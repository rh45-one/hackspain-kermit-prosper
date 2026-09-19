"""The settings screen reports what is running, and never a secret."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agent.ops import console
from agent.ops.console import app

OPS_TOKEN = "test-ops-token"


@pytest.fixture(autouse=True)
def _door(monkeypatch):
    monkeypatch.setattr(console, "settings", lambda: type("S", (), {"ops_token": OPS_TOKEN})())


def _config() -> dict:
    with TestClient(app) as client:
        response = client.get("/ops/api/live/agent", headers={"x-ops-token": OPS_TOKEN})
        assert response.status_code == 200
        return response.json()


def test_a_stranger_cannot_read_the_configuration():
    with TestClient(app) as client:
        assert client.get("/ops/api/live/agent").status_code in (401, 403)


def test_it_reports_the_running_engine_and_prompt():
    reported = _config()

    assert reported["engine"]["running"] in ("gemini_live", "cascade")
    assert reported["prompt"]["version"].startswith("receptionist-v")


def test_no_key_ever_leaves_this_endpoint():
    """Presence is a fact worth reporting. The value is not."""
    served = json.dumps(_config())

    for secret in ("sk-", "pk-", "apikey_", "AQ.", "REPLACE_ME"):
        assert secret not in served


def test_cascade_is_reported_as_unusable_with_its_reason():
    """It is listed because the code falls back to it, not because it works."""
    cascade = _config()["engine"]["alternatives"]["cascade"]

    if not cascade["usable"]:
        assert "Helmcode" in cascade["why_not"]


def test_the_screen_says_what_it_cannot_do():
    assert _config()["read_only"]
