"""The drawing is the catalogue, and it is behind the same door as the rest."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent.ops import console
from agent.ops.console import app

OPS_TOKEN = "test-ops-token"


@pytest.fixture(autouse=True)
def _door(monkeypatch):
    monkeypatch.setattr(console, "settings", lambda: type("S", (), {"ops_token": OPS_TOKEN})())


def _map() -> dict:
    with TestClient(app) as client:
        response = client.get("/ops/api/live/graph", headers={"x-ops-token": OPS_TOKEN})
        assert response.status_code == 200
        return response.json()


def test_a_stranger_cannot_read_the_clinic_map():
    with TestClient(app) as client:
        assert client.get("/ops/api/live/graph").status_code in (401, 403)


def test_every_way_a_call_can_end_is_a_node_you_can_point_at():
    """On a screen an escalation has to exist before it can be pointed at."""
    drawn = _map()
    reasons = [n for n in drawn["nodes"] if n["kind"] == "reason"]

    assert len(reasons) == len(drawn["escalations"]) == 18
    assert all(n["meta"]["urgency"] in ("now", "today", "queue") for n in reasons)


def test_the_labels_are_readable_and_the_ids_survive_underneath():
    """A person reads the screen; the challenge's vocabulary stays in meta."""
    drawn = _map()
    emergency = next(n for n in drawn["nodes"] if n["id"] == "reason:medical_emergency")

    assert emergency["label"] == "Urgencia médica"
    assert emergency["meta"]["reason"] == "medical_emergency"
    assert emergency["meta"]["urgency"] == "now"


def test_every_node_knows_which_layer_it_is_drawn_on():
    drawn = _map()

    assert all("layer" in node and "tone" in node for node in drawn["nodes"])


def test_a_cold_catalogue_draws_what_it_knows_instead_of_failing():
    """Roles and failure modes do not need the API to be reachable."""
    drawn = _map()

    assert drawn["legend"]["urgency"]["now"]
    assert {n["kind"] for n in drawn["nodes"]} >= {"role", "reason"}
