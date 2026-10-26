"""Базовый коннектор: вежливый HTTP-клиент (п. 5 ТЗ — robots.txt, ограничение частоты)."""
from __future__ import annotations

import logging
import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from ..models import Lot

log = logging.getLogger(__name__)
USER_AGENT = "TenderMonitor/0.1 (+public data only; contact: see config)"


class Source:
    """Каждый источник наследует этот класс и реализует fetch()."""
    name = "base"

    def __init__(self, cfg: dict, secrets: dict):
        self.cfg = cfg
        self.secrets = secrets
        self.delay = float(cfg.get("delay_sec", 1.5))
        self._last = 0.0
        self._robots: dict[str, RobotFileParser] = {}
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True)

    def fetch(self, since_days: int) -> list[Lot]:
        raise NotImplementedError

    # --- HTTP ---
    def get(self, url: str, **kw) -> httpx.Response:
        self._check_robots(url)
        return self._request("GET", url, **kw)

    def post(self, url: str, **kw) -> httpx.Response:
        return self._request("POST", url, **kw)

    def _request(self, method: str, url: str, **kw) -> httpx.Response:
        for attempt in range(3):
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                r = self.client.request(method, url, **kw)
                if r.status_code in (429, 502, 503, 504):
                    raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
                r.raise_for_status()
                return r
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                if attempt == 2:
                    raise
                log.warning("%s: %s, повтор %d", self.name, e, attempt + 1)
                time.sleep(5 * (attempt + 1))
        raise RuntimeError("unreachable")

    def _check_robots(self, url: str) -> None:
        if not self.cfg.get("respect_robots", True):
            return
        host = "{0.scheme}://{0.netloc}".format(urlparse(url))
        rp = self._robots.get(host)
        if rp is None:
            rp = RobotFileParser()
            try:
                r = self.client.get(urljoin(host, "/robots.txt"))
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except httpx.HTTPError:
                rp.parse([])
            self._robots[host] = rp
        if not rp.can_fetch(USER_AGENT, url):
            raise PermissionError(f"robots.txt запрещает {url}")
