"""What the agent is actually running, read off the live process.

The settings screen used to be a paragraph telling you to go and edit
`backend/.env`, which is documentation pretending to be a status page. It said
`cascade` was an option when cascade cannot start — its Helmcode key is a
placeholder and the API answers 401 — so it was documentation that was also
wrong.

This reports the running values instead: which engine answered the last call,
which prompt version, whether the catalogue is warm, which sidecars are
configured. Read-only and secret-free: names and versions, never a key.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

router = APIRouter(prefix="/ops/api/live")


def _access(request: Request) -> None:
    from agent.ops.console import require_ops_access

    require_ops_access(request)


def _configured(value: Any) -> bool:
    """A credential is present and is not one of the repo's placeholders."""
    text = str(value or "")
    return bool(text) and "REPLACE_ME" not in text


@router.get("/agent")
async def agent_configuration(_: None = Depends(_access)) -> dict[str, Any]:
    """The running configuration, as facts rather than instructions."""
    from agent.brain import deps
    from agent.brain.prompts import PROMPT_ID
    from agent.config import settings
    from agent.orgs import DEFAULT_ORG_ID

    config = settings()
    engine = str(getattr(config, "voice_engine", "") or "cascade")

    cache = deps.try_catalogue_cache(DEFAULT_ORG_ID)
    warm = bool(cache is not None and getattr(cache, "warmed", False))

    # Cascade is listed because it is what the code falls back to, not because
    # it is a choice: without a Helmcode key it cannot answer a call at all.
    # A screen that offers it as an option is offering silence.
    cascade_possible = _configured(getattr(config, "helmcode_api_key", "")) and _configured(
        getattr(config, "elevenlabs_voice_id", "")
    )

    return {
        "engine": {
            "running": engine,
            "model": getattr(config, "gemini_live_model", "") if engine == "gemini_live" else None,
            "voice": getattr(config, "gemini_voice_id", "") or None,
            # Unset on purpose: native audio models choose the language
            # themselves and cannot be pinned to one.
            "language": getattr(config, "gemini_language", "") or "la elige el modelo",
            "configured": _configured(getattr(config, "gemini_api_key", "")),
            "alternatives": {
                "cascade": {
                    "usable": cascade_possible,
                    "why_not": None
                    if cascade_possible
                    else "sin clave de Helmcode ni voz de ElevenLabs: no puede atender una llamada",
                }
            },
        },
        "prompt": {"version": PROMPT_ID},
        "clinic": {
            "organisation": DEFAULT_ORG_ID,
            "catalogue_warm": warm,
            "providers": len(getattr(cache, "providers_by_id", {}) or {}) if warm else 0,
            "api_configured": _configured(getattr(config, "prosper_api_key", "")),
        },
        "sidecars": {
            "jev": {
                "configured": _configured(getattr(config, "typesafe_api_key", "")),
                "model": getattr(config, "jev_model", "") or None,
                "advisory_only": True,
            }
        },
        "limits": {
            "call_minutes": getattr(config, "max_call_minutes", None),
            "submit_window_seconds": getattr(config, "submit_window_seconds", None),
        },
        # What this screen cannot do, said once and honestly rather than as a
        # footnote under controls that look clickable.
        "read_only": [
            "El prompt y el motor se leen del entorno al arrancar; no se editan desde aquí.",
            "No hay control manual de llamadas: el agente atiende lo que le marcan.",
        ],
    }
