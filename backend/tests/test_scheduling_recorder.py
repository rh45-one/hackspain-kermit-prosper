"""National id check letters, phone folding, email, slot and body normalization."""

from __future__ import annotations

import pytest

from agent.scheduling.recorder import (
    ActionRecorder,
    build_body,
    normalize_action,
    normalize_email,
    normalize_phone,
    normalize_slot,
    validate_national_id,
)


def test_dni_valid() -> None:
    assert validate_national_id("12345678Z") == "12345678Z"


def test_dni_with_dash_and_lowercase() -> None:
    assert validate_national_id("12345678-z") == "12345678Z"


def test_dni_with_internal_whitespace() -> None:
    assert validate_national_id("1234 5678 Z") == "12345678Z"
    assert validate_national_id("1234\t5678\nZ") == "12345678Z"


def test_dni_wrong_letter_raises() -> None:
    with pytest.raises(ValueError, match="check letter"):
        validate_national_id("12345678K")


def test_dni_bad_shape_raises() -> None:
    with pytest.raises(ValueError):
        validate_national_id("1234Z")
    with pytest.raises(ValueError):
        validate_national_id("")
    with pytest.raises(ValueError):
        validate_national_id("1234567AB")


def test_nie_valid() -> None:
    # X + 1234567 -> number 01234567 -> 1234567 % 23 = 19 -> letter L
    assert validate_national_id("X1234567L") == "X1234567L"


def test_nie_lowercase_and_spaces() -> None:
    assert validate_national_id("x-1234567-l") == "X1234567L"
    assert validate_national_id(" x 1234567 l ") == "X1234567L"


def test_nie_wrong_letter_raises() -> None:
    with pytest.raises(ValueError, match="check letter"):
        validate_national_id("X-1234567-Z")


def test_phone_folding() -> None:
    assert normalize_phone("+34 612 345 678") == "612345678"
    assert normalize_phone("0034612345678") == "612345678"
    assert normalize_phone("612-345-678") == "612345678"
    assert normalize_phone("612.345.678") == "612345678"
    assert normalize_phone("+34612345678") == "612345678"


def test_email_strips_internal_whitespace() -> None:
    assert normalize_email(" Ana.Garcia@Gmail.com ") == "ana.garcia@gmail.com"
    assert normalize_email(" ana.garcia @ gmail.com ") == "ana.garcia@gmail.com"


@pytest.mark.parametrize("raw", ["not-an-email", "a@@b.com", "a@b", "a@.com", "a@b."])
def test_email_invalid_raises(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_email(raw)


def test_slot_truncates_seconds_keeps_offset() -> None:
    assert normalize_slot("2026-09-19T10:30:07+02:00") == "2026-09-19T10:30:00+02:00"


def test_slot_converts_utc_to_madrid() -> None:
    assert normalize_slot("2026-09-19T08:30:00+00:00") == "2026-09-19T10:30:00+02:00"
    assert normalize_slot("2026-09-19T08:30:00Z") == "2026-09-19T10:30:00+02:00"


def test_slot_naive_is_madrid_wall_time() -> None:
    assert normalize_slot("2026-09-19T10:30:00") == "2026-09-19T10:30:00+02:00"


def test_slot_invalid_raises() -> None:
    with pytest.raises(ValueError):
        normalize_slot("not-a-slot")
    with pytest.raises(ValueError):
        normalize_slot("")


def test_register_action_normalizes_everything() -> None:
    action = {
        "route": "register",
        "given_name": " Ana ",
        "first_surname": "García",
        "second_surname": "López",
        "national_id": "12345678-z",
        "date_of_birth": "1990-05-12",
        "phone": "+34 612 345 678",
        "email": " Ana.Garcia @ Gmail.com ",
        "insurer": "sanitas",
    }
    out = normalize_action(action)
    assert out["national_id"] == "12345678Z"
    assert out["phone"] == "612345678"
    assert out["email"] == "ana.garcia@gmail.com"
    assert out["given_name"] == "Ana"


def test_book_action_normalizes_slot() -> None:
    out = normalize_action(
        {
            "route": "book",
            "patient_id": "P1",
            "provider_id": "PR05",
            "location_id": "sur",
            "appointment_type_id": "review",
            "slot": "2026-09-24T08:30:00+00:00",
            "policy_id": "sanitas",
        }
    )
    assert out["slot"] == "2026-09-24T10:30:00+02:00"


BOOK = {
    "route": "book",
    "patient_id": "P00042",
    "provider_id": "PR05",
    "location_id": "sur",
    "appointment_type_id": "review",
    "slot": "2026-09-24T16:30:00+02:00",
    "policy_id": "sanitas",
}


def test_build_body_is_exact_route_shape() -> None:
    body = build_body({**BOOK, "unexpected": "drop-me"}, "call-1")
    assert body["call_id"] == "call-1"
    assert set(body) == {
        "call_id",
        "patient_id",
        "provider_id",
        "location_id",
        "appointment_type_id",
        "slot",
        "policy_id",
    }


def test_build_body_requires_every_field() -> None:
    incomplete = {key: value for key, value in BOOK.items() if key != "policy_id"}
    with pytest.raises(ValueError, match="policy_id"):
        build_body(incomplete, "call-1")


def test_build_body_rejects_unknown_route() -> None:
    with pytest.raises(ValueError, match="unknown action route"):
        build_body({"route": "frobnicate"}, "call-1")


def test_reason_enum_is_folded() -> None:
    body = build_body({"route": "no-action", "reason": "  NO_AVAILABILITY "}, "call-1")
    assert body == {"call_id": "call-1", "reason": "no_availability"}


def test_recorder_validates_at_record_time() -> None:
    recorder = ActionRecorder("call-1")
    queued = recorder.record(BOOK)
    assert queued.verb == "BOOK"
    assert len(recorder) == 1
    with pytest.raises(ValueError):
        recorder.record({"route": "book", "patient_id": "P1"})


def test_recorder_instances_are_independent() -> None:
    first = ActionRecorder("call-1")
    second = ActionRecorder("call-2")
    first.record(BOOK)
    first.record({"route": "no-action", "reason": "no_availability"})
    second.record(BOOK)
    assert len(first) == 2
    assert len(second) == 1
    assert first.actions[1].body["call_id"] == "call-1"
    assert second.actions[0].body["call_id"] == "call-2"
