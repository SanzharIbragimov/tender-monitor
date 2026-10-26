"""Хранилище SQLite: лоты, оценки, журнал запусков (п. 4.3, 4.6, 6 ТЗ).

Схема создаётся миграциями из папки migrations/ (по номеру файла).
"""
from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Lot

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    _migrate(con)
    return con


def _migrate(con: sqlite3.Connection) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER)")
    cur = con.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
    for f in sorted(MIGRATIONS.glob("*.sql")):
        ver = int(f.name.split("_")[0])
        if ver > cur:
            con.executescript(f.read_text(encoding="utf-8"))
            con.execute("INSERT INTO schema_version VALUES (?)", (ver,))
    con.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert(con: sqlite3.Connection, lot: Lot) -> str:
    """Сохраняет лот. Возвращает статус: new | changed | same | duplicate."""
    row = con.execute("SELECT id, content_hash FROM lots WHERE key = ?", (lot.key,)).fetchone()
    if row:
        if row["content_hash"] == lot.content_hash:
            con.execute("UPDATE lots SET last_seen = ? WHERE id = ?", (_now(), row["id"]))
            return "same"
        con.execute(
            """UPDATE lots SET title=?, organizer=?, region=?, deadline=?, budget=?,
               description=?, url=?, content_hash=?, fingerprint=?, changed=1,
               scored=0, digested=0, last_seen=? WHERE id=?""",
            (lot.title, lot.organizer, lot.region, _iso(lot.deadline), lot.budget,
             lot.description, lot.url, lot.content_hash, lot.fingerprint, _now(), row["id"]))
        return "changed"

    # тот же лот уже пришёл из другого источника?
    twin = con.execute(
        "SELECT id FROM lots WHERE fingerprint = ? AND source != ? AND dup_of IS NULL",
        (lot.fingerprint, lot.source)).fetchone()
    con.execute(
        """INSERT INTO lots (key, source, external_id, title, organizer, region,
           published_at, deadline, budget, description, url, extra, content_hash,
           fingerprint, dup_of, first_seen, last_seen)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (lot.key, lot.source, lot.external_id, lot.title, lot.organizer, lot.region,
         _iso(lot.published_at), _iso(lot.deadline), lot.budget, lot.description, lot.url,
         json.dumps(lot.extra, ensure_ascii=False), lot.content_hash, lot.fingerprint,
         twin["id"] if twin else None, _now(), _now()))
    return "duplicate" if twin else "new"


def unscored(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT * FROM lots WHERE scored = 0 AND dup_of IS NULL").fetchall()


def save_score(con, lot_id: int, score: int, direction: str, explanation: str, method: str):
    con.execute(
        "UPDATE lots SET score=?, direction=?, explanation=?, score_method=?, scored=1 WHERE id=?",
        (score, direction, explanation, method, lot_id))


def for_digest(con, threshold: int, now_iso: str) -> list[sqlite3.Row]:
    """Оценённые, ещё не отправленные, срок подачи не истёк."""
    return con.execute(
        """SELECT * FROM lots WHERE scored=1 AND digested=0 AND dup_of IS NULL
           AND score >= ? AND (deadline IS NULL OR deadline >= ?)
           ORDER BY score DESC, deadline ASC""",
        (threshold, now_iso)).fetchall()


def mark_digested(con, ids: list[int], subject: str = "") -> None:
    """Помечает лоты отправленными и записывает дайджест в журнал."""
    cur = con.execute("INSERT INTO digests (ts, subject, count) VALUES (?,?,?)",
                      (_now(), subject, len(ids)))
    for i in ids:
        row = con.execute("SELECT fingerprint, changed FROM lots WHERE id=?", (i,)).fetchone()
        con.execute("INSERT INTO digest_items (digest_id, lot_id, fingerprint, changed) VALUES (?,?,?,?)",
                    (cur.lastrowid, i, row["fingerprint"], row["changed"]))
    con.executemany("UPDATE lots SET digested=1, changed=0 WHERE id=?", [(i,) for i in ids])


def log_run(con, stage: str, source: str, ok: bool, count: int = 0, error: str = "") -> None:
    con.execute(
        "INSERT INTO runs (ts, stage, source, ok, count, error) VALUES (?,?,?,?,?,?)",
        (_now(), stage, source, int(ok), count, error[:2000]))
    con.commit()


def export_csv(con, path: str, date_from: str, date_to: str) -> int:
    rows = con.execute(
        """SELECT source, external_id, title, organizer, region, published_at, deadline,
           budget, url, score, direction, explanation, first_seen
           FROM lots WHERE first_seen >= ? AND first_seen < ? ORDER BY first_seen""",
        (date_from, date_to)).fetchall()
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        if rows:
            w.writerow(rows[0].keys())
        w.writerows([tuple(r) for r in rows])
    return len(rows)


def _iso(dt):
    return dt.isoformat() if dt else None
