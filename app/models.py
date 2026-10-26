"""Единая структура лота (п. 4.2 ТЗ)."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass
class Lot:
    source: str                     # код источника: goszakup, zakup_sk, nadloc, ...
    external_id: str                # id лота/объявления в источнике
    title: str
    organizer: str = ""
    region: str = ""
    published_at: datetime | None = None
    deadline: datetime | None = None
    budget: float | None = None     # тенге
    description: str = ""
    url: str = ""
    extra: dict = field(default_factory=dict)

    # --- заполняется при оценке ---
    score: int | None = None
    direction: str | None = None
    explanation: str | None = None

    @property
    def key(self) -> str:
        """Ключ лота внутри источника."""
        return f"{self.source}:{self.external_id}"

    @property
    def fingerprint(self) -> str:
        """Ключ для поиска одного и того же лота в разных источниках."""
        day = self.deadline.date().isoformat() if self.deadline else ""
        raw = f"{_norm(self.title)}|{_norm(self.organizer)}|{day}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    @property
    def content_hash(self) -> str:
        """Хэш значимых полей: меняется при переносе срока или правке условий."""
        raw = "|".join(str(x) for x in (
            self.title, self.organizer, self.deadline, self.budget, self.description))
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def as_dict(self) -> dict:
        d = asdict(self)
        for k in ("published_at", "deadline"):
            d[k] = d[k].isoformat() if d[k] else None
        return d


def _norm(s: str) -> str:
    s = (s or "").lower().replace("ё", "е")
    s = re.sub(r"[«»\"'.,;:()№\-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()
