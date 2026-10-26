"""goszakup.gov.kz — официальный API OWS v3 (GraphQL), доступ по токену.

Схема сверена интроспекцией: https://ows.goszakup.gov.kz/help/v3/schema/
- лоты выбираются фильтром indexDate [с, по] — новые и изменённые записи;
- в работу идут только лоты, по которым ещё идёт приём заявок (TrdBuy.endDate в будущем);
- коды ЕНС ТРУ берутся из пунктов плана лота (Plans.refEnstruCode):
  Lots.enstruList содержит внутренние id справочника, а не коды.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from ..models import Lot
from .base import Source

QUERY = (Path(__file__).with_name("goszakup.graphql")).read_text(encoding="utf-8")
PUBLIC_URL = "https://goszakup.gov.kz/ru/announce/index/{id}"
FMT = "%Y-%m-%d %H:%M:%S"


class Goszakup(Source):
    name = "goszakup"

    def fetch(self, since_days: int) -> list[Lot]:
        token = self.secrets.get("goszakup_token")
        if not token:
            raise RuntimeError("нет GOSZAKUP_TOKEN — токен оформляет Заказчик")
        url = self.cfg.get("endpoint", "https://ows.goszakup.gov.kz/v3/graphql")
        now = datetime.now()
        window = [(now - timedelta(days=since_days)).strftime(FMT),
                  (now + timedelta(days=1)).strftime(FMT)]
        limit = min(int(self.cfg.get("page_size", 200)), 200)      # API принимает 1–200
        after, lots = None, []
        for _ in range(int(self.cfg.get("max_pages", 100))):
            r = self.post(url, json={"query": QUERY, "variables": {
                "filter": {"indexDate": window}, "limit": limit, "after": after}},
                headers={"Authorization": f"Bearer {token}"})
            data = r.json()
            if data.get("errors"):
                raise RuntimeError(f"GraphQL: {data['errors']}")
            items = (data.get("data") or {}).get("Lots") or []
            lots.extend(l for l in (parse_lot(i) for i in items) if l and _open(l, now))
            page = (data.get("extensions") or {}).get("pageInfo") or {}
            if not page.get("hasNextPage") or not items:
                break
            after = page.get("lastId")
        return lots


def parse_lot(item: dict) -> Lot | None:
    if item.get("isDeleted"):
        return None
    buy = item.get("TrdBuy") or {}
    desc = " ".join(x for x in (item.get("descriptionRu"), item.get("descriptionKz")) if x)
    codes = sorted({p.get("refEnstruCode") for p in (item.get("Plans") or []) if p.get("refEnstruCode")})
    buy_id = buy.get("id") or item.get("trdBuyId")
    return Lot(
        source="goszakup",
        external_id=str(item.get("id")),
        title=item.get("nameRu") or item.get("nameKz") or buy.get("nameRu") or "",
        organizer=buy.get("orgNameRu") or item.get("customerNameRu") or "",
        region=", ".join(buy.get("kato") or []),
        published_at=_dt(buy.get("publishDate")),
        deadline=_dt(buy.get("endDate")),
        budget=_num(item.get("amount")),
        description=desc,
        url=PUBLIC_URL.format(id=buy_id),
        extra={"number_anno": buy.get("numberAnno") or item.get("trdBuyNumberAnno"),
               "lot_number": item.get("lotNumber"), "enstru": codes,
               "buy_status": (buy.get("RefBuyStatus") or {}).get("nameRu"),
               "customer": item.get("customerNameRu")},
    )


def _open(lot: Lot, now: datetime) -> bool:
    """Приём заявок ещё идёт (или срок неизвестен)."""
    return lot.deadline is None or lot.deadline >= now


def _dt(s):
    if not s:
        return None
    for fmt in (FMT, "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    return None


def _num(x):
    try:
        return float(x) if x not in (None, "") else None
    except (TypeError, ValueError):
        return None
