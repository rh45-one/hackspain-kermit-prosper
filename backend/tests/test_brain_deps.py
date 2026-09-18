"""Offline tests for brain.deps: national-id gate and language normalization."""
from __future__ import annotations

from agent.brain.deps import CLOSED_REASONS, normalize_language, validate_national_id


def test_validate_national_id_accepts_valid_dni():
    ok, normalized = validate_national_id("12345678Z")
    assert ok and normalized == "12345678Z"


def test_validate_national_id_accepts_spaced_nie():
    ok, normalized = validate_national_id("x-1234567-l")
    assert ok and normalized == "X1234567L"


def test_validate_national_id_never_raises_on_bad_letter():
    ok, normalized = validate_national_id("12345678K")
    assert ok is False
    assert normalized == ""


def test_validate_national_id_never_raises_on_bad_shape():
    ok, normalized = validate_national_id("hello")
    assert ok is False and normalized == ""
    ok, normalized = validate_national_id("")
    assert ok is False and normalized == ""


def test_closed_reasons_match_the_contract_vocabulary():
    # The eleven clinic rules plus the seven non-rule endings.
    assert len(CLOSED_REASONS) == 18
    for reason in (
        "not_eligible_age",
        "referral_required",
        "provider_not_in_network",
        "specialty_not_covered",
        "location_not_covered",
        "insurer_referral_required",
        "allowance_exhausted",
        "provider_on_leave",
        "location_hours",
        "type_not_offered",
        "patient_history",
        "no_availability",
        "clinic_closed",
        "patient_not_found",
        "provider_not_found",
        "caller_not_authorised",
        "out_of_scope",
        "medical_emergency",
    ):
        assert reason in CLOSED_REASONS


def test_normalize_language_names_and_codes():
    assert normalize_language("catalán") == "ca"
    assert normalize_language("Catalan") == "ca"
    assert normalize_language("español") == "es"
    assert normalize_language("Spanish") == "es"
    assert normalize_language("ca") == "ca"
    assert normalize_language(None) is None
    assert normalize_language("") is None
