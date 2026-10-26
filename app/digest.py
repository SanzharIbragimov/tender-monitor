"""Ежедневный дайджест и уведомления о сбоях (п. 4.5, 6 ТЗ)."""
from __future__ import annotations

import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import db

TEMPLATES = Path(__file__).with_name("templates")
env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))


def build(con, cfg: dict) -> tuple[str, str, list[int]]:
    """Возвращает (тема, html, id отправленных лотов)."""
    dcfg = cfg["digest"]
    tz = ZoneInfo(cfg.get("timezone", "Asia/Almaty"))
    now = datetime.now(tz).replace(tzinfo=None)
    rows = db.for_digest(con, int(dcfg.get("threshold", 60)), now.isoformat())
    rows = rows[: int(dcfg.get("max_lots", 20))]
    urgent_until = now + timedelta(days=int(dcfg.get("urgent_days", 3)))

    names = {k: v["name"] for k, v in cfg["scoring"]["directions"].items()}
    lots = [_view(r, names) for r in rows]
    urgent = [l for l in lots if l["deadline_dt"] and l["deadline_dt"] <= urgent_until]
    rest = [l for l in lots if l not in urgent]

    date_s = now.strftime("%d.%m.%Y")
    subject = (f"Тендеры ИТ {date_s}: {len(lots)} подходящих" if lots
               else f"Тендеры ИТ {date_s}: подходящих лотов нет")
    html = env.get_template("digest.html").render(
        date=date_s, urgent=urgent, rest=rest, total=len(lots),
        urgent_days=dcfg.get("urgent_days", 3))
    return subject, html, [r["id"] for r in rows]


def _view(r, names) -> dict:
    dl = datetime.fromisoformat(r["deadline"]) if r["deadline"] else None
    return {
        "title": r["title"], "organizer": r["organizer"] or "—", "url": r["url"],
        "deadline": dl.strftime("%d.%m.%Y %H:%M") if dl else "не указан", "deadline_dt": dl,
        "budget": f"{r['budget']:,.0f} ₸".replace(",", " ") if r["budget"] else "не указан",
        "score": r["score"], "direction": names.get(r["direction"], "—"),
        "explanation": r["explanation"], "changed": bool(r["changed"]), "source": r["source"],
    }


def send(cfg: dict, to: list[str], subject: str, html: str) -> None:
    s = cfg["secrets"]
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, s["smtp_from"], ", ".join(to)
    msg.set_content("Откройте письмо в HTML-режиме.")
    msg.add_alternative(html, subtype="html")
    ctx = ssl.create_default_context()
    if s["smtp_port"] == 465:
        with smtplib.SMTP_SSL(s["smtp_host"], 465, context=ctx, timeout=30) as smtp:
            smtp.login(s["smtp_user"], s["smtp_password"])
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(s["smtp_host"], s["smtp_port"], timeout=30) as smtp:
            smtp.starttls(context=ctx)
            smtp.login(s["smtp_user"], s["smtp_password"])
            smtp.send_message(msg)


def alert(cfg: dict, text: str) -> None:
    """Письмо ответственному при сбое источника или рассылки."""
    to = cfg["digest"].get("alert_to") or []
    if to and cfg["secrets"].get("smtp_host"):
        send(cfg, to, "Мониторинг тендеров: сбой", f"<pre>{text}</pre>")
