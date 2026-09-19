"""Central configuration. All knobs come from environment (.env)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent.orgs import DEFAULT_ORG_ID, normalize_org_id

# Repository layout: backend/{pyproject.toml,src/agent/config.py}.
# Paths are anchored here so commands behave the same whether they run from the
# repository root or from backend/.
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Prosper platform
    prosper_api_base_url: str = "https://hackspain.getprosperapp.com"
    prosper_api_key: str = ""

    # Helmcode (agent brain)
    helmcode_api_key: str = ""
    helmcode_base_url: str = "https://api.helmcode.com/v1"
    agent_model: str = "deepseek-v4-flash"
    agent_model_fallback: str = "glm5.3"

    # Voice
    deepgram_api_key: str = ""
    deepgram_stt_model: str = "nova-3"
    deepgram_stt_language: str = "multi"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_tts_model: str = "eleven_turbo_v2_5"
    cartesia_api_key: str = ""

    # Voice engine selection: cascade (STT->LLM->TTS) or gemini_live. cascade
    # is the configured default and the permanent rollback; gemini_live only
    # becomes the default after the offline acceptance + live gate.
    voice_engine: str = "cascade"

    # Gemini Live audio host (VOICE_ENGINE=gemini_live). The pinned model is
    # not an extended-thinking variant; see agent.voice.gemini_live.
    gemini_api_key: str = ""
    gemini_live_model: str = "gemini-3.8-live"
    gemini_voice_id: str = ""
    # Gemini Live speech_config.language_code. Empty means "let the model
    # choose", which is the default: a pinned code is also an accent, and
    # pinning es-ES had the agent answer English callers in English with a
    # Spanish accent. Set it only to force one language.
    gemini_language: str = ""
    # RNNoise on the inbound wire. Measured at 2.48 ms per 20 ms frame, which
    # one call absorbs easily and ten do not: ten concurrent calls would ask
    # for 1240 ms of CPU per second of audio on a single event loop, and a
    # loop that falls behind is exactly the failure this whole path fights.
    # Off by default; worth turning on for the Noise problem, where the bed
    # is mixed at 5 dB SNR and a clean signal is the whole point.
    noise_suppression: bool = False

    # TypeSafe Jev structured-decision sidecar (advisory only).
    typesafe_api_key: str = ""
    typesafe_base_url: str = "https://api.typesafe.ai"
    jev_model: str = "jev-1.13.0"
    # TypeSafe publishes 70-500 ms end-to-end for Jev, so a 300 ms budget
    # turned the slow half of that range into silent abstentions. 600 ms
    # covers the published tail with margin and still fits inside a turn.
    jev_timeout_seconds: float = 0.600
    jev_min_confidence: float = 0.5

    # Server
    voice_ws_host: str = "0.0.0.0"
    voice_ws_port: int = 7860
    ops_http_port: int = 7861
    # Shared secret for the ops console. Unset, the console answers only to
    # loopback — so a deployed host serves nothing until this is set on
    # purpose. See agent/ops/console.py.
    ops_token: str = ""

    # The organisation this process answers for. One clinic today; the value
    # rides on every CallContext and decides which directory its trace and
    # which catalogue cache it gets. Credentials are still global (one
    # PROSPER_API_KEY): that is the next step, and the one that needs a
    # database.
    org_id: str = DEFAULT_ORG_ID

    # Behaviour
    caller_tz: str = "Europe/Madrid"
    max_call_minutes: int = 3
    submit_window_seconds: int = 30
    data_dir: str = "./data"
    log_level: str = "INFO"

    @field_validator("voice_engine")
    @classmethod
    def _validate_voice_engine(cls, value: str) -> str:
        """Fail fast on an unsupported engine: never run in a guessed mode."""
        allowed = {"cascade", "gemini_live"}
        if value not in allowed:
            raise ValueError(f"VOICE_ENGINE must be one of {sorted(allowed)}; got {value!r}")
        return value

    @field_validator("data_dir")
    @classmethod
    def _resolve_data_dir(cls, value: str) -> str:
        """Anchor a relative DATA_DIR to the backend root, not the cwd.

        A bare ``./data`` must mean ``backend/data`` even when the server,
        ops console or simulator is launched from the repository root.
        """
        path = Path(value)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return str(path)

    @field_validator("org_id")
    @classmethod
    def _validate_org_id(cls, value: str) -> str:
        """Fail at boot, not at the first call: the id is a directory name."""
        return normalize_org_id(value)

    # ---- call traces -----------------------------------------------------
    # Written to DATA_DIR/<org_id>/calls/<call_id>.jsonl. Before organisations
    # existed they were written to DATA_DIR/calls, and 190-odd traces of real
    # scored calls still sit there — on this laptop and on the Fly volume. The
    # readers below read both for the default organisation, so nothing that
    # was ever recorded stops being readable. Nothing is ever written there
    # again.
    def calls_dir_for(self, org_id: str = DEFAULT_ORG_ID) -> str:
        """Where this organisation's traces are written."""
        return f"{self.data_dir}/{normalize_org_id(org_id)}/calls"

    @property
    def calls_dir(self) -> str:
        """The default organisation's trace directory (the write path)."""
        return self.calls_dir_for(DEFAULT_ORG_ID)

    @property
    def legacy_calls_dir(self) -> str:
        """The pre-organisation layout. Read-only."""
        return f"{self.data_dir}/calls"

    def call_trace_dirs(self, org_id: str = DEFAULT_ORG_ID) -> list[Path]:
        """Every existing directory holding this org's traces, current first."""
        org_id = normalize_org_id(org_id)
        dirs = [Path(self.calls_dir_for(org_id))]
        if org_id == DEFAULT_ORG_ID:
            dirs.append(Path(self.legacy_calls_dir))
        return [d for d in dirs if d.is_dir()]

    def call_trace_paths(self, org_id: str = DEFAULT_ORG_ID) -> list[Path]:
        """Every trace file for an org, deduplicated by call id, current wins."""
        found: dict[str, Path] = {}
        for directory in self.call_trace_dirs(org_id):
            for path in directory.glob("*.jsonl"):
                found.setdefault(path.name, path)
        return list(found.values())

    def call_trace_path(self, call_id: str, org_id: str = DEFAULT_ORG_ID) -> Path:
        """One call's trace. The current layout wins; falls back to legacy.

        Returns the current-layout path when the trace exists in neither, so
        the caller reports "not found" against the path we would write.
        """
        candidates = [d / f"{call_id}.jsonl" for d in self.call_trace_dirs(org_id)]
        for path in candidates:
            if path.is_file():
                return path
        return Path(self.calls_dir_for(org_id)) / f"{call_id}.jsonl"


@lru_cache
def settings() -> Settings:
    return Settings()
