"""Оценка релевантности: правила отсекают явный мусор, LLM оценивает остальное."""
from __future__ import annotations

import json
import logging

from .. import db
from .llm import LlmScorer
from .rules import RuleScorer

log = logging.getLogger(__name__)


def score_pending(con, cfg: dict) -> dict:
    scfg = cfg["scoring"]
    rules = RuleScorer(scfg)
    llm = None
    if scfg.get("llm", {}).get("enabled") and cfg["secrets"].get("anthropic_api_key"):
        llm = LlmScorer({**scfg["llm"], "_directions": scfg["directions"]},
                        cfg["secrets"]["anthropic_api_key"])
    prefilter = int(scfg.get("prefilter_threshold", 10))
    stats = {"rules_only": 0, "llm": 0, "llm_errors": 0}

    for row in db.unscored(con):
        extra = json.loads(row["extra"] or "{}")
        rr = rules.score(row["title"], row["description"] or "", extra.get("enstru"))
        if rr.score < prefilter or llm is None:
            db.save_score(con, row["id"], rr.score, rr.direction or "",
                          rr.explain(rules.names), "rules")
            stats["rules_only"] += 1
            continue
        try:
            s, d, why = llm.score(row["title"], row["organizer"], row["budget"], row["description"])
            db.save_score(con, row["id"], s, d or rr.direction or "", why, "llm")
            stats["llm"] += 1
        except Exception as e:                       # LLM недоступна — не теряем лот
            log.warning("LLM: %s — оценка по правилам", e)
            db.save_score(con, row["id"], rr.score, rr.direction or "",
                          rr.explain(rules.names) + " (оценка по правилам: LLM недоступна)", "rules")
            stats["llm_errors"] += 1
    con.commit()
    return stats
