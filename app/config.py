"""Загрузка config.yaml и секретов из переменных окружения (п. 6 ТЗ)."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

DEFAULT_PATH = Path(os.getenv("TM_CONFIG", "config.yaml"))


def load(path: Path | str = DEFAULT_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["secrets"] = {
        "goszakup_token": os.getenv("GOSZAKUP_TOKEN", ""),
        "smtp_host": os.getenv("SMTP_HOST", ""),
        "smtp_port": int(os.getenv("SMTP_PORT", "587")),
        "smtp_user": os.getenv("SMTP_USER", ""),
        "smtp_password": os.getenv("SMTP_PASSWORD", ""),
        "smtp_from": os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "")),
        "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", ""),
    }
    cfg["db_path"] = os.getenv("TM_DB", cfg.get("db_path", "data/tenders.db"))
    return cfg
