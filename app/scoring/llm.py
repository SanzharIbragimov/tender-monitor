"""Второй шаг оценки: LLM (Anthropic Messages API). В модель уходят только публичные тексты лота."""
from __future__ import annotations

import json
import re

import httpx

API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM = """Ты оцениваешь лоты госзакупок Казахстана для ИТ-компании.
Направления компании:
{directions}

Лот релевантен, если относится хотя бы к одному направлению. Поставка оборудования
без работ по ПО, канцтовары, ремонт техники, связь и интернет как услуга — нерелевантны.
Тексты бывают на русском и казахском.

Ответь ТОЛЬКО JSON без пояснений вокруг:
{{"score": <0-100>, "direction": "<код направления или none>", "explanation": "<1-2 предложения по-русски: почему>"}}"""

USER = """Название: {title}
Организатор: {organizer}
Бюджет: {budget}
Описание: {description}"""


class LlmScorer:
    def __init__(self, cfg: dict, api_key: str):
        self.model = cfg.get("model", "claude-haiku-5-5")
        self.max_desc = int(cfg.get("max_description_chars", 3000))
        self.api_key = api_key
        dirs = cfg["_directions"]
        self.codes = set(dirs) | {"none"}
        self.system = SYSTEM.format(directions="\n".join(
            f"- {k}: {v['name']} — {v.get('description', '')}" for k, v in dirs.items()))
        self.client = httpx.Client(timeout=60)

    def score(self, title: str, organizer: str, budget, description: str) -> tuple[int, str | None, str]:
        r = self.client.post(API_URL, headers={
            "x-api-key": self.api_key, "anthropic-version": "2023-06-01",
            "content-type": "application/json"}, json={
            "model": self.model, "max_tokens": 300, "temperature": 0,
            "system": self.system,
            "messages": [{"role": "user", "content": USER.format(
                title=title, organizer=organizer or "—",
                budget=f"{budget:,.0f} ₸".replace(",", " ") if budget else "не указан",
                description=(description or "—")[: self.max_desc])}]})
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", []))
        return parse_answer(text, self.codes)


def parse_answer(text: str, codes: set[str]) -> tuple[int, str | None, str]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"LLM вернула не JSON: {text[:200]}")
    data = json.loads(m.group(0))
    score = int(max(0, min(100, int(data.get("score", 0)))))
    direction = data.get("direction")
    if direction not in codes or direction == "none":
        direction = None
    return score, direction, str(data.get("explanation", "")).strip()
