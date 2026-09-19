"""Credential redaction: no response body, manifest or error repeats a value.

`GET /api/runs/{run_id}` served the raw run manifest, and the manifest carries
`candidates[].env` — the environment the runner used to start the agent. That
map survived serialization (`experiment.py` only dropped `start_command`), so a
provider key written in an experiment YAML reached the browser as text.

Two complementary passes, both conservative:

- `redact_secrets` walks a JSON-shaped value and replaces the *value* of any
  sensitive-named key, plus every value inside an `env` map (a name is
  configuration; a value may be a secret). Names survive: an operator still sees
  which variables were set.
- `redact_text` scrubs provider-key shapes and `NAME=value` assignments out of
  free text (error strings, diagnostics) without echoing what it removed.

The on-disk manifest keeps whatever the runner wrote — the runner is outside
this package's write surface — and that is exactly why every response goes
through here instead of trusting the file.
"""
from __future__ import annotations

import re
from typing import Any

REDACTED = "***"

# A key is sensitive when one of these appears as its own word ("apikey" and
# friends are covered by the suffix check below). Substring matching would
# redact `monkey_counter`, so the key is split first.
SENSITIVE_KEY_PARTS = frozenset(
    {
        "key",
        "keys",
        "token",
        "tokens",
        "secret",
        "secrets",
        "password",
        "passwd",
        "pwd",
        "credential",
        "credentials",
        "authorization",
        "auth",
        "bearer",
        "apikey",
        "privatekey",
    }
)

# A map of environment settings: every value goes, every name stays.
ENV_MAP_KEY = "env"

_SENSITIVE_SUFFIXES = ("apikey", "apisecret", "authtoken", "accesstoken", "privatekey")

_SECRET_TEXT_PATTERNS = (
    # Provider key shapes: sk-..., dg-..., hf_..., AIza..., JWTs.
    re.compile(r"\b(?:sk|pk|dg|hf|ghp|xox[abp]|AIza|eyJ)[-_A-Za-z0-9.]{8,}"),
    # ENV_VAR=value, the shape a leaky log line takes. `***` is left alone.
    re.compile(r"\b[A-Z][A-Z0-9_]{2,}=(?!\*)\S+"),
)

_SPLIT_PATTERN = re.compile(r"[^a-z0-9]+")


def is_sensitive_key(key: Any) -> bool:
    """True when this JSON key name holds a credential by convention."""
    if not isinstance(key, str):
        return False
    parts = [part for part in _SPLIT_PATTERN.split(key.lower()) if part]
    if not parts:
        return False
    if any(part in SENSITIVE_KEY_PARTS for part in parts):
        return True
    joined = "".join(parts)
    return any(joined.endswith(suffix) for suffix in _SENSITIVE_SUFFIXES)


def redact_secrets(value: Any, *, key: Any = None) -> Any:
    """Deep-copy `value`, replacing credential values with a marker.

    Values are never inspected for looking secret here: an `env` map is redacted
    whole, because the only thing this layer can promise is that no value in it
    survives a response. `None` is left as `None` so a manifest keeps meaning.
    """
    if isinstance(value, dict):
        if isinstance(key, str) and key.lower() == ENV_MAP_KEY:
            return {name: (None if item is None else REDACTED) for name, item in value.items()}
        return {name: redact_secrets(item, key=name) for name, item in value.items()}
    if isinstance(value, list):
        return [redact_secrets(item, key=key) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item, key=key) for item in value)
    if key is not None and is_sensitive_key(key) and value is not None:
        return REDACTED
    return value


def redact_text(text: str) -> str:
    """Scrub credential shapes out of free text (errors, diagnostics)."""
    if not text:
        return text
    redacted = text
    for pattern in _SECRET_TEXT_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)
    return redacted
