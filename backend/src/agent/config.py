"""Central configuration. All knobs come from environment (.env)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    gemini_vad_mode: Literal["local", "server"] = "server"
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

    @property
    def calls_dir(self) -> str:
        return f"{self.data_dir}/calls"


@lru_cache
def settings() -> Settings:
    return Settings()
