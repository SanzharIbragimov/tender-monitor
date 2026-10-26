"""Универсальный разбор публичных страниц по CSS-селекторам из config.yaml.

Подходит для zakup.sk.kz, nadloc.kz и других площадок без API.
Новый источник = блок в config.yaml (селекторы), код не меняется.
Если площадка отдаёт данные JSON-запросом из своего интерфейса —
лучше написать отдельный коннектор, как goszakup.py.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Lot
from .base import Source


class HtmlSource(Source):
    def __init__(self, name: str, cfg: dict, secrets: dict):
        super().__init__(cfg, secrets)
        self.name = name

    def fetch(self, since_days: int) -> list[Lot]:
        lots = []
        for page in range(1, int(self.cfg.get("max_pages", 5)) + 1):
            url = self.cfg["list_url"].format(page=page)
            html = self.get(url).text
            batch = parse_list(html, self.name, self.cfg)
            if not batch:
                break
            lots.extend(batch)
        return lots


def parse_list(html: str, source: str, cfg: dict) -> list[Lot]:
    sel = cfg["selectors"]
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for node in soup.select(sel["item"]):
        def text(key):
            s = sel.get(key)
            el = node.select_one(s) if s else None
            return el.get_text(" ", strip=True) if el else ""
        link = node.select_one(sel["link"]) if sel.get("link") else None
        href = urljoin(cfg["list_url"], link["href"]) if link and link.get("href") else ""
        ext_id = text("id") or _id_from_url(href)
        title = text("title")
        if not title or not ext_id:
            continue
        out.append(Lot(
            source=source, external_id=ext_id, title=title,
            organizer=text("organizer"), region=text("region"),
            published_at=_date(text("published"), cfg),
            deadline=_date(text("deadline"), cfg),
            budget=_money(text("budget")), description=text("description"), url=href))
    return out


def _id_from_url(url: str) -> str:
    m = re.search(r"(\d{4,})", url or "")
    return m.group(1) if m else ""


_DATE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}(?:\s+\d{2}:\d{2})?|\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2})?")


def _date(s: str, cfg: dict):
    m = _DATE_RE.search(s or "")
    if not m:
        return None
    s = m.group(0).replace("T", " ")
    for fmt in cfg.get("date_formats", ["%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d"]):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _money(s: str):
    digits = re.sub(r"[^\d,\.]", "", s or "").replace(",", ".")
    if digits.count(".") > 1:
        digits = digits.replace(".", "", digits.count(".") - 1)
    try:
        return float(digits) if digits else None
    except ValueError:
        return None
