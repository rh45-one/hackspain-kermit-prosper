"""Recursive allowlist + redaction for everything sent to the Jev sidecar.

Two independent controls are applied to the server-owned snapshot before it is
serialised, so no protected value can leave the process even if a caller passes
an unexpected field or writes a phone number into an utterance:

1. **Allowlist** — only keys on :data:`ALLOWED_KEYS` survive; anything else is
   dropped at every nesting level.
2. **Redaction** — sensitive keys are replaced wholesale and every surviving
   string is scrubbed of phone numbers, emails, national ids (DNI/NIE), dates
   and other identifiers.

Nothing here logs; the text never reaches a logger or a trace.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from agent.decision.models import REDACTED, JsonValue, TurnDecisionInput

MAX_DEPTH = 12

# Keys permitted in the redacted state, at any nesting level. Unknown keys are
# dropped rather than forwarded, which is what makes the control an allowlist.
ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "caller_transcript",
        "transcript",
        "call_context",
        "language",
        "caller_language",
        "role",
        "text",
        "phase",
        "turn_index",
        "identified",
        "identity_status",
        "patient_confirmed",
        "requested_specialty",
        "requested_site",
        "requested_provider",
        "requested_part_of_day",
        "requested_date_text",
    }
)

# Normalised keys whose value is never forwarded.
_SENSITIVE_EXACT: frozenset[str] = frozenset(
    {
        "id",
        "ids",
        "identifier",
        "identifiers",
        "dni",
        "nie",
        "nif",
        "ssn",
        "phone",
        "phones",
        "phone_number",
        "mobile",
        "mobile_number",
        "tel",
        "telephone",
        "telephone_number",
        "email",
        "email_address",
        "dob",
        "date_of_birth",
        "birth_date",
        "birthdate",
        "address",
        "home_address",
        "patient_id",
        "record_id",
        "history_number",
        "expediente",
        "policy_number",
        "insurance_number",
        "credit_card",
        "card_number",
        "account_number",
        "iban",
        "passport",
    }
)

_SENSITIVE_TOKENS: frozenset[str] = frozenset(
    {
        "id",
        "identifier",
        "dni",
        "nie",
        "nif",
        "ssn",
        "phone",
        "mobile",
        "tel",
        "telephone",
        "email",
        "dob",
        "birth",
        "birthdate",
        "address",
        "expediente",
        "iban",
        "passport",
    }
)

_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b")
_NIE_RE = re.compile(r"\b[XYZxyz][\-\s]?\d{7}[\-\s]?[A-Za-z]\b")
_DNI_RE = re.compile(r"\b\d{8}[\-\s]?[A-Za-z]\b")
_DATE_RE = re.compile(
    r"\b(?:"
    r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"
    r"|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}"
    r")\b"
)
_PHONE_RES: tuple[re.Pattern[str], ...] = (
    # International, e.g. +34 600 123 456 / +1 (555) 010-9999
    re.compile(r"\+\d(?:[\s().\-]?\d){7,14}"),
    # Spanish landline/mobile grouped, e.g. 600 123 456 / 971-123-456
    re.compile(r"(?<!\d)[6789]\d{2}[\s.\-]?\d{3}[\s.\-]?\d{3}(?!\d)"),
    # Spanish nine digit run, e.g. 600123456
    re.compile(r"(?<!\d)[6789]\d{8}(?!\d)"),
)


def normalize_key(key: object) -> str:
    """Lower-case a key and split camelCase into snake_case tokens."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key))
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    return text.strip("_").lower()


def is_sensitive_key(key: object) -> bool:
    """True when this key names a protected identifier or contact field."""
    normalized = normalize_key(key)
    if normalized in _SENSITIVE_EXACT:
        return True
    if normalized.endswith(("_id", "_ids")):
        return True
    return any(token in _SENSITIVE_TOKENS for token in normalized.split("_"))


def redact_text(text: str) -> str:
    """Strip supported protected value patterns from a single string."""
    value = _EMAIL_RE.sub(REDACTED, text)
    value = _NIE_RE.sub(REDACTED, value)
    value = _DNI_RE.sub(REDACTED, value)
    value = _DATE_RE.sub(REDACTED, value)
    for pattern in _PHONE_RES:
        value = pattern.sub(REDACTED, value)
    return value


def redact_value(
    value: object,
    *,
    allowlist: frozenset[str] | None = ALLOWED_KEYS,
    depth: int = 0,
) -> JsonValue:
    """Recursively allowlist keys and redact protected values.

    Pass ``allowlist=None`` to keep every key and apply redaction only.
    """
    if depth > MAX_DEPTH:
        return REDACTED
    if isinstance(value, Mapping):
        cleaned: dict[str, JsonValue] = {}
        for raw_key, raw_item in value.items():
            key = str(raw_key)
            if allowlist is not None and normalize_key(key) not in allowlist:
                continue
            if is_sensitive_key(key):
                cleaned[key] = REDACTED
            else:
                cleaned[key] = redact_value(raw_item, allowlist=allowlist, depth=depth + 1)
        return cleaned
    if isinstance(value, (bytes, bytearray)):
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, (list, tuple, set, frozenset, Sequence)):
        return [redact_value(item, allowlist=allowlist, depth=depth + 1) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(str(value))


def redact_turn_input(snapshot: TurnDecisionInput) -> JsonValue:
    """Build the redacted ``state`` object for a Jev request."""
    state: dict[str, JsonValue] = {
        "caller_transcript": [turn.as_wire() for turn in snapshot.transcript],
    }
    if snapshot.context:
        state["call_context"] = dict(snapshot.context)
    if snapshot.language:
        state["language"] = snapshot.language
    return redact_value(state)


__all__ = [
    "ALLOWED_KEYS",
    "MAX_DEPTH",
    "is_sensitive_key",
    "normalize_key",
    "redact_text",
    "redact_turn_input",
    "redact_value",
]
