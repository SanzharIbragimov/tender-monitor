"""Точка входа.

  python -m app.main run          — сбор → оценка → дайджест (один раз)
  python -m app.main serve        — по расписанию из config.yaml
  python -m app.main collect | score | digest [--dry-run out.html]
  python -m app.main export --from 2026-11-01 --to 2026-11-15 --out lots.csv
  python -m app.main probe --source zakup_sk   — сырой ответ источника для сверки полей
  python -m app.main report --from 2026-11-01 --to 2026-11-15 --sample control.csv  — отчёт о качестве
"""
from __future__ import annotations

import argparse
import logging
import traceback

from . import config, db, digest, scoring, sources

log = logging.getLogger("tender-monitor")


def collect(con, cfg) -> dict:
    stats, failures = {}, []
    for src in sources.build(cfg):
        try:
            lots = src.fetch(int(cfg.get("lookback_days", 2)))
            counts = {"new": 0, "changed": 0, "same": 0, "duplicate": 0}
            for lot in lots:
                counts[db.upsert(con, lot)] += 1
            con.commit()
            db.log_run(con, "collect", src.name, True, len(lots))
            stats[src.name] = counts
        except Exception as e:                       # сбой одного источника не останавливает остальные
            con.rollback()
            db.log_run(con, "collect", src.name, False, error=traceback.format_exc())
            failures.append(f"{src.name}: {e}")
            stats[src.name] = {"error": str(e)}
    if failures:
        digest.alert(cfg, "Сбой источников:\n" + "\n".join(failures))
    return stats


def score(con, cfg) -> dict:
    s = scoring.score_pending(con, cfg)
    db.log_run(con, "score", "", True, s["rules_only"] + s["llm"] + s["llm_errors"])
    return s


def send_digest(con, cfg, dry_run: str | None = None) -> int:
    subject, html, ids = digest.build(con, cfg)
    if dry_run:
        with open(dry_run, "w", encoding="utf-8") as f:
            f.write(html)
        log.info("дайджест сохранён в %s (%s)", dry_run, subject)
        return len(ids)
    try:
        digest.send(cfg, cfg["digest"]["recipients"], subject, html)
        db.mark_digested(con, ids, subject)
        db.log_run(con, "digest", "", True, len(ids))
    except Exception as e:
        db.log_run(con, "digest", "", False, error=traceback.format_exc())
        digest.alert(cfg, f"Сбой рассылки: {e}")
        raise
    con.commit()
    return len(ids)


def run_all(cfg) -> None:
    con = db.connect(cfg["db_path"])
    log.info("сбор: %s", collect(con, cfg))
    log.info("оценка: %s", score(con, cfg))
    log.info("в дайджесте: %s", send_digest(con, cfg))


def serve(cfg) -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    hh, mm = cfg["digest"].get("send_at", "08:00").split(":")
    sched = BlockingScheduler(timezone=cfg.get("timezone", "Asia/Almaty"))
    # сбор и оценка за 60 минут до рассылки, рассылка — в заданное время
    sched.add_job(lambda: _safe(_collect_score, cfg),
                  CronTrigger(hour=(int(hh) - 1) % 24, minute=int(mm)), name="сбор и оценка")
    sched.add_job(lambda: _safe(_digest_only, cfg), CronTrigger(hour=int(hh), minute=int(mm)), name="рассылка")
    log.info("расписание: сбор %02d:%s, рассылка %s:%s", (int(hh) - 1) % 24, mm, hh, mm)
    sched.start()


def _collect_score(cfg):
    con = db.connect(cfg["db_path"])
    log.info("сбор: %s", collect(con, cfg))
    log.info("оценка: %s", score(con, cfg))


def _digest_only(cfg):
    con = db.connect(cfg["db_path"])
    score(con, cfg)          # дооценить, если что-то пришло позже
    log.info("в дайджесте: %s", send_digest(con, cfg))


def _safe(fn, cfg):
    try:
        fn(cfg)
    except Exception:
        log.exception("ошибка задания")


def main():
    p = argparse.ArgumentParser(prog="tender-monitor")
    p.add_argument("cmd", choices=["run", "serve", "collect", "score", "digest", "export", "probe", "report"])
    p.add_argument("--config", default=None)
    p.add_argument("--dry-run", metavar="FILE", help="digest: сохранить HTML вместо отправки")
    p.add_argument("--from", dest="date_from")
    p.add_argument("--to", dest="date_to")
    p.add_argument("--out", default="lots.csv")
    p.add_argument("--source", default="zakup_sk", help="probe: какой источник проверить")
    p.add_argument("--sample", help="report: CSV контрольной выборки (key или url; label 1/0)")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = config.load(a.config) if a.config else config.load()
    con = db.connect(cfg["db_path"])
    if a.cmd == "run":
        run_all(cfg)
    elif a.cmd == "serve":
        serve(cfg)
    elif a.cmd == "collect":
        log.info("сбор: %s", collect(con, cfg))
    elif a.cmd == "score":
        log.info("оценка: %s", score(con, cfg))
    elif a.cmd == "digest":
        send_digest(con, cfg, a.dry_run)
    elif a.cmd == "probe":
        import json as _json
        scfg = {**cfg["sources"][a.source], "enabled": True}
        src = sources.build({"sources": {a.source: scfg}, "secrets": cfg["secrets"]})[0]
        print(_json.dumps(src.probe(), ensure_ascii=False, indent=1)[:5000])
    elif a.cmd == "report":
        from . import quality
        period = (a.date_from or "0000", a.date_to or "9999")
        threshold = int(cfg["digest"].get("threshold", 60))
        enabled = [n for n, sc in cfg["sources"].items() if sc.get("enabled", True)]
        m = {"runs": quality.run_metrics(con, *period, enabled),
             "fields": quality.field_completeness(con, *period),
             "dups": quality.duplicate_rate(con, *period),
             "delivery": quality.delivery(con, *period),
             "eval": quality.evaluate(con, a.sample, threshold) if a.sample else None}
        out = a.out if a.out != "lots.csv" else "quality_report.md"
        with open(out, "w", encoding="utf-8") as f:
            f.write(quality.render(m, period, threshold))
        log.info("отчёт о качестве: %s", out)
    elif a.cmd == "export":
        n = db.export_csv(con, a.out, a.date_from or "0000", a.date_to or "9999")
        log.info("выгружено %d лотов в %s", n, a.out)


if __name__ == "__main__":
    main()
