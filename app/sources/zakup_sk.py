"""zakup.sk.kz — портал закупок АО «Самрук-Қазына».

Интерфейс сайта (SPA) сам получает объявления JSON-запросом:
  POST https://zakup.sk.kz/eprocsearch/api/external/4dv3rts/filter
  тело: {"query": "...", "advertStatus": "PUBLISHED", "lotStatus": "PUBLISHED", ...}
  ответ: список объявлений (у каждого есть "number").
Эндпоинт найден в открытом парсере github.com/AmbreKitsune/Parser-for-zakup.sk.kz.
Параметры пагинации и имена остальных полей ответа сверяются на этапе 1
(DevTools → Network на странице поиска) и задаются в config.yaml без правки кода.
"""
from __future__ import annotations

from datetime import datetime

from ..models import Lot
from .base import Source


class ZakupSk(Source):
    name = "zakup_sk"

    def fetch(self, since_days: int) -> list[Lot]:
        site = self.cfg.get("site", "https://zakup.sk.kz")
        url = site + self.cfg.get("search_path", "/eprocsearch/api/external/4dv3rts/filter")
        size = int(self.cfg.get("page_size", 50))
        lots = []
        for status in self.cfg.get("statuses", ["PUBLISHED"]):
            for page in range(int(self.cfg.get("max_pages", 20))):
                params = {k: v.format(page=page, size=size)
                          for k, v in (self.cfg.get("page_params") or {}).items()}
                body = {"query": self.cfg.get("query", ""),
                        "advertStatus": status, "lotStatus": status,
                        **(self.cfg.get("extra_body") or {})}
                self._check_robots(url)
                data = self.post(url, params=params, json=body).json()
                items = data if isinstance(data, list) else data.get(
                    self.cfg.get("items_key", "content"), [])
                if not items:
                    break
                lots.extend(l for l in (parse_item(i, self.cfg) for i in items) if l)
                if len(items) < size:
                    break
        return lots


    def probe(self) -> dict:
        """Один запрос без разбора — чтобы увидеть реальные поля ответа на этапе 1."""
        site = self.cfg.get("site", "https://zakup.sk.kz")
        url = site + self.cfg.get("search_path", "/eprocsearch/api/external/4dv3rts/filter")
        r = self.post(url, params={k: v.format(page=0, size=5) for k, v in
                                   (self.cfg.get("page_params") or {}).items()},
                      json={"query": "", "advertStatus": "PUBLISHED", "lotStatus": "PUBLISHED"})
        return {"status": r.status_code, "url": str(r.request.url), "body": r.json()}


def parse_item(item: dict, cfg: dict) -> Lot | None:
    f = cfg.get("fields") or {}
    number = _pick(item, f.get("id", ["number"]))
    if not number:
        return None
    site = cfg.get("site", "https://zakup.sk.kz")
    return Lot(
        source="zakup_sk",
        external_id=str(number),
        title=_pick(item, f.get("title", ["nameRu", "name", "title"])) or "",
        organizer=_pick(item, f.get("organizer", ["customerNameRu", "customerName", "organizerName"])) or "",
        published_at=_dt(_pick(item, f.get("published", ["publishDate", "startDate"]))),
        deadline=_dt(_pick(item, f.get("deadline", ["endDate", "acceptanceEndDate"]))),
        budget=_num(_pick(item, f.get("budget", ["sum", "amount", "totalSum"]))),
        description=_pick(item, f.get("description", ["descriptionRu", "description"])) or "",
        url=f"{site}/#/ext(popup:item/{number}/advert)",
    )


def _pick(d: dict, keys):
    """Первое непустое значение по списку ключей; ключ может быть путём через точку."""
    for k in keys if isinstance(keys, list) else [keys]:
        v = d
        for part in k.split("."):
            v = v.get(part) if isinstance(v, dict) else None
        if v not in (None, ""):
            return v
    return None


def _dt(v):
    if not v:
        return None
    if isinstance(v, (int, float)):                       # epoch ms
        return datetime.fromtimestamp(v / 1000)
    s = str(v).replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _num(v):
    try:
        return float(str(v).replace(" ", "").replace(",", ".")) if v not in (None, "") else None
    except ValueError:
        return None
