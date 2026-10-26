from .base import Source
from .goszakup import Goszakup
from .html import HtmlSource
from .zakup_sk import ZakupSk


def build(cfg: dict) -> list[Source]:
    """Создаёт включённые в конфиге источники."""
    out = []
    for name, scfg in (cfg.get("sources") or {}).items():
        if not scfg.get("enabled", True):
            continue
        kind = scfg.get("type", "html")
        if kind == "goszakup":
            out.append(Goszakup(scfg, cfg["secrets"]))
        elif kind == "zakup_sk":
            out.append(ZakupSk(scfg, cfg["secrets"]))
        elif kind == "html":
            out.append(HtmlSource(name, scfg, cfg["secrets"]))
        else:
            raise ValueError(f"неизвестный тип источника {kind} для {name}")
    return out
