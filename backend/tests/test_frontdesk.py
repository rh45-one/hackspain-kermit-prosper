"""FrontDesk must not confuse audit data, fixtures and accepted submissions."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

# These routes sit behind the same door as the rest of /ops, so every request
# here carries the token a real caller would. A test that reached them without
# one would be testing a hole, not the feature.
OPS_TOKEN = "test-ops-token"


@pytest.fixture(autouse=True)
def _ops_door(monkeypatch):
    from agent.ops import console

    monkeypatch.setattr(console, "settings", lambda: type("S", (), {"ops_token": OPS_TOKEN})())

from agent.clinic.client import ProsperClient
from agent.clinic.models import PatientMatch
from agent.config import Settings
from agent.ops import frontdesk
from agent.ops.console import app
from agent.voice.context import CallContext
from tests.conftest import load_fixture


@pytest.fixture
def config(tmp_path, monkeypatch):
    value = Settings(_env_file=None, data_dir=str(tmp_path), prosper_api_key="local-test")
    monkeypatch.setattr(frontdesk, "settings", lambda: value)
    return value


def test_call_audit_is_isolated_and_partial_lines_are_ignored(config):
    first = CallContext(data_dir=config.data_dir, call_id="CA-ended")
    first.add_transcript("caller", "Necesito una cita")
    first.add_transcript("assistant", "¿Para qué día?")
    first.mark_stopped()
    # PR #2 also adds CallContext.emit_outcome_summary, which this test used to
    # call. That method needs the pipeline-stage tracking the same PR threads
    # through pipeline, tap, twilio and flush, and none of that is needed to
    # serve this panel — so it is not in this change, and neither is the call.
    # What the test is actually about survives: one call's audit never bleeds
    # into another's, and a half-written line is skipped rather than fatal.
    second = CallContext(data_dir=config.data_dir, call_id="CA-active")
    second.add_transcript("caller", "Otra llamada")
    with (Path(config.calls_dir) / "CA-ended.jsonl").open("a") as stream:
        stream.write('null\n{"event":')
    with TestClient(app) as client:
        calls = client.get("/ops/api/frontdesk/calls", headers={"x-ops-token": OPS_TOKEN}).json()
    assert [call["callId"] for call in calls] == ["CA-active", "CA-ended"]
    assert calls[0]["status"] == "active"
    assert calls[0]["transcript"] == [{"role": "caller", "text": "Otra llamada"}]
    assert calls[1]["status"] == "ended"
    assert calls[1]["transcript"][-1] == {"role": "agent", "text": "¿Para qué día?"}
    # `diagnostic` stays empty until the outcome summary lands with the rest of
    # PR #2. The panel treats it as optional, which is why this is a missing
    # field and not a broken page.
    assert calls[1]["diagnostic"] is None


def test_calls_recorded_before_organisations_are_still_served(config):
    """The panel must not lose the calls this clinic made before the change."""
    legacy = Path(config.legacy_calls_dir)
    legacy.mkdir(parents=True, exist_ok=True)
    event = frontdesk.AuditEvent(ts=datetime.now(UTC), event="call_context_created")
    (legacy / "CA-old.jsonl").write_text(event.model_dump_json())
    CallContext(data_dir=config.data_dir, call_id="CA-new")
    assert {call.callId for call in frontdesk.calls()} == {"CA-old", "CA-new"}


def test_old_unclosed_logs_are_not_live_calls(config):
    CallContext(data_dir=config.data_dir, call_id="CA-abandoned")
    event = frontdesk.AuditEvent(
        ts=datetime.now(UTC) - timedelta(hours=1), event="call_context_created"
    )
    (Path(config.calls_dir) / "CA-abandoned.jsonl").write_text(event.model_dump_json())
    assert frontdesk.calls()[0].status == "unknown"


def _warm(monkeypatch, **indexes):
    """Give the route a warm catalogue, the way agent.serve's lifespan does.

    The ids-to-names no longer come off a per-request fetch, so a test that
    wants names has to supply the cache rather than a fake HTTP response.
    """
    cache = type("C", (), {f"{kind}_by_id": value for kind, value in indexes.items()})()

    async def _warmed() -> object:
        return cache

    monkeypatch.setattr(frontdesk, "_warm_catalogue", _warmed)


def _named(name: str) -> object:
    return type("N", (), {"name": name})()


def test_clinic_enriches_appointments_and_keeps_key_on_server(config, monkeypatch):
    _warm(
        monkeypatch,
        providers={"PR01": _named("Dra. Ana Sáez")},
        locations={"centro": _named("Arenal Centro")},
        types={"review": _named("Review")},
    )
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Api-Key"] == config.prosper_api_key
        route = request.url.path
        if route.endswith("/clinic"):
            body = load_fixture("clinic")
        elif route.endswith("/directory"):
            assert request.url.params["national_id"] == "12345678Z"
            body = load_fixture("directory")
        else:
            assert request.url.params["when"] == "all"
            body = load_fixture("appointments") if "P00042" in route else {"appointments": []}
        return httpx.Response(200, json=body)

    monkeypatch.setattr(
        frontdesk, "ProsperClient",
        lambda config: ProsperClient(config, transport=httpx.MockTransport(handle)),
    )
    with TestClient(app) as client:
        response = client.get("/ops/api/frontdesk/clinic", headers={"x-ops-token": OPS_TOKEN}, params={"national_id": "12345678Z"})
    assert response.status_code == 200
    assert len(response.json()["patients"]) == 2
    assert len(response.json()["appointments"]) == 2
    assert response.json()["appointments"][0]["provider_name"] == "Dra. Ana Sáez"
    assert config.prosper_api_key not in response.text


@pytest.mark.parametrize("configured", [False, True])
def test_clinic_failures_are_explicit_and_do_not_return_mocks(config, monkeypatch, configured):
    config.prosper_api_key = "local-test" if configured else ""
    transport = httpx.MockTransport(lambda request: httpx.Response(403, text="private detail"))
    monkeypatch.setattr(
        frontdesk, "ProsperClient", lambda config: ProsperClient(config, transport=transport),
    )
    with TestClient(app) as client:
        response = client.get("/ops/api/frontdesk/clinic", headers={"x-ops-token": OPS_TOKEN}, params={"national_id": "12345678Z"})
    assert response.status_code == (502 if configured else 503)
    assert set(response.json()) == {"detail"}
    assert "private detail" not in response.text


def test_empty_directory_does_not_request_full_export(config, monkeypatch):
    def unexpected_client(config):
        pytest.fail("Empty searches must not call Prosper")

    monkeypatch.setattr(frontdesk, "ProsperClient", unexpected_client)
    with TestClient(app) as client:
        response = client.get("/ops/api/frontdesk/clinic", headers={"x-ops-token": OPS_TOKEN})
        invalid = client.get("/ops/api/frontdesk/clinic", headers={"x-ops-token": OPS_TOKEN}, params={"name": "Marta"})
    assert response.status_code == 200
    assert response.json() == {"patients": [], "appointments": []}
    assert invalid.status_code == 422


def test_official_search_rejection_is_actionable(config, monkeypatch):
    transport = httpx.MockTransport(lambda request: httpx.Response(422, text="private detail"))
    monkeypatch.setattr(
        frontdesk, "ProsperClient", lambda config: ProsperClient(config, transport=transport),
    )
    with TestClient(app) as client:
        response = client.get("/ops/api/frontdesk/clinic", headers={"x-ops-token": OPS_TOKEN}, params={"name": "Marta Ruiz"})
    assert response.status_code == 422
    assert "documento completo" in response.json()["detail"]
    assert "private detail" not in response.text

def test_a_patient_card_carries_no_national_id_or_phone(config, monkeypatch):
    """This panel is published; those two fields are what must never leave.

    `live.py` redacts exactly these from transcripts on purpose, and two views
    of the same patient cannot disagree about it. The name and date of birth
    stay: they are how a person at a desk knows who they are looking at, and
    the challenge protects the id and the telephone, never the name.
    """
    card = frontdesk.PatientCard.of(
        PatientMatch(
            patient_id="P00042",
            given_name="Marta",
            first_surname="Ruiz",
            second_surname="Gómez",
            national_id="12345678Z",
            date_of_birth="1988-03-14",
            phone="612345678",
            sex="F",
            has_visited_before=True,
            insurer="sanitas",
        )
    )

    served = card.model_dump()
    assert "national_id" not in served
    assert "phone" not in served
    assert "12345678Z" not in json.dumps(served)
    assert "612345678" not in json.dumps(served)
    assert served["given_name"] == "Marta"
    assert served["date_of_birth"] == "1988-03-14"
