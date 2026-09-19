"""La cola de lo que va mal, y quién se entera.

Una llamada que escala escribía una línea de auditoría en un `.jsonl` dentro
del volumen: sirve para reconstruir la llamada mañana y no para que alguien se
entere hoy. Esto comprueba que además queda una fila donde una persona la ve,
asignada a quien dicen las rutas de la clínica y no a otro.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent.accounts.store import Person, Route, Store
from agent.ops import console
from agent.ops.console import app
from agent.orgs import DEFAULT_ORG_ID

OPS_TOKEN = "test-ops-token"


@pytest.fixture(autouse=True)
def _door(monkeypatch, accounts_db):
    monkeypatch.setattr(console, "settings", lambda: type("S", (), {"ops_token": OPS_TOKEN})())
    shop = Store(accounts_db)
    shop.upsert_person(
        DEFAULT_ORG_ID, Person(slug="german", name="Germán Padua", role="Ginecólogo Jr.")
    )
    shop.upsert_route(
        DEFAULT_ORG_ID, Route(reason="provider_on_leave", person_slug="german", urgency="today")
    )


def _client() -> TestClient:
    return TestClient(app)


def test_a_stranger_cannot_read_what_is_going_wrong():
    with _client() as client:
        assert client.get("/ops/api/live/incidents").status_code in (401, 403)


def test_an_incident_lands_on_whoever_the_routes_say(accounts_db):
    """Sin destinatario, lo decide la misma tabla que decide a quién llama."""
    with _client() as client:
        made = client.post(
            "/ops/api/live/incidents",
            json={"reason": "provider_on_leave", "summary": "Hugo de vacaciones"},
            headers={"x-ops-token": OPS_TOKEN},
        )
        assert made.status_code == 200
        body = made.json()
        assert body["assigned_to"] == "german"
        # Y con su nombre puesto: una pantalla que dice `german` obliga a
        # quien la lee a traducirlo de cabeza.
        assert body["assigned_name"] == "Germán Padua"
        assert body["assigned_role"] == "Ginecólogo Jr."
        assert body["reason_label"] == "Médico de baja"
        assert body["status"] == "open"


def test_closing_one_takes_it_out_of_the_queue(accounts_db):
    with _client() as client:
        headers = {"x-ops-token": OPS_TOKEN}
        made = client.post(
            "/ops/api/live/incidents",
            json={"reason": "provider_on_leave"},
            headers=headers,
        ).json()
        listed = client.get("/ops/api/live/incidents", headers=headers).json()
        assert listed["open"] == 1
        assert listed["by_urgency"] == {"today": 1}

        closed = client.post(
            f"/ops/api/live/incidents/{made['id']}/status",
            json={"status": "closed", "note": "lo coge Andrés"},
            headers=headers,
        )
        assert closed.status_code == 200
        assert closed.json()["status"] == "closed"
        assert closed.json()["note"] == "lo coge Andrés"
        assert closed.json()["closed_at"]

        assert client.get("/ops/api/live/incidents", headers=headers).json()["open"] == 0


def test_an_unknown_incident_is_a_404(accounts_db):
    with _client() as client:
        answer = client.post(
            "/ops/api/live/incidents/inc-nope/status",
            json={"status": "closed"},
            headers={"x-ops-token": OPS_TOKEN},
        )
        assert answer.status_code == 404


def test_a_made_up_status_is_refused(accounts_db):
    with _client() as client:
        made = client.post(
            "/ops/api/live/incidents",
            json={"reason": "provider_on_leave"},
            headers={"x-ops-token": OPS_TOKEN},
        ).json()
        answer = client.post(
            f"/ops/api/live/incidents/{made['id']}/status",
            json={"status": "resuelto-mas-o-menos"},
            headers={"x-ops-token": OPS_TOKEN},
        )
        assert answer.status_code == 422


# ---- el simulador ---------------------------------------------------------
def test_the_simulator_lets_jev_decide_and_says_so(accounts_db, monkeypatch):
    """Lo que hay que enseñar es quién ha decidido, no sólo a quién le toca."""
    from agent.decision.client import CoverChoice
    from agent.ops import incidents as ops_incidents

    async def _jev(_org, _situation):
        return "german", 0.93, "chosen"

    monkeypatch.setattr(ops_incidents, "_jev_assigns", _jev)
    with _client() as client:
        made = client.post(
            "/ops/api/live/incidents/simulate", headers={"x-ops-token": OPS_TOKEN}
        )
        assert made.status_code == 200
        body = made.json()
        assert body["decided_by"] == "jev"
        assert body["assigned_to"] == "german"
        assert body["confidence"] == 0.93
        assert body["source"] == "simulador"
        # Y la frase llega en castellano, no como identificador: es lo que
        # Jev tiene que leer para decidir.
        assert " " in body["summary"]
    assert CoverChoice  # el tipo que devuelve el cliente de verdad


def test_when_jev_abstains_the_configured_route_answers(accounts_db, monkeypatch):
    from agent.ops import incidents as ops_incidents

    async def _jev(_org, _situation):
        return "", 0.31, "not_confident"

    monkeypatch.setattr(ops_incidents, "_jev_assigns", _jev)
    with _client() as client:
        body = client.post(
            "/ops/api/live/incidents/simulate", headers={"x-ops-token": OPS_TOKEN}
        ).json()
        assert body["decided_by"] == "route"
        # La clínica siempre tiene a alguien: o el de la ruta del motivo, o
        # el declarado a mano que nadie ha reemplazado.
        assert body["assigned_to"]


def test_a_stranger_cannot_launch_incidents():
    with _client() as client:
        assert client.post("/ops/api/live/incidents/simulate").status_code in (401, 403)
