from datetime import datetime

import httpx

from app import db, digest, scoring
from app.models import Lot
from app.scoring.llm import parse_answer
from app.scoring.rules import RuleScorer
from app.sources.goszakup import Goszakup, parse_lot
from app.sources.html import parse_list

from .conftest import FIX, mock_client


def _collect(cfg, payload, monkeypatch):
    monkeypatch.setattr("app.sources.goszakup.datetime", _FixedNow)
    src = Goszakup(cfg["sources"]["goszakup"], cfg["secrets"])
    src.client = mock_client(payload)
    src.delay = 0
    con = db.connect(cfg["db_path"])
    for lot in src.fetch(2):
        db.upsert(con, lot)
    con.commit()
    return con


# --- сбор ---
def test_goszakup_parse_fields(goszakup_json):
    l = parse_lot(goszakup_json["data"]["Lots"][0])
    assert l.title.startswith("Разработка информационной системы")
    assert l.organizer and l.deadline == datetime(2026, 10, 27, 18, 0)
    assert l.url == "https://goszakup.gov.kz/ru/announce/index/900001"
    assert l.budget == 48_500_000
    assert l.extra["enstru"] == ["620110.000.000001"]


def test_goszakup_kazakh_title_fallback(goszakup_json):
    l = parse_lot(goszakup_json["data"]["Lots"][3])
    assert l.title == "Ақпараттық жүйені әзірлеу және енгізу"


def test_goszakup_skips_closed_and_deleted(cfg, goszakup_json, monkeypatch):
    con = _collect(cfg, goszakup_json, monkeypatch)
    titles = [r[0] for r in con.execute("SELECT title FROM lots")]
    assert len(titles) == 6
    assert not any("приём завершён" in t for t in titles)


def test_goszakup_request_shape(cfg, goszakup_json, monkeypatch):
    seen = {}

    def handler(request):
        import json as _j
        seen.update(_j.loads(request.content))
        return httpx.Response(200, json=goszakup_json)
    monkeypatch.setattr("app.sources.goszakup.datetime", _FixedNow)
    src = Goszakup(cfg["sources"]["goszakup"], cfg["secrets"])
    src.client = httpx.Client(transport=httpx.MockTransport(handler))
    src.delay = 0
    src.fetch(2)
    v = seen["variables"]
    assert v["filter"]["indexDate"] == ["2026-10-23 08:00:00", "2026-10-26 08:00:00"]
    assert 1 <= v["limit"] <= 200 and v["after"] is None
    assert "Lots(filter: $filter" in seen["query"]


def test_html_parser():
    cfg = {"list_url": "https://example.kz/list?page={page}", "selectors": {
        "item": ".tender", "title": ".name", "link": ".name", "organizer": ".org",
        "deadline": ".deadline", "budget": ".sum"}}
    lots = parse_list((FIX / "html_list.html").read_text(encoding="utf-8"), "test", cfg)
    assert len(lots) == 2
    assert lots[0].external_id == "123456"
    assert lots[0].url == "https://example.kz/tender/123456"
    assert lots[0].deadline == datetime(2026, 11, 5, 18, 0)
    assert lots[0].budget == 12_500_000.0


# --- дедупликация и изменения ---
def test_dedup_and_changes(cfg, goszakup_json, monkeypatch):
    con = _collect(cfg, goszakup_json, monkeypatch)
    assert con.execute("SELECT COUNT(*) FROM lots").fetchone()[0] == 6
    # повторный сбор тех же данных — без новых строк
    lot = parse_lot(goszakup_json["data"]["Lots"][0])
    assert db.upsert(con, lot) == "same"
    # перенос срока — лот помечается изменённым
    lot.deadline = datetime(2026, 10, 30, 18, 0)
    assert db.upsert(con, lot) == "changed"
    # тот же лот из другого источника — дубль
    twin = Lot(source="other", external_id="x1", title=lot.title,
               organizer=lot.organizer, deadline=lot.deadline)
    assert db.upsert(con, twin) == "duplicate"


# --- оценка ---
def test_rules_relevant_and_not(cfg):
    r = RuleScorer(cfg["scoring"])
    dev = r.score("Разработка информационной системы", "веб-портал, интеграция")
    assert dev.score >= 60 and dev.direction == "development"
    staff = r.score("Техническая поддержка и администрирование", "привлечение специалистов")
    assert staff.direction == "staffing"
    junk = r.score("Приобретение канцелярских товаров", "бумага, ручки")
    assert junk.score == 0
    kz = r.score("Ақпараттық жүйені әзірлеу")
    assert kz.score > 0 and kz.direction == "development"


def test_llm_answer_parsing():
    s, d, why = parse_answer('Ответ: {"score": 87, "direction": "development", "explanation": "ИС"}',
                             {"development", "boxed", "staffing", "none"})
    assert (s, d, why) == (87, "development", "ИС")
    s, d, _ = parse_answer('{"score": 150, "direction": "none", "explanation": ""}', {"none"})
    assert s == 100 and d is None


# --- дайджест ---
def test_digest_rules_only(cfg, goszakup_json, monkeypatch):
    monkeypatch.setattr("app.digest.datetime", _FixedNow)
    con = _collect(cfg, goszakup_json, monkeypatch)
    stats = scoring.score_pending(con, cfg)
    assert stats["llm"] == 0                        # без ключа — только правила
    subject, html, ids = digest.build(con, cfg)
    assert "канцеляр" not in html.lower() and "картридж" not in html.lower()
    assert "Разработка информационной системы" in html
    assert "Срок подачи в ближайшие" in html       # лот со сроком 27.10 — горящий
    assert len(ids) >= 3


def test_empty_digest(cfg, monkeypatch):
    monkeypatch.setattr("app.digest.datetime", _FixedNow)
    con = db.connect(cfg["db_path"])
    subject, html, ids = digest.build(con, cfg)
    assert ids == [] and "нет" in subject


class _FixedNow(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 25, 8, 0, tzinfo=tz)


# --- zakup.sk.kz ---
def test_zakup_sk_request_and_mapping(cfg):
    from app.sources.zakup_sk import ZakupSk
    calls = []

    def handler(request):
        import json as _j
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        body = _j.loads(request.content)
        calls.append((dict(request.url.params), body))
        if request.url.params.get("page") == "0" and body["advertStatus"] == "PUBLISHED":
            return httpx.Response(200, json=[{"number": "SK-1", "nameRu": "Разработка CRM",
                "customerNameRu": "АО «Тест»", "endDate": "2026-11-05T18:00:00", "sum": "5000000"}])
        return httpx.Response(200, json=[])
    scfg = {**cfg["sources"]["zakup_sk"], "statuses": ["PUBLISHED"]}
    src = ZakupSk(scfg, cfg["secrets"])
    src.client = httpx.Client(transport=httpx.MockTransport(handler))
    src.delay = 0
    lots = src.fetch(2)
    assert calls[0][0] == {"page": "0", "size": "50"}
    assert calls[0][1]["lotStatus"] == "PUBLISHED"
    l = lots[0]
    assert (l.external_id, l.title, l.budget) == ("SK-1", "Разработка CRM", 5_000_000)
    assert l.deadline == datetime(2026, 11, 5, 18, 0)
    assert l.url.endswith("item/SK-1/advert)")
