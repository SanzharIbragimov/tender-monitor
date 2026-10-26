"""Демо без сети: прогон тестовых лотов через весь конвейер (оценка по правилам).

  python demo.py  →  demo_digest.html + таблица оценок в консоли
"""
import json
from datetime import datetime
import os
import tempfile
from pathlib import Path

from app import config, db, digest, scoring
from app.sources.goszakup import parse_lot

os.environ.setdefault("TM_DB", str(Path(tempfile.mkdtemp()) / "demo.db"))
cfg = config.load(Path(__file__).with_name("config.yaml"))
cfg["secrets"]["anthropic_api_key"] = ""            # демо — только правила
con = db.connect(cfg["db_path"])

data = json.loads(Path("tests/fixtures/goszakup_response.json").read_text(encoding="utf-8"))
for item in data["data"]["Lots"]:
    lot = parse_lot(item)
    if lot and (lot.deadline is None or lot.deadline >= datetime.now()):
        db.upsert(con, lot)
con.commit()
scoring.score_pending(con, cfg)

for r in con.execute("SELECT score, direction, title, explanation FROM lots ORDER BY score DESC"):
    print(f"{r['score']:>3}  {r['direction'] or '—':<12} {r['title'][:55]:<55}  {r['explanation']}")

subject, html, ids = digest.build(con, cfg)
Path("demo_digest.html").write_text(html, encoding="utf-8")
print(f"\n{subject} → demo_digest.html")
