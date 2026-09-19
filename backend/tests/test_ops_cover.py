"""The cover suggestion: a hint on a refresh, and never the only answer.

Jev is stubbed throughout. What is being tested is not whether the sidecar
chooses well — that is measured against the live service — but that the panel
gets an answer whatever the sidecar does, including when it is not there.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent.accounts.store import Person, Route, Store
from agent.ops import console
from agent.ops import cover as ops_cover
from agent.ops.console import app

OPS_TOKEN = "test-ops-token"
ORG = "clinica-arenal"


@pytest.fixture(autouse=True)
def _door(monkeypatch, accounts_db):
    monkeypatch.setattr(console, "settings", lambda: type("S", (), {"ops_token": OPS_TOKEN})())
    shop = Store(accounts_db)
    shop.upsert_person(ORG, Person(slug="ana", name="Ana Ruiz", role="Ginecóloga"))
    shop.upsert_person(
        ORG,
        Person(slug="bea", name="Bea Lis", role="Ginecóloga Jr.", covers_for="ana"),
    )
    shop.upsert_route(ORG, Route(reason="provider_on_leave", person_slug="ana", urgency="today"))


def _ask(monkeypatch, answer):
    async def _stub(situation, people, **kwargs):
        return answer(situation, people) if callable(answer) else answer

    monkeypatch.setattr(ops_cover, "_ask_jev", _stub)


def _get(**params) -> dict:
    with TestClient(app) as client:
        response = client.get(
            "/ops/api/live/cover",
            params={"org_id": ORG, **params},
            headers={"x-ops-token": OPS_TOKEN},
        )
        assert response.status_code == 200
        return response.json()


def test_a_stranger_cannot_ask_who_covers_a_shift():
    with TestClient(app) as client:
        assert client.get("/ops/api/live/cover").status_code in (401, 403)


def test_jev_can_reach_the_second_line_of_the_rota(monkeypatch):
    _ask(monkeypatch, "bea")
    answer = _get(situation="Ana está de baja el lunes", reason="provider_on_leave")
    assert answer["suggested"]["slug"] == "bea"
    assert answer["suggested"]["source"] == "jev"
    # The route is still returned, so the panel can show what happens anyway.
    assert answer["fallback"]["slug"] == "ana"


def test_an_abstention_leaves_the_configured_route_answering(monkeypatch):
    _ask(monkeypatch, None)
    answer = _get(situation="No sé qué pasa", reason="provider_on_leave")
    assert answer["suggested"]["slug"] == "ana"
    assert answer["suggested"]["source"] == "route"


def test_the_sidecar_being_down_is_not_a_failed_page(monkeypatch):
    def _explode(*_args, **_kwargs):
        raise RuntimeError("typesafe is down")

    monkeypatch.setattr("agent.brain.tools._build_jev_client", _explode)
    answer = _get(situation="Ana está de baja", reason="provider_on_leave")
    assert answer["suggested"]["slug"] == "ana"
    assert answer["suggested"]["source"] == "route"


def test_nothing_is_asked_of_jev_without_a_situation(monkeypatch):
    _ask(monkeypatch, lambda *_: pytest.fail("Jev was asked with no situation"))
    answer = _get(reason="provider_on_leave")
    assert answer["asked"] is False
    assert answer["suggested"]["slug"] == "ana"


def test_a_phone_number_is_never_offered_to_the_sidecar(monkeypatch):
    seen: dict = {}

    def _capture(_situation, people):
        seen.update(people)

    _ask(monkeypatch, _capture)
    _get(situation="Ana está de baja", reason="provider_on_leave")
    assert seen, "Jev was never asked"
    assert not any("+34" in line for line in seen.values())


def test_the_chain_is_described_by_name_not_by_slug():
    line = ops_cover._describe(
        Person(slug="bea", name="Bea Lis", role="Ginecóloga Jr.", covers_for="ana"),
        {"ana": "Ana Ruiz", "bea": "Bea Lis"},
    )
    assert "Ana Ruiz" in line
    assert "ana" not in line.replace("Ana Ruiz", "")
