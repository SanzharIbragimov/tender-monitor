"""Первый шаг оценки: правила по ключевым словам, стоп-словам и кодам ЕНС ТРУ.

Ключевые слова задаются основами слов («разработк», «бағдарламалық»),
фраза из нескольких основ ловит любые окончания: «программн обеспечен» →
«программного обеспечения», «программное обеспечение».
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class RuleResult:
    score: int                          # 0–100
    direction: str | None               # лучшее направление или None
    hits: dict[str, list[str]] = field(default_factory=dict)
    stops: list[str] = field(default_factory=list)
    enstru: bool = False

    def explain(self, names: dict[str, str]) -> str:
        if self.stops and not self.hits:
            return "Нерелевантно: стоп-слова — " + ", ".join(self.stops[:5]) + "."
        if not self.hits and not self.enstru:
            return "Нет совпадений с ключевыми словами направлений."
        parts = []
        if self.direction and self.hits.get(self.direction):
            parts.append(f"{names.get(self.direction, self.direction)}: "
                         + ", ".join(self.hits[self.direction][:5]))
        if self.enstru:
            parts.append("код ЕНС ТРУ из ИТ-группы")
        if self.stops:
            parts.append("снижено стоп-словами: " + ", ".join(self.stops[:3]))
        return "Совпадения — " + "; ".join(parts) + "."


class RuleScorer:
    def __init__(self, cfg: dict):
        self.directions = cfg["directions"]
        self.names = {k: v["name"] for k, v in self.directions.items()}
        self.kw = {k: [(w, _pattern(w), float(wt)) for w, wt in _items(v.get("keywords"))]
                   for k, v in self.directions.items()}
        self.stops = [(w, _pattern(w), float(wt)) for w, wt in _items(cfg.get("stop_words"), 40)]
        self.enstru_prefixes = tuple(str(p) for p in cfg.get("enstru_prefixes", []))
        self.enstru_bonus = float(cfg.get("enstru_bonus", 30))

    def score(self, title: str, description: str = "", enstru: list | None = None) -> RuleResult:
        text = _norm(f"{title} {description}")
        title_n = _norm(title)
        per_dir, hits = {}, {}
        for d, words in self.kw.items():
            s = 0.0
            for word, pat, wt in words:
                if pat.search(text):
                    s += wt * (1.5 if pat.search(title_n) else 1.0)   # в названии — весомее
                    hits.setdefault(d, []).append(word)
            per_dir[d] = s
        stops, penalty = [], 0.0
        for word, pat, wt in self.stops:
            if pat.search(text):
                stops.append(word)
                penalty += wt
        codes = [str(c) for c in (enstru or [])]
        enstru_hit = bool(self.enstru_prefixes) and any(c.startswith(self.enstru_prefixes) for c in codes)
        best = max(per_dir, key=per_dir.get) if per_dir else None
        raw = (per_dir.get(best, 0) if best else 0) + (self.enstru_bonus if enstru_hit else 0) - penalty
        score = int(max(0, min(100, raw)))
        return RuleResult(score=score, direction=best if score > 0 and per_dir.get(best) else None,
                          hits=hits, stops=stops, enstru=enstru_hit)


def _items(x, default_weight=20):
    """Список ключевых слов: строки (вес по умолчанию) или {слово: вес}."""
    if isinstance(x, dict):
        return list(x.items())
    return [(w, default_weight) for w in (x or [])]


def _pattern(phrase: str) -> re.Pattern:
    stems = [re.escape(s) for s in _norm(phrase).split()]
    return re.compile(r"(?<!\w)" + r"\w*\s+".join(stems) + r"\w*")


def _norm(s: str) -> str:
    s = (s or "").lower().replace("ё", "е")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s)
