import json
from pathlib import Path

import httpx
import pytest

from app import config

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).with_name("fixtures")


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("GOSZAKUP_TOKEN", "test-token")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    c = config.load(ROOT / "config.yaml")
    c["db_path"] = str(tmp_path / "t.db")
    return c


@pytest.fixture
def goszakup_json():
    return json.loads((FIX / "goszakup_response.json").read_text(encoding="utf-8"))


def mock_client(payload: dict) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(200, json=payload)
    return httpx.Client(transport=httpx.MockTransport(handler))
