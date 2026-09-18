"""Offline tests for recursive allowlisting and PII redaction before Jev."""
from __future__ import annotations

import json

import pytest

from agent.decision import (
    ALLOWED_KEYS,
    REDACTED,
    TranscriptTurn,
    TurnDecisionInput,
    redact_text,
    redact_turn_input,
    redact_value,
)
from agent.decision.redaction import MAX_DEPTH, is_sensitive_key, normalize_key


@pytest.mark.parametrize(
    ("raw", "secret"),
    [
        ("llamame al +34 600 123 456", "+34 600 123 456"),
        ("o al 600123456 si no contesto", "600123456"),
        ("mi movil es 655-123-456", "655-123-456"),
        ("escribe a ana.lopez@example.com", "ana.lopez@example.com"),
        ("mi DNI es 12345678Z", "12345678Z"),
        ("mi NIE es X1234567L", "X1234567L"),
        ("nacida el 1988-03-14", "1988-03-14"),
        ("la cita es el 12/10/2026", "12/10/2026"),
    ],
)
def test_redact_text_strips_supported_patterns(raw: str, secret: str):
    redacted = redact_text(raw)
    assert secret not in redacted
    assert REDACTED in redacted


def test_redact_text_leaves_plain_clinical_text_untouched():
    raw = "Quiero pedir cita con digestivo por la manana."
    assert redact_text(raw) == raw


def test_normalize_key_handles_camel_case_and_punctuation():
    assert normalize_key("phoneNumber") == "phone_number"
    assert normalize_key("national-id") == "national_id"
    assert normalize_key("  Date Of Birth ") == "date_of_birth"


@pytest.mark.parametrize(
    "key",
    [
        "phone",
        "phone_number",
        "phoneNumber",
        "mobile",
        "email",
        "email_address",
        "dni",
        "nie",
        "nif",
        "ssn",
        "date_of_birth",
        "dateOfBirth",
        "dob",
        "national_id",
        "patient_id",
        "patientId",
        "record_id",
        "expediente",
        "iban",
    ],
)
def test_sensitive_keys_detected(key: str):
    assert is_sensitive_key(key) is True


@pytest.mark.parametrize("key", ["valid", "paid", "grid", "general", "role", "text", "phase"])
def test_non_sensitive_keys_not_flagged(key: str):
    assert is_sensitive_key(key) is False


def test_redact_value_replaces_sensitive_keys_wholesale():
    cleaned = redact_value(
        {"phone_number": "600123456", "patientId": "P00042", "role": "caller", "text": "hola"},
        allowlist=None,
    )
    assert cleaned["phone_number"] == REDACTED
    assert cleaned["patientId"] == REDACTED
    assert cleaned["role"] == "caller"
    assert cleaned["text"] == "hola"


def test_redact_value_recurses_through_lists_and_dicts():
    cleaned = redact_value(
        {"call_context": {"notes": ["llama al 600123456", {"email": "a@b.com"}]}},
        allowlist=None,
    )
    assert cleaned == {"call_context": {"notes": ["llama al [REDACTED]", {"email": REDACTED}]}}


def test_redact_value_default_allowlist_drops_unknown_keys():
    cleaned = redact_value({"phase": "intake", "unknown_field": "drop me", "patient_id": "P1"})
    assert cleaned == {"phase": "intake"}


def test_redact_value_allowlist_none_keeps_every_key():
    cleaned = redact_value({"phase": "intake", "unknown_field": "kept"}, allowlist=None)
    assert cleaned == {"phase": "intake", "unknown_field": "kept"}


def test_redact_value_depth_limit_fails_closed():
    value: object = "leaf"
    for _ in range(MAX_DEPTH + 3):
        value = {"call_context": value}
    cleaned = redact_value(value, allowlist=None)
    serialized = json.dumps(cleaned)
    assert REDACTED in serialized
    assert "leaf" not in serialized


def test_redact_value_redacts_bytes():
    assert redact_value(b"raw", allowlist=None) == REDACTED


def test_redact_value_preserves_scalars():
    assert redact_value(True, allowlist=None) is True
    assert redact_value(None, allowlist=None) is None
    assert redact_value(3, allowlist=None) == 3
    assert redact_value(4.5, allowlist=None) == 4.5


def test_allowed_keys_is_frozen_allowlist():
    assert isinstance(ALLOWED_KEYS, frozenset)
    assert {"caller_transcript", "call_context", "role", "text"} <= ALLOWED_KEYS


def test_redact_turn_input_builds_state_and_strips_pii():
    snapshot = TurnDecisionInput(
        transcript=(
            TranscriptTurn(role="caller", text="Mi telefono es 600123456 y mi DNI 12345678Z."),
            TranscriptTurn(role="agent", text="Perfecto."),
        ),
        context={"phase": "intake", "patient_id": "P00042", "requested_specialty": "general"},
        language="es",
    )
    state = redact_turn_input(snapshot)
    serialized = json.dumps(state, ensure_ascii=False)
    assert "600123456" not in serialized
    assert "12345678Z" not in serialized
    assert "P00042" not in serialized
    assert state["language"] == "es"
    assert state["call_context"] == {"phase": "intake", "requested_specialty": "general"}
    assert state["caller_transcript"][0] == {
        "role": "caller",
        "text": f"Mi telefono es {REDACTED} y mi DNI {REDACTED}.",
    }
