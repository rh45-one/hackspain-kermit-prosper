"""FrontDesk must not confuse audit data, fixtures and accepted submissions."""
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from agent.clinic.client import ProsperClient
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
    first.emit_outcome_summary(
        actions_before_flush=1, fallback_action_added=False, submissions_succeeded=0,
        submissions_failed=1, submission_configured=True,
    )
    second = CallContext(data_dir=config.data_dir, call_id="CA-active")
    second.add_transcript("caller", "Otra llamada")
    with (Path(config.calls_dir) / "CA-ended.jsonl").open("a") as stream:
        stream.write('null\n{"event":')
    with TestClient(app) as client:
        calls = client.get("/ops/api/frontdesk/calls").json()
    assert [call["callId"] for call in calls] == ["CA-active", "CA-ended"]
    assert calls[0]["status"] == "active"
    assert calls[0]["transcript"] == [{"role": "caller", "text": "Otra llamada"}]
    assert calls[1]["status"] == "ended"
    assert calls[1]["transcript"][-1] == {"role": "agent", "text": "¿Para qué día?"}
    assert calls[1]["diagnostic"]["submissions_failed"] == 1


def test_old_unclosed_logs_are_not_live_calls(config):
    CallContext(data_dir=config.data_dir, call_id="CA-abandoned")
    event = frontdesk.AuditEvent(
        ts=datetime.now(UTC) - timedelta(hours=1), event="call_context_created"
    )
    (Path(config.calls_dir) / "CA-abandoned.jsonl").write_text(event.model_dump_json())
    assert frontdesk.calls()[0].status == "unknown"


def test_clinic_enriches_appointments_and_keeps_key_on_server(config, monkeypatch):
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
        response = client.get("/ops/api/frontdesk/clinic", params={"national_id": "12345678Z"})
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
        response = client.get("/ops/api/frontdesk/clinic", params={"national_id": "12345678Z"})
    assert response.status_code == (502 if configured else 503)
    assert set(response.json()) == {"detail"}
    assert "private detail" not in response.text


def test_empty_directory_does_not_request_full_export(config, monkeypatch):
    def unexpected_client(config):
        pytest.fail("Empty searches must not call Prosper")

    monkeypatch.setattr(frontdesk, "ProsperClient", unexpected_client)
    with TestClient(app) as client:
        response = client.get("/ops/api/frontdesk/clinic")
        invalid = client.get("/ops/api/frontdesk/clinic", params={"name": "Marta"})
    assert response.status_code == 200
    assert response.json() == {"patients": [], "appointments": []}
    assert invalid.status_code == 422


def test_official_search_rejection_is_actionable(config, monkeypatch):
    transport = httpx.MockTransport(lambda request: httpx.Response(422, text="private detail"))
    monkeypatch.setattr(
        frontdesk, "ProsperClient", lambda config: ProsperClient(config, transport=transport),
    )
    with TestClient(app) as client:
        response = client.get("/ops/api/frontdesk/clinic", params={"name": "Marta Ruiz"})
    assert response.status_code == 422
    assert "documento completo" in response.json()["detail"]
    assert "private detail" not in response.text
