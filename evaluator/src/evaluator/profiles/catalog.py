"""The initial profile catalog: the two real engines, declared once.

Both profiles describe the *same* external agent process — the one in
`backend/` — started on a dedicated laboratory port and switched with the
frozen `VOICE_ENGINE` env (`{cascade, gemini_live}`, default `cascade`). They
differ in the engine they select and in the providers that engine talks to;
the ports, endpoints and evidence claims are identical because the process is.

Frozen contract this is pinned against (verified by reading `backend/`, see
`odd/tasks/evaluator-laboratorio.md`):

- entrypoint `uv run --project backend python -m agent.serve`
- address env `VOICE_WS_HOST` (default 0.0.0.0), `VOICE_WS_PORT` (default
  **7860 = production**) and `PORT` for the single-process entrypoint
- readiness `GET /healthz`, voice `ws://host:port/ws`
- text adapter `POST {text_url}/turns`, mounted only when `TURNS_ADAPTER` is
  truthy and gated by loopback or the `x-ops-token`/`token` header
- per-call audit `<DATA_DIR>/calls/<call_id>.jsonl`

`lab_data_dir` keeps the audit inside `evaluator/`: the lab writes no file under
`backend/`. Recordings do not exist in that contract, so neither profile claims
server-side audio; they claim `client_capture`, which is what the evaluator's
own WebSocket client really does.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from evaluator.profiles.guard import destination_problems
from evaluator.profiles.schema import (
    AgentProfile,
    ProfileNotFound,
    ProfileValidationError,
)

# Laboratory ports. 7860 (production) and 7861 (the ops console used by hand)
# are never used here; the evaluator's own README fixes 17860 as the dedicated
# agent port.
LAB_VOICE_PORT = 17860
LAB_OPS_PORT = 17861
LAB_CLINIC_URL = "http://127.0.0.1:18090"
LAB_DATA_DIR = "evaluator/experiments/results/agent-data"

# Non-secret environment an operator starts the laboratory agent with. `PORT`
# is the single-process entrypoint's knob; `VOICE_WS_PORT` is the dev voice
# server's. Both are set so either launch shape lands on the lab port.
LAB_LAUNCH_ENV: dict[str, str] = {
    "VOICE_WS_HOST": "127.0.0.1",
    "VOICE_WS_PORT": str(LAB_VOICE_PORT),
    "PORT": str(LAB_VOICE_PORT),
    "OPS_HTTP_PORT": str(LAB_OPS_PORT),
    "TURNS_ADAPTER": "1",
    "PROSPER_API_BASE_URL": LAB_CLINIC_URL,
    "DATA_DIR": LAB_DATA_DIR,
}


def _laboratory() -> dict[str, Any]:
    return {
        "voice_port": LAB_VOICE_PORT,
        "clinic_url": LAB_CLINIC_URL,
        "submit_key": "pk-local-eval",
        "data_dir": LAB_DATA_DIR,
        "agent_audit_dir": LAB_DATA_DIR,
        "tts": "espeak-ng",
        "launch_hint": (
            "uv run --project backend python -m agent.serve, desde la raíz del repo y "
            "con este entorno"
        ),
    }


def _endpoints() -> dict[str, Any]:
    return {
        # The text adapter lives in the same process as the voice socket
        # (`voice/server.py` mounts it), so it is the same host and port.
        "ws_url": f"ws://127.0.0.1:{LAB_VOICE_PORT}/ws",
        "text_url": f"http://127.0.0.1:{LAB_VOICE_PORT}",
    }


def _capabilities(**overrides: Any) -> dict[str, Any]:
    capabilities: dict[str, Any] = {
        "text": True,
        "voice": True,
        # The lab records what goes over its own socket; the agent writes no
        # WAV (`add_wav_header=False`), so this is not `server_recording`.
        "audio_capture": True,
        "audio_source": "client_capture",
        "transcript": True,  # audit transcript + text adapter replies
        "usage_telemetry": False,  # the agent exposes no usage endpoint today
        "expected_outcome": True,  # scenarios carry accepted outcomes
    }
    capabilities.update(overrides)
    return capabilities


def cascade_profile() -> AgentProfile:
    """The default cascade engine: Deepgram STT -> Helmcode brain -> ElevenLabs."""
    return AgentProfile.from_declaration(
        {
            "id": "cascade",
            "engine": "cascade",
            "version": "lab-1",
            "endpoints": _endpoints(),
            "capabilities": _capabilities(),
            "providers": {
                "name": "deepgram + helmcode + elevenlabs",
                "stack": ["deepgram", "helmcode", "elevenlabs"],
                "docs": "backend/README.md",
                "notes": "motor por defecto del backend y rollback permanente",
            },
            "credentials": {
                "agent_api_key": "PROSPER_API_KEY",
                "stt_api_key": "DEEPGRAM_API_KEY",
                "tts_api_key": "ELEVENLABS_API_KEY",
                "brain_api_key": "HELMCODE_API_KEY",
            },
            "launch_env": {**LAB_LAUNCH_ENV, "VOICE_ENGINE": "cascade"},
            "laboratory": _laboratory(),
            "notes": (
                "sin endpoints de consumo en el contrato congelado: el coste queda "
                "desconocido, nunca cero"
            ),
        }
    )


def gemini_live_profile() -> AgentProfile:
    """The Gemini Live engine: one audio-to-audio model behind the same socket."""
    return AgentProfile.from_declaration(
        {
            "id": "gemini_live",
            "engine": "gemini_live",
            "version": "lab-1",
            "endpoints": {"ws_url": "ws://127.0.0.1:17862/ws", "text_url": "http://127.0.0.1:17862"},
            "capabilities": _capabilities(),
            "providers": {
                "name": "gemini live",
                "stack": ["gemini", "helmcode"],
                "docs": "backend/README.md",
                "notes": "modelo de audio a audio; la clave vive en GEMINI_API_KEY",
            },
            "credentials": {
                "agent_api_key": "PROSPER_API_KEY",
                "gemini_api_key": "GEMINI_API_KEY",
            },
            "launch_env": {**LAB_LAUNCH_ENV, "VOICE_ENGINE": "gemini_live",
                           "VOICE_WS_PORT": "17862", "PORT": "17862", "OPS_HTTP_PORT": "17863",
                           "DATA_DIR": f"{LAB_DATA_DIR}-gemini"},
            "laboratory": {**_laboratory(), "voice_port": 17862,
                           "data_dir": f"{LAB_DATA_DIR}-gemini",
                           "agent_audit_dir": f"{LAB_DATA_DIR}-gemini"},
            "notes": (
                "la voz la sintetiza el propio modelo: no hay STT/TTS separados que "
                "declarar"
            ),
        }
    )


class ProfileCatalog:
    """The profiles this server declared, addressed by id and nothing else.

    A browser asks for an id; the server decides what that means. Duplicate ids
    are refused at construction: two profiles that cannot be told apart are
    worse than a config that will not load.
    """

    def __init__(self, profiles: Iterable[AgentProfile] = ()) -> None:
        self._by_id: dict[str, AgentProfile] = {}
        for profile in profiles:
            self.add(profile)

    def add(self, profile: AgentProfile) -> None:
        if profile.id in self._by_id:
            raise ProfileValidationError(
                profile.id, [f"id: ya hay un perfil declarado con el id {profile.id!r}"]
            )
        self._by_id[profile.id] = profile

    def get(self, profile_id: str) -> AgentProfile:
        profile = self._by_id.get(profile_id)
        if profile is None:
            declared = ", ".join(self.ids()) or "ninguno"
            raise ProfileNotFound(
                f"perfil desconocido: {profile_id!r} (declarados en este servidor: {declared})"
            )
        return profile

    def ids(self) -> list[str]:
        return sorted(self._by_id)

    def __len__(self) -> int:
        return len(self._by_id)

    def __contains__(self, profile_id: object) -> bool:
        return profile_id in self._by_id

    def __iter__(self):
        return iter(self._by_id.values())

    def public_view(self) -> list[dict[str, Any]]:
        """Every profile, browser-safe, with its laboratory guard verdict."""
        rows = []
        for profile_id in self.ids():
            profile = self._by_id[profile_id]
            row = profile.public_view()
            row["refusals"] = destination_problems(profile)
            rows.append(row)
        return rows

    @classmethod
    def builtin(cls) -> ProfileCatalog:
        """The catalog the evaluator ships with."""
        return cls([cascade_profile(), gemini_live_profile()])

    @classmethod
    def from_declarations(cls, entries: Iterable[dict[str, Any]]) -> ProfileCatalog:
        """Build a catalog from a list of YAML/JSON-shaped declarations."""
        return cls([AgentProfile.from_declaration(entry) for entry in entries])

    @classmethod
    def from_yaml(cls, path: Path | str) -> ProfileCatalog:
        """Load `experiments/profiles.yaml`-shaped files (`profiles:` list)."""
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        entries = raw.get("profiles") if isinstance(raw, dict) else raw
        if not isinstance(entries, list) or not entries:
            raise ProfileValidationError(str(path), ["profiles: falta la lista de perfiles"])
        try:
            return cls.from_declarations(entries)
        except ValidationError as exc:  # shape error: report it as a profile error
            raise ProfileValidationError(str(path), [str(exc)]) from None
