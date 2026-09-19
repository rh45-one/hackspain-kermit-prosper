"""The request surface of a live session: one profile id, nothing else.

The console used to ask for a WebSocket URL, a clinic URL, a scenario path and
an audit directory. That let a browser choose an outbound destination and point
the server at files of its choosing. The contract now is one **profile id** the
server already declared; this module is the allowlist that enforces it.

Anything that selects a destination, a path, a command or an environment is
refused by name, and the refusal never repeats the value it refused.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Timing knobs and modality choices a session may still set: they change how
# long the rig waits, never who it talks to.
REQUEST_ALLOWED_FIELDS = frozenset(
    {
        "profile_id",
        "call_id",
        "from_number",
        "tts",
        "stt",
        "greet_first",
        "reply_idle_ms",
        "reply_max_ms",
        "reply_start_ms",
        "greeting_wait_ms",
        "turn_tail_ms",
        "submission_wait_s",
    }
)

# Named explicitly so the error can say which door was tried, without echoing
# the value behind it. `profile`/`engine` are here because a client that names
# its own engine is also choosing a destination.
REQUEST_FORBIDDEN_FIELDS = (
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
    "profile",
    "engine",
)

FORBIDDEN_FIELD_MESSAGE = (
    "el navegador no puede elegir destino, ruta, comando ni entorno; "
    "pedí un profile_id del catálogo del servidor"
)

# Providers a session may name. These are *names of things the server already
# runs*, not URLs: the browser cannot introduce a destination, and an unknown
# name is refused instead of reaching a provider factory.
ALLOWED_TTS_PROVIDERS = ("espeak-ng", "pico2wave")
ALLOWED_STT_PROVIDERS = ("none", "deepgram", "openai-compat", "whisper-on-prem")

# Timing knobs: milliseconds or seconds, never negative and never unbounded.
_TIMING_FIELDS = {
    "reply_idle_ms": (0.0, 60_000.0),
    "reply_max_ms": (0.0, 600_000.0),
    "reply_start_ms": (0.0, 600_000.0),
    "greeting_wait_ms": (0.0, 600_000.0),
    "turn_tail_ms": (0.0, 60_000.0),
    "submission_wait_s": (0.0, 600.0),
}


def _timing_refusals(body: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    for name, (low, high) in _TIMING_FIELDS.items():
        if name not in body or body[name] is None:
            continue
        value = body[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append(f"{name}: tiene que ser un número")
        elif not low <= float(value) <= high:
            problems.append(f"{name}: fuera de rango ({low:g} a {high:g})")
    return problems


def _provider_refusals(body: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    tts = body.get("tts")
    if tts is not None and tts not in ALLOWED_TTS_PROVIDERS:
        problems.append(f"tts: proveedor desconocido (válidos: {', '.join(ALLOWED_TTS_PROVIDERS)})")
    stt = body.get("stt")
    if stt not in (None, "") and stt not in ALLOWED_STT_PROVIDERS:
        problems.append(f"stt: proveedor desconocido (válidos: {', '.join(ALLOWED_STT_PROVIDERS)})")
    for name in ("profile_id", "call_id", "from_number", "lang"):
        value = body.get(name)
        if value is not None and not isinstance(value, str):
            problems.append(f"{name}: tiene que ser texto")
    return problems


def request_refusals(body: Mapping[str, Any]) -> list[str]:
    """Problems with a chat request body, or an empty list.

    A field is refused when it is forbidden by name, unknown, or carries a value
    outside the server's closed sets: a client cannot smuggle a destination past
    the server by inventing a key or a provider name.
    """
    problems: list[str] = []
    forbidden = sorted(name for name in REQUEST_FORBIDDEN_FIELDS if name in body)
    if forbidden:
        problems.append(f"{FORBIDDEN_FIELD_MESSAGE}: {', '.join(forbidden)}")
    unknown = sorted(
        name
        for name in body
        if name not in REQUEST_ALLOWED_FIELDS and name not in REQUEST_FORBIDDEN_FIELDS
    )
    if unknown:
        problems.append(f"campos desconocidos en la petición: {', '.join(unknown)}")
    problems.extend(_provider_refusals(body))
    problems.extend(_timing_refusals(body))
    return problems
