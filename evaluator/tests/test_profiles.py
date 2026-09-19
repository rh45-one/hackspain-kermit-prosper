"""Profiles are declarations: an incomplete one does not load, production is refused.

Contract tests for P0.1 (declarative profile schema) and P0.2 (initial catalog
and laboratory guard), plus the request allowlist that keeps a browser from
naming a destination, a path or a command (P0.4's second leak).

Three properties are asserted here and nowhere else:

- **Every gap is named.** A declaration with several problems raises once, and
  the message contains each offending field name: an operator fixes the YAML in
  one pass instead of one error per attempt.
- **The catalog matches the frozen backend contract.** The shipped profiles and
  the example YAML agree, both point at the laboratory port, and neither ever
  touches 7860.
- **The guard answers about 7860 without touching it.** Port 7860 is the
  production instance with the ngrok tunnel: the refusal comes from a constant,
  proven by making every socket construction fail for the duration of the call.
"""
from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from evaluator.profiles import (
    PRODUCTION_VOICE_PORT,
    AgentProfile,
    LaboratoryRefusal,
    ProfileCatalog,
    ProfileNotFound,
    ProfileValidationError,
    assert_laboratory_profile,
    cascade_profile,
    destination_problems,
    laboratory_problems,
    port_is_free,
    port_problems,
    request_refusals,
)
from evaluator.tester import ChatOptions

PROFILES_YAML = Path(__file__).resolve().parent.parent / "experiments" / "profiles.yaml"

# An obviously fake credential. Nothing here is a real key and nothing here reads
# an environment file: the point is that the value never comes back out.
CANARY = "sk-live-CANARY-0123456789abcdef"


def _valid(**overrides) -> dict:
    """A minimal complete declaration, with overrides applied on top."""
    declaration = {
        "id": "candidate",
        "engine": "cascade",
        "version": "v1",
        "endpoints": {"ws_url": "ws://127.0.0.1:17860/ws", "text_url": "http://127.0.0.1:17860"},
        "capabilities": {
            "text": True,
            "voice": True,
            "audio_capture": True,
            "audio_source": "client_capture",
            "transcript": True,
            "expected_outcome": True,
        },
        "providers": {"name": "deepgram + helmcode + elevenlabs"},
        "credentials": {"agent_api_key": "PROSPER_API_KEY"},
        "launch_env": {"VOICE_ENGINE": "cascade"},
        "laboratory": {"voice_port": 17860},
    }
    for key, value in overrides.items():
        declaration[key] = value
    return declaration


def _profile(**overrides) -> AgentProfile:
    return AgentProfile.from_declaration(_valid(**overrides))


def _destination_profile(ws_url: str) -> AgentProfile:
    """A complete profile whose voice socket points at `ws_url`.

    Text is declared absent so the declaration stays consistent: this helper is
    about the guard, and a profile that contradicts itself never gets that far.
    """
    return _profile(
        endpoints={"ws_url": ws_url},
        capabilities={
            "voice": True,
            "text": False,
            "audio_capture": True,
            "audio_source": "client_capture",
            "transcript": True,
        },
    )


def _url_port(url: str) -> int | None:
    from urllib.parse import urlsplit

    return urlsplit(url).port


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


# ---- P0.1: the declaration -------------------------------------------------


class TestProfileSchema:
    def test_a_complete_declaration_loads_and_reports_no_problems(self):
        profile = _profile()
        assert profile.problems() == []
        assert profile.is_complete is True
        assert profile.engine == "cascade"

    def test_a_voice_capability_without_ws_url_names_the_field(self):
        declaration = _valid(
            endpoints={"text_url": "http://127.0.0.1:17860"},
            capabilities={
                "text": True,
                "voice": True,
                "audio_capture": True,
                "audio_source": "client_capture",
                "transcript": True,
            },
        )
        with pytest.raises(ProfileValidationError) as error:
            AgentProfile.from_declaration(declaration)
        assert "endpoints.ws_url" in str(error.value)
        assert "capabilities.voice" in str(error.value)

    def test_a_declared_audio_capability_without_a_source_is_refused(self):
        with pytest.raises(ProfileValidationError) as error:
            _profile(capabilities={"voice": True, "audio_capture": True, "audio_source": "none"})
        assert "capabilities.audio_capture" in str(error.value)
        assert "audio_source" in str(error.value)

    def test_audio_capture_without_a_way_to_capture_is_refused(self):
        # audio_source is a source in name only: the capability still needs one.
        declaration = _valid()
        declaration["capabilities"]["audio_capture"] = True
        declaration["capabilities"]["audio_source"] = "magic"
        with pytest.raises(ProfileValidationError) as error:
            AgentProfile.from_declaration(declaration)
        assert "capabilities.audio_source" in str(error.value)

    def test_an_unknown_engine_is_refused_by_name(self):
        with pytest.raises(ProfileValidationError) as error:
            _profile(engine="gpt5-voice")
        message = str(error.value)
        assert "engine" in message
        assert "gpt5-voice" in message

    def test_every_missing_field_is_named_in_one_message(self):
        with pytest.raises(ProfileValidationError) as error:
            AgentProfile.from_declaration({"id": "broken", "capabilities": {"voice": True}})
        message = str(error.value)
        for field in (
            "engine",
            "version",
            "providers.name",
            "endpoints.ws_url",
        ):
            assert field in message, f"{field} no aparece en: {message}"

    def test_contradictions_between_endpoints_and_capabilities_are_refused(self):
        with pytest.raises(ProfileValidationError) as error:
            _profile(capabilities={"voice": False, "text": False})
        message = str(error.value)
        assert "capabilities.voice" in message
        assert "capabilities.text" in message

    def test_cost_telemetry_without_a_usage_url_is_refused(self):
        with pytest.raises(ProfileValidationError) as error:
            _profile(capabilities={"voice": True, "usage_telemetry": True})
        assert "endpoints.usage_url" in str(error.value)

    def test_credentials_are_references_by_name_only(self):
        profile = _profile(credentials={"agent_api_key": "PROSPER_API_KEY"})
        assert profile.credentials == {"agent_api_key": "PROSPER_API_KEY"}
        with pytest.raises(ProfileValidationError) as error:
            _profile(credentials={"agent_api_key": CANARY})
        message = str(error.value)
        assert "credentials.agent_api_key" in message
        assert "NOMBRE" in message
        assert CANARY not in message, "el error de validación repitió el valor"

    def test_a_secret_in_the_environment_block_is_refused_without_echoing_it(self):
        with pytest.raises(ProfileValidationError) as error:
            _profile(launch_env={"PROSPER_API_KEY": CANARY})
        message = str(error.value)
        assert "launch_env.PROSPER_API_KEY" in message
        assert CANARY not in message, "el error de validación repitió el valor"

    def test_start_command_is_server_owned_and_never_rendered(self):
        profile = _profile(start_command="uv run --project backend python -m agent.serve")
        assert profile.start_command is not None
        view = profile.public_view()
        assert "start_command" not in view
        assert "uv run" not in json.dumps(view)
        assert view["laboratory"]["has_start_command"] is True
        assert view["credentials"] == ["PROSPER_API_KEY"]

    def test_a_session_cannot_override_a_destination(self):
        profile = _profile()
        ChatOptions.from_profile(profile, reply_idle_ms=250)
        for forbidden in ("ws_url", "clinic_url", "api_key", "scenario", "agent_audit_dir"):
            with pytest.raises(ValueError):
                ChatOptions.from_profile(profile, **{forbidden: "ws://evil.example.com/ws"})

    def test_a_session_takes_its_destination_from_the_profile(self):
        profile = _profile(
            endpoints={
                "ws_url": "ws://127.0.0.1:17999/ws",
                "text_url": "http://127.0.0.1:17999",
            },
            laboratory={"clinic_url": "http://127.0.0.1:18990", "submit_key": "pk-test"},
        )
        options = ChatOptions.from_profile(profile)
        assert options.ws_url == "ws://127.0.0.1:17999/ws"
        assert options.clinic_url == "http://127.0.0.1:18990"
        assert options.api_key == "pk-test"
        assert options.profile_id == "candidate"


# ---- P0.2: the catalog and the guard --------------------------------------


class TestShippedCatalog:
    def test_the_catalog_declares_both_real_engines(self):
        catalog = ProfileCatalog.builtin()
        assert catalog.ids() == ["cascade", "gemini_live"]
        assert catalog.get("cascade").engine == "cascade"
        assert catalog.get("gemini_live").engine == "gemini_live"

    def test_both_profiles_use_the_lab_port_and_never_7860(self):
        catalog = ProfileCatalog.builtin()
        for profile in catalog:
            assert _url_port(profile.endpoints.ws_url or "") == 17860
            assert _url_port(profile.endpoints.ws_url or "") != PRODUCTION_VOICE_PORT
            assert profile.laboratory.voice_port != PRODUCTION_VOICE_PORT
            assert destination_problems(profile) == []
            assert profile.capabilities.text and profile.capabilities.voice

    def test_neither_profile_claims_cost_it_cannot_measure(self):
        for profile in ProfileCatalog.builtin():
            assert profile.capabilities.usage_telemetry is False
            assert profile.endpoints.usage_url is None

    def test_the_catalog_never_carries_a_credential_value(self):
        catalog = ProfileCatalog.builtin()
        for profile in catalog:
            for name in profile.credentials.values():
                assert name.isupper(), "una referencia tiene que ser un nombre de variable"
            assert "=" not in json.dumps(profile.credentials)

    def test_the_example_yaml_declares_exactly_the_builtin_catalog(self):
        example = ProfileCatalog.from_yaml(PROFILES_YAML)
        builtin = ProfileCatalog.builtin()
        assert example.ids() == builtin.ids()
        for profile_id in builtin.ids():
            assert (
                example.get(profile_id).model_dump(mode="json")
                == builtin.get(profile_id).model_dump(mode="json")
            ), f"{profile_id} diverge entre el YAML de ejemplo y el catálogo en código"

    def test_the_example_yaml_keeps_its_launcher_commented_out(self):
        # P0 does not launch real profiles: the launcher stays documentation. The
        # example documents the shape, and every line declaring it is a comment.
        lines = PROFILES_YAML.read_text(encoding="utf-8").splitlines()
        declared = [line for line in lines if "start_command: uv run" in line]
        assert declared, "el ejemplo tiene que documentar la forma de start_command"
        assert all(line.lstrip().startswith("#") for line in declared)
        for profile in ProfileCatalog.from_yaml(PROFILES_YAML):
            assert profile.start_command is None

    def test_an_unknown_profile_id_is_refused_with_the_declared_ones(self):
        with pytest.raises(ProfileNotFound) as error:
            ProfileCatalog.builtin().get("nope")
        assert "cascade" in str(error.value)

    def test_two_profiles_cannot_share_an_id(self):
        with pytest.raises(ProfileValidationError):
            ProfileCatalog([cascade_profile(), cascade_profile()])

    def test_the_public_view_exposes_no_path_and_no_command(self):
        rows = ProfileCatalog.builtin().public_view()
        for row in rows:
            rendered = json.dumps(row)
            assert "launch_hint" not in rendered
            assert "backend python" not in rendered
            assert "agent-data" not in row["laboratory"].values()


class TestLaboratoryGuard:
    def test_port_7860_is_refused_by_name_without_touching_the_socket(self, monkeypatch):
        # Any socket construction during this test is a bug: 7860 is answered
        # from the constant, never probed.
        def _forbidden(*args, **kwargs):  # pragma: no cover - only runs on a bug
            raise AssertionError("la guarda abrió un socket para hablar del 7860")

        monkeypatch.setattr(socket, "socket", _forbidden)
        profile = _destination_profile("ws://127.0.0.1:7860/ws")
        problems = port_problems(profile)
        assert any("7860" in problem and "producción" in problem for problem in problems)
        assert port_is_free("127.0.0.1", PRODUCTION_VOICE_PORT) is False

    def test_a_profile_pointing_at_production_is_refused_by_the_destination_guard(self):
        profile = _destination_profile("ws://127.0.0.1:7860/ws")
        with pytest.raises(LaboratoryRefusal) as error:
            assert_laboratory_profile(profile)
        message = str(error.value)
        assert "7860" in message
        assert "puntuadas" in message

    @pytest.mark.parametrize(
        "ws_url",
        [
            "wss://prosper-api.example.com/ws",
            "wss://abc123.ngrok-free.app/ws",
            "ws://hackspain.getprosperapp.com/ws",
        ],
    )
    def test_an_official_destination_is_refused(self, ws_url):
        profile = _destination_profile(ws_url)
        with pytest.raises(LaboratoryRefusal) as error:
            assert_laboratory_profile(profile)
        assert "oficial" in str(error.value)

    def test_a_remote_destination_is_refused_even_when_it_is_not_official(self):
        profile = _destination_profile("ws://203.0.113.9:17860/ws")
        with pytest.raises(LaboratoryRefusal) as error:
            assert_laboratory_profile(profile)
        assert "remoto" in str(error.value)

    def test_an_occupied_port_is_refused_when_the_lab_would_start_something(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen(1)
            port = taken.getsockname()[1]
            profile = _destination_profile(f"ws://127.0.0.1:{port}/ws")
            with pytest.raises(LaboratoryRefusal) as error:
                assert_laboratory_profile(profile, probe_ports=True)
            assert "ocupado" in str(error.value)
            # A live session talks to a process that must already be listening,
            # so the chat path must not apply the occupancy check.
            assert laboratory_problems(profile, probe_ports=False) == []

    def test_a_free_local_port_passes_the_launch_guard(self):
        port = _free_port()
        profile = _destination_profile(f"ws://127.0.0.1:{port}/ws")
        assert_laboratory_profile(profile, probe_ports=True)


# ---- P0.4: the request allowlist ------------------------------------------


class TestRequestAllowlist:
    def test_a_profile_id_with_timing_is_a_valid_request(self):
        assert (
            request_refusals(
                {"profile_id": "cascade", "tts": "espeak-ng", "stt": "none", "reply_idle_ms": 300}
            )
            == []
        )

    @pytest.mark.parametrize(
        "field",
        [
            "ws_url",
            "text_url",
            "usage_url",
            "clinic_url",
            "api_key",
            "scenario",
            "agent_audit_dir",
            "start_command",
            "launch_env",
            "env",
            "cwd",
        ],
    )
    def test_a_browser_cannot_name_a_destination_a_path_or_a_command(self, field):
        problems = request_refusals({"profile_id": "cascade", field: CANARY})
        assert problems, f"{field} debería ser rechazado"
        joined = "; ".join(problems)
        assert field in joined
        assert CANARY not in joined, "el rechazo repitió el valor"

    def test_an_invented_field_is_refused_instead_of_ignored(self):
        joined = "; ".join(request_refusals({"profile_id": "cascade", "nonsense": 1}))
        assert "campos desconocidos" in joined
        assert "nonsense" in joined

    def test_provider_names_are_a_closed_set(self):
        assert request_refusals({"profile_id": "cascade", "tts": "/bin/sh"})
        assert request_refusals({"profile_id": "cascade", "stt": "curl-evil"})

    def test_timing_knobs_are_bounded_numbers(self):
        assert request_refusals({"profile_id": "cascade", "reply_idle_ms": -1})
        assert request_refusals({"profile_id": "cascade", "reply_idle_ms": "soon"})
        assert request_refusals({"profile_id": "cascade", "reply_max_ms": 10**12})
