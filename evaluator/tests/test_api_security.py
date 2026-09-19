"""No credential reaches a response, and no browser picks where we connect.

Contract tests for P0.4's two verified leaks, and for the redaction layer that
closes them (P0.5's "ausencia de credenciales en toda respuesta"):

- `GET /api/runs/{run_id}` served the raw manifest, and `candidates[].env` — the
  environment the runner started the agent with — travelled with it.
- `POST /api/chat` accepted `ws_url`, `clinic_url`, `scenario` (a server path)
  and `agent_audit_dir` from the browser.

Every assertion here works on a canary value, never on a key name: the question
is not whether a field is called `api_key`, it is whether the string that was in
it can still be read.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from evaluator.api.app import create_app
from evaluator.api.redact import REDACTED, redact_secrets, redact_text
from evaluator.models import CaseResult
from evaluator.profiles import AgentProfile, ProfileCatalog

RUN = "20260919T180000Z-cafe01"
# Obvious fakes. Nothing reads a real .env in this file.
CANARY_API_KEY = "sk-live-CANARY-0123456789abcdef"
CANARY_TOKEN = "CANARY-MANIFEST-TOKEN-4f5a6b7c8d9e"


def _catalog(*extra: AgentProfile) -> ProfileCatalog:
    return ProfileCatalog([*ProfileCatalog.builtin(), *extra])


@pytest.fixture
def results_root(tmp_path) -> Path:
    run = tmp_path / RUN
    run.mkdir()
    cases = [
        CaseResult(
            case_id="baseline/sb-001/r0",
            call_id="call-1",
            scenario_id="sb-001",
            problem_id="simple_booking",
            candidate="baseline",
            repetition=0,
            verdict="invalid_evaluation",
            notes=[f"el rig no pudo abrir el socket con PROSPER_API_KEY={CANARY_API_KEY}"],
            errors=[f"provider rejected {CANARY_API_KEY}"],
        )
    ]
    (run / "cases.jsonl").write_text(
        "".join(case.model_dump_json() + "\n" for case in cases), encoding="utf-8"
    )
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": RUN,
                "experiment": "leak-check",
                "candidates": [
                    {
                        "name": "baseline",
                        "version": "lab-1",
                        "env": {
                            "PROSPER_API_KEY": CANARY_API_KEY,
                            "SOME_TOKEN": CANARY_TOKEN,
                            "PROSPER_API_BASE_URL": "http://127.0.0.1:18090",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (run / "real_calls.jsonl").write_text(
        json.dumps({"call_id": "abc", "transcript": {"caller": "hola", "assistant": "buenas"}})
        + "\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def client(results_root) -> TestClient:
    return TestClient(create_app(results_root))


class TestRedactionPrimitives:
    def test_values_of_sensitive_keys_go_and_names_stay(self):
        redacted = redact_secrets(
            {"api_key": CANARY_API_KEY, "PROSPER_API_BASE_URL": "http://127.0.0.1:18090"}
        )
        assert redacted == {
            "api_key": REDACTED,
            "PROSPER_API_BASE_URL": "http://127.0.0.1:18090",
        }

    def test_an_environment_map_loses_every_value(self):
        redacted = redact_secrets({"env": {"PROSPER_API_KEY": CANARY_API_KEY, "PORT": "17860"}})
        assert redacted == {"env": {"PROSPER_API_KEY": REDACTED, "PORT": REDACTED}}

    def test_a_credential_shape_inside_free_text_is_scrubbed(self):
        text = redact_text(f"falló con PROSPER_API_KEY={CANARY_API_KEY}")
        assert CANARY_API_KEY not in text
        assert "PROSPER_API_KEY" in text, "el nombre de la variable no es el secreto"

    def test_an_unrelated_word_containing_key_is_not_redacted(self):
        assert redact_secrets({"monkey_counter": 3}) == {"monkey_counter": 3}


class TestRunResponsesCarryNoCredential:
    def test_the_run_detail_redacts_the_candidate_environment(self, client):
        response = client.get(f"/api/runs/{RUN}")
        assert response.status_code == 200
        for canary in (CANARY_API_KEY, CANARY_TOKEN):
            assert canary not in response.text, f"{canary} viajó en /api/runs/{RUN}"
        env = response.json()["manifest"]["candidates"][0]["env"]
        assert sorted(env) == ["PROSPER_API_BASE_URL", "PROSPER_API_KEY", "SOME_TOKEN"]
        assert env["PROSPER_API_KEY"] == REDACTED

    def test_the_run_list_carries_no_credential(self, client):
        response = client.get("/api/runs")
        assert CANARY_API_KEY not in response.text
        assert CANARY_TOKEN not in response.text

    def test_the_cases_endpoint_scrubs_diagnostics(self, client):
        response = client.get(f"/api/runs/{RUN}/cases")
        assert response.status_code == 200
        assert CANARY_API_KEY not in response.text
        case = response.json()[0]
        assert "PROSPER_API_KEY" in case["notes"][0], "el diagnóstico sigue siendo legible"

    def test_the_console_listing_carries_no_credential(self, client, tmp_path):
        assert CANARY_API_KEY not in client.get(f"/api/runs/{RUN}/compare").text

    def test_a_manifest_with_no_environment_is_untouched(self, tmp_path):
        run = tmp_path / "plain"
        run.mkdir()
        (run / "cases.jsonl").write_text("", encoding="utf-8")
        (run / "manifest.json").write_text(json.dumps({"experiment": "smoke"}), encoding="utf-8")
        body = TestClient(create_app(tmp_path)).get("/api/runs/plain").json()
        assert body["manifest"]["experiment"] == "smoke"


class TestChatSurface:
    def test_a_destination_a_path_or_a_command_is_refused_and_never_echoed(self, client):
        for field in ("ws_url", "clinic_url", "scenario", "agent_audit_dir", "start_command"):
            response = client.post(
                "/api/chat", json={"profile_id": "cascade", field: CANARY_API_KEY}
            )
            assert response.status_code == 400, f"{field} debería ser rechazado"
            assert field in response.text
            assert CANARY_API_KEY not in response.text, "el rechazo repitió el valor"

    def test_an_invented_field_is_refused(self, client):
        response = client.post("/api/chat", json={"profile_id": "cascade", "mailbox": "/etc"})
        assert response.status_code == 400
        assert "campos desconocidos" in response.text

    def test_a_request_without_a_profile_id_is_refused(self, client):
        response = client.post("/api/chat", json={"tts": "espeak-ng"})
        assert response.status_code == 400
        assert "profile_id" in response.json()["detail"]

    def test_an_unknown_profile_is_named_without_echoing_a_credential(self, client):
        response = client.post("/api/chat", json={"profile_id": CANARY_API_KEY})
        assert response.status_code == 404
        assert CANARY_API_KEY not in response.text
        assert "cascade" in response.text, "el error dice qué perfiles sí existen"

    def test_a_profile_pointing_at_production_is_refused_at_request_time(self, monkeypatch):
        # Nothing may be opened for this request: the refusal comes from the
        # profile's destination, before the clinic window or the socket.
        from evaluator.api import chat

        def _forbidden(*args, **kwargs):  # pragma: no cover - only runs on a bug
            raise AssertionError("la petición abrió la llamada antes de aplicar la guarda")

        monkeypatch.setattr(chat, "open_call_window", _forbidden)
        production = AgentProfile.from_declaration(
            {
                "id": "production-guard-test",
                "engine": "cascade",
                "version": "v1",
                "endpoints": {"ws_url": "ws://127.0.0.1:7860/ws"},
                "capabilities": {"voice": True, "audio_capture": False},
                "providers": {"name": "producción"},
            }
        )
        client = TestClient(create_app(Path("/nonexistent"), profiles=_catalog(production)))
        response = client.post("/api/chat", json={"profile_id": production.id})
        assert response.status_code == 400
        assert "7860" in response.text


class TestProfilesEndpoint:
    def test_the_catalog_is_readable_and_names_the_engines(self, client):
        rows = client.get("/api/profiles").json()
        assert [row["id"] for row in rows] == ["cascade", "gemini_live"]
        assert rows[0]["engine"] == "cascade"
        assert rows[0]["refusals"] == []

    def test_the_catalog_exposes_no_command_no_path_and_no_value(self, client):
        response = client.get("/api/profiles")
        assert "agent-data" not in response.text
        for row in response.json():
            assert "start_command" not in row
            assert "launch_hint" not in row["laboratory"]
            assert row["credentials"], "los perfiles declaran qué variables necesitan"
            assert all(name.isupper() for name in row["credentials"])
            # Only booleans and non-path facts about the server side.
            assert set(row["laboratory"]) == {
                "voice_port",
                "tts",
                "has_start_command",
                "scores_scenario",
                "has_agent_audit_dir",
            }

    def test_the_catalog_never_renders_a_credential_name_as_a_value(self, client):
        # Names are configuration; a profile that declared a value never loads
        # (see test_profiles), so nothing here can even look like a secret.
        joined = " ".join(
            name for row in client.get("/api/profiles").json() for name in row["credentials"]
        )
        assert "=" not in joined
        assert all(name.isupper() and name.replace("_", "").isalnum() for name in joined.split())

    def test_a_profile_the_guard_refuses_is_listed_with_its_reason(self):
        broken = AgentProfile.from_declaration(
            {
                "id": "broken-destination",
                "engine": "external",
                "version": "v1",
                "endpoints": {"ws_url": "wss://prosper.example.com/ws"},
                "capabilities": {"voice": True},
                "providers": {"name": "oficial"},
            }
        )
        client = TestClient(create_app(Path("/nonexistent"), profiles=_catalog(broken)))
        row = next(r for r in client.get("/api/profiles").json() if r["id"] == broken.id)
        assert row["refusals"], "la lista tiene que decir por qué ese perfil no se puede usar"
        assert "oficial" in row["refusals"][0]
