"""Отчёт о качестве по критериям приёмки (п. 8.4 и 9 ТЗ).

report   — источники, полнота полей, повторы, доставка (из журнала и базы);
evaluate — полнота и точность отбора на контрольной выборке Заказчика.
"""
from __future__ import annotations

import csv
import random
from datetime import date, datetime, timedelta

THRESHOLDS = {"runs": 0.95, "fields": 0.90, "dups": 0.02, "recall": 0.80,
              "precision": 0.70, "delivery_days": 14}


def run_metrics(con, date_from: str, date_to: str, sources: list[str]) -> dict:
    """Доля успешных запусков сбора по каждому включённому источнику."""
    out = {}
    for s in sources:
        total, ok = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(ok),0) FROM runs WHERE stage='collect' AND source=? "
            "AND ts >= ? AND ts < ?", (s, date_from, date_to)).fetchone()
        out[s] = {"total": total, "ok": ok, "rate": ok / total if total else None}
    return out


def field_completeness(con, date_from: str, date_to: str, sample: int = 100, seed: int = 42) -> dict:
    """Случайная выборка лотов: заполнены название, организатор, срок подачи, ссылка."""
    rows = con.execute("SELECT title, organizer, deadline, url, source FROM lots "
                       "WHERE first_seen >= ? AND first_seen < ?", (date_from, date_to)).fetchall()
    rows = random.Random(seed).sample(rows, min(sample, len(rows)))
    full = [r for r in rows if all((r[k] or "").strip() for k in ("title", "organizer", "deadline", "url"))]
    missing = {k: sum(1 for r in rows if not (r[k] or "").strip())
               for k in ("title", "organizer", "deadline", "url")}
    return {"sample": len(rows), "full": len(full),
            "rate": len(full) / len(rows) if rows else None, "missing": missing}


def duplicate_rate(con, date_from: str, date_to: str) -> dict:
    """Доля позиций дайджестов, которые уже отправлялись раньше (без учёта помеченных «изменён»)."""
    items = con.execute(
        "SELECT i.fingerprint, i.changed, d.ts FROM digest_items i JOIN digests d ON d.id = i.digest_id "
        "WHERE d.ts >= ? AND d.ts < ? ORDER BY d.ts, i.rowid", (date_from, date_to)).fetchall()
    seen, dups = set(), 0
    for it in items:
        if it["fingerprint"] in seen and not it["changed"]:
            dups += 1
        seen.add(it["fingerprint"])
    return {"items": len(items), "dups": dups, "rate": dups / len(items) if items else None}


def delivery(con, date_from: str, date_to: str) -> dict:
    """Дни, в которые дайджест ушёл, и самая длинная серия подряд."""
    days = sorted({date.fromisoformat(r[0][:10]) for r in con.execute(
        "SELECT ts FROM digests WHERE ts >= ? AND ts < ?", (date_from, date_to))})
    best = cur = 0
    for i, d in enumerate(days):
        cur = cur + 1 if i and d - days[i - 1] == timedelta(days=1) else 1
        best = max(best, cur)
    failed = con.execute("SELECT COUNT(*) FROM runs WHERE stage='digest' AND ok=0 AND ts >= ? AND ts < ?",
                         (date_from, date_to)).fetchone()[0]
    return {"days": len(days), "streak": best, "failed": failed}


def evaluate(con, sample_csv: str, threshold: int) -> dict:
    """Контрольная выборка: CSV с колонками key (source:external_id) или url, и label (1/0).

    Лот считается отобранным, если его оценка ≥ порога дайджеста.
    Лот из выборки, которого нет в базе, считается пропущенным.
    """
    with open(sample_csv, encoding="utf-8-sig") as f:
        text = f.read()
    delim = ";" if ";" in text.splitlines()[0] else ","
    rows = list(csv.DictReader(text.splitlines(), delimiter=delim))
    tp = fp = fn = tn = 0
    errors = []
    for r in rows:
        label = str(r.get("label", "")).strip() in ("1", "да", "yes", "true", "релевантный")
        key, url = (r.get("key") or "").strip(), (r.get("url") or "").strip()
        lot = con.execute("SELECT * FROM lots WHERE key = ? OR (url != '' AND url = ?)", (key, url)).fetchone()
        picked = bool(lot and lot["score"] is not None and lot["score"] >= threshold)
        if label and picked:
            tp += 1
        elif label and not picked:
            fn += 1
            errors.append({"kind": "пропущен", "key": key or url,
                           "title": lot["title"] if lot else "нет в базе",
                           "score": lot["score"] if lot else None,
                           "why": lot["explanation"] if lot else "лот не собран"})
        elif picked:
            fp += 1
            errors.append({"kind": "лишний", "key": key or url, "title": lot["title"],
                           "score": lot["score"], "why": lot["explanation"]})
        else:
            tn += 1
    return {"n": len(rows), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "recall": tp / (tp + fn) if tp + fn else None,
            "precision": tp / (tp + fp) if tp + fp else None, "errors": errors}


def render(m: dict, period: tuple[str, str], threshold: int) -> str:
    """Отчёт в Markdown."""
    def pct(x):
        return "—" if x is None else f"{x:.0%}"

    def mark(ok):
        return "—" if ok is None else ("выполнен" if ok else "не выполнен")

    title = ("весь период" if period == ("0000", "9999")
             else f"{period[0] if period[0] != '0000' else '…'} — {period[1] if period[1] != '9999' else '…'}")
    lines = [f"# Отчёт о качестве: {title}", "",
             f"Сформирован {datetime.now():%d.%m.%Y %H:%M}. Порог отбора в дайджест: {threshold}.", "",
             "## Критерии приёмки", "", "| Критерий | Значение | Порог | Итог |", "| --- | --- | --- | --- |"]
    runs = m["runs"]
    rates = [v["rate"] for v in runs.values() if v["rate"] is not None]
    worst = min(rates) if rates else None
    lines.append(f"| Источники, успешных запусков | {len(runs)} ист., мин. {pct(worst)} | "
                 f"≥ 5 ист., ≥ 95% | {mark(None if worst is None else len(runs) >= 5 and worst >= THRESHOLDS['runs'])} |")
    fc = m["fields"]
    lines.append(f"| Полнота полей (выборка {fc['sample']}) | {pct(fc['rate'])} | ≥ 90% | "
                 f"{mark(None if fc['rate'] is None else fc['rate'] >= THRESHOLDS['fields'])} |")
    du = m["dups"]
    lines.append(f"| Повторы в дайджестах | {du['dups']} из {du['items']} ({pct(du['rate'])}) | ≤ 2% | "
                 f"{mark(None if du['rate'] is None else du['rate'] <= THRESHOLDS['dups'])} |")
    if m.get("eval"):
        ev = m["eval"]
        lines.append(f"| Полнота отбора (recall) | {pct(ev['recall'])} | ≥ 80% | "
                     f"{mark(None if ev['recall'] is None else ev['recall'] >= THRESHOLDS['recall'])} |")
        lines.append(f"| Точность отбора (precision) | {pct(ev['precision'])} | ≥ 70% | "
                     f"{mark(None if ev['precision'] is None else ev['precision'] >= THRESHOLDS['precision'])} |")
    dl = m["delivery"]
    lines.append(f"| Доставка дайджеста | {dl['streak']} дн. подряд, сбоев {dl['failed']} | 14 дн. подряд | "
                 f"{mark(dl['streak'] >= THRESHOLDS['delivery_days'] if dl['days'] else None)} |")

    lines += ["", "## Запуски по источникам", "", "| Источник | Запусков | Успешных | Доля |", "| --- | --- | --- | --- |"]
    lines += [f"| {s} | {v['total']} | {v['ok']} | {pct(v['rate'])} |" for s, v in runs.items()]
    if fc["sample"]:
        lines += ["", "Незаполненные поля в выборке: " + ", ".join(
            f"{k} — {v}" for k, v in fc["missing"].items()) + "."]
    if m.get("eval"):
        ev = m["eval"]
        lines += ["", "## Контрольная выборка", "",
                  f"{ev['n']} лотов: верно отобрано {ev['tp']}, лишних {ev['fp']}, "
                  f"пропущено {ev['fn']}, верно отсеяно {ev['tn']}.", ""]
        if ev["errors"]:
            lines += ["| Ошибка | Лот | Оценка | Пояснение сервиса |", "| --- | --- | --- | --- |"]
            lines += [f"| {e['kind']} | {e['title']} ({e['key']}) | {e['score'] if e['score'] is not None else '—'} | "
                      f"{(e['why'] or '').replace('|', '/')} |" for e in ev["errors"]]
    return "\n".join(lines) + "\n"
