"""Central configuration. All knobs come from environment (.env)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

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
