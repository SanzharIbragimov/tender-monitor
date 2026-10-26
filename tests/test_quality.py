from datetime import datetime

from app import db, quality
from app.models import Lot


def _lot(con, ext, title, score, organizer="ГУ «Тест»", deadline=datetime(2026, 11, 20)):
    db.upsert(con, Lot(source="goszakup", external_id=ext, title=title, organizer=organizer,
                       deadline=deadline, url=f"https://x/{ext}"))
    lid = con.execute("SELECT id FROM lots WHERE key=?", (f"goszakup:{ext}",)).fetchone()[0]
    db.save_score(con, lid, score, "development", f"оценка {score}", "rules")
    return lid


def test_evaluate_recall_precision(cfg, tmp_path):
    con = db.connect(cfg["db_path"])
    _lot(con, "1", "Разработка ИС", 90)       # релевантный, отобран
    _lot(con, "2", "Внедрение СЭД", 40)       # релевантный, пропущен
    _lot(con, "3", "Поставка мебели", 70)     # нерелевантный, но отобран
    _lot(con, "4", "Канцтовары", 0)           # нерелевантный, отсеян
    sample = tmp_path / "control.csv"
    sample.write_text("key;label\ngoszakup:1;1\ngoszakup:2;1\ngoszakup:3;0\ngoszakup:4;0\ngoszakup:99;1\n",
                      encoding="utf-8")
    ev = quality.evaluate(con, str(sample), threshold=60)
    assert (ev["tp"], ev["fn"], ev["fp"], ev["tn"]) == (1, 2, 1, 1)
    assert round(ev["recall"], 2) == 0.33 and ev["precision"] == 0.5
    assert {e["kind"] for e in ev["errors"]} == {"пропущен", "лишний"}
    assert any(e["why"] == "лот не собран" for e in ev["errors"])


def test_duplicates_and_delivery(cfg):
    con = db.connect(cfg["db_path"])
    a = _lot(con, "1", "Разработка ИС", 90)
    b = _lot(con, "2", "Внедрение СЭД", 80)
    db.mark_digested(con, [a, b], "день 1")
    db.mark_digested(con, [a], "день 2")      # повтор без изменений
    du = quality.duplicate_rate(con, "0000", "9999")
    assert (du["items"], du["dups"]) == (3, 1)
    dl = quality.delivery(con, "0000", "9999")
    assert dl["days"] == 1 and dl["streak"] == 1


def test_field_completeness_and_report(cfg):
    con = db.connect(cfg["db_path"])
    _lot(con, "1", "Разработка ИС", 90)
    _lot(con, "2", "Внедрение СЭД", 80, organizer="")
    db.log_run(con, "collect", "goszakup", True, 2)
    db.log_run(con, "collect", "goszakup", False, error="timeout")
    m = {"runs": quality.run_metrics(con, "0000", "9999", ["goszakup"]),
         "fields": quality.field_completeness(con, "0000", "9999"),
         "dups": quality.duplicate_rate(con, "0000", "9999"),
         "delivery": quality.delivery(con, "0000", "9999"), "eval": None}
    assert m["fields"]["rate"] == 0.5 and m["fields"]["missing"]["organizer"] == 1
    assert m["runs"]["goszakup"]["rate"] == 0.5
    md = quality.render(m, ("2026-11-01", "2026-11-15"), 60)
    assert "Полнота полей" in md and "не выполнен" in md


def test_send_digest_records_journal(cfg, monkeypatch):
    from app import main
    sent = []
    monkeypatch.setattr("app.digest.send", lambda cfg, to, subj, html: sent.append((to, subj)))
    con = db.connect(cfg["db_path"])
    _lot(con, "1", "Разработка ИС", 90)
    assert main.send_digest(con, cfg) == 1
    assert main.send_digest(con, cfg) == 0           # повторно не отправляется; уходит «лотов нет»
    assert "нет" in sent[1][1]
    assert con.execute("SELECT COUNT(*) FROM digests").fetchone()[0] == 2
    assert quality.duplicate_rate(con, "0000", "9999")["dups"] == 0
