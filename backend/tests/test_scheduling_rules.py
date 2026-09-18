"""Rules engine tests against a minimal catalogue shaped like the real one."""

from __future__ import annotations

from datetime import date

import pytest

from agent.clinic.models import ClinicCatalogue
from agent.scheduling.rules import Decision, RulesEngine, map_restriction


def make_catalogue() -> ClinicCatalogue:
    fixture = {
        "clinic_name": "Test Clinic",
        "calendar": {
            "starts": "2026-09-07",
            "ends": "2026-10-16",
            "max_span_days": 14,
            "slot_minutes": 15,
            "closure_days": ["2026-10-12"],
            "appointment_count": 0,
        },
        "restrictions": [],
        "providers": [
            {
                "id": "PR01",
                "name": "Dra. Iglesias",
                "specialty_id": "dermatologia",
                "languages": ["es", "en"],
                "refused_insurers": [{"id": "dkv", "name": "DKV"}],
                "accepted_insurers": [],
                "leave": {"start": "2026-09-14", "end": "2026-09-30", "reason": "sick"},
                "schedules": [],
            },
            {
                "id": "PR02",
                "name": "Dr. Vilar",
                "specialty_id": "dermatologia",
                "languages": ["es"],
                "accepted_insurers": [{"id": "dkv", "name": "DKV"}],
                "schedules": [],
            },
            {
                "id": "PR03",
                "name": "D. Alvaro Cid",
                "specialty_id": "fisioterapia",
                "languages": ["es", "ca"],
                "accepted_insurers": [],
                "schedules": [{"location_id": "sur", "location_name": "Sur", "days": []}],
            },
        ],
        "specialties": [
            {
                "id": "dermatologia",
                "name": "Dermatology",
                "referral_required": True,
                "covered_by": [],
                "not_covered_by": [],
            },
            {
                "id": "pediatria",
                "name": "Paediatrics",
                "min_age_months": 0,
                "max_age_months": 168,
                "covered_by": [],
                "not_covered_by": [],
            },
        ],
        "appointment_types": [],
        "locations": [
            {
                "id": "centro",
                "name": "Centro",
                "latitude": 40.4168,
                "longitude": -3.7038,
                "hours": [
                    {"weekday": "Monday", "intervals": ["09:00-14:00", "15:00-19:00"]},
                    {"weekday": "Friday", "intervals": ["09:00-14:00", "15:00-19:00"]},
                    {"weekday": "Saturday", "intervals": ["09:00-13:00"]},
                ],
            },
            {
                "id": "sur",
                "name": "Sur",
                "latitude": 40.34,
                "longitude": -3.74,
                "hours": [
                    {"weekday": "Monday", "intervals": []},
                    {"weekday": "Friday", "intervals": ["09:00-14:00"]},
                ],
            },
        ],
        "plans": [
            {
                "id": "adeslas",
                "name": "Adeslas",
                "uncovered_specialty_names": ["Gynaecology"],
                "covered_specialty_names": [],
                "covered_location_names": [],
                "uncovered_location_names": ["Norte"],
            },
            {"id": "sanitas", "name": "Sanitas"},
            {
                "id": "basic",
                "name": "Basic",
                "uncovered_specialty_names": ["Dermatology"],
            },
            {"id": "premium", "name": "Premium"},
        ],
    }
    return ClinicCatalogue.model_validate(fixture)


def make_engine() -> RulesEngine:
    return RulesEngine(make_catalogue())


PATIENT = {"patient_id": "P1", "date_of_birth": "1990-01-01", "insurer": "sanitas", "referrals": []}
FRIDAY = date(2026, 9, 18)


def test_referral_required() -> None:
    d = make_engine().evaluate(PATIENT, {"date": date(2026, 9, 16), "specialty_id": "dermatologia"})
    assert not d.allowed and d.reason == "referral_required"


def test_referral_satisfied_passes() -> None:
    patient = {**PATIENT, "referrals": ["derm-2026"]}
    d = make_engine().evaluate(patient, {"date": date(2026, 9, 16), "specialty_id": "dermatologia"})
    assert d.allowed


def test_age_boundary_paediatrics() -> None:
    adult = {**PATIENT, "date_of_birth": "2010-06-01"}  # > 14y in 2026
    d = make_engine().evaluate(adult, {"date": date(2026, 9, 16), "specialty_id": "pediatria"})
    assert not d.allowed and d.reason == "not_eligible_age"


def test_closure_day_fiesta_nacional() -> None:
    d = make_engine().evaluate(PATIENT, {"date": date(2026, 10, 12), "specialty_id": "pediatria"})
    assert not d.allowed and d.reason == "clinic_closed"


def test_sunday_is_closed() -> None:
    d = make_engine().evaluate(PATIENT, {"date": date(2026, 9, 20)})
    assert not d.allowed and d.reason == "clinic_closed"


def test_unknown_provider() -> None:
    d = make_engine().evaluate(PATIENT, {"date": FRIDAY, "provider_id": "PR99"})
    assert not d.allowed and d.reason == "provider_not_found"


def test_provider_on_leave_requena_window() -> None:
    d = make_engine().evaluate(PATIENT, {"date": date(2026, 9, 16), "provider_id": "PR01"})
    assert not d.allowed and d.reason == "provider_on_leave"


def test_leave_precedes_plan_refusal() -> None:
    d = make_engine().evaluate(
        {**PATIENT, "referrals": ["derm-2026"]},
        {
            "date": date(2026, 9, 16),
            "provider_id": "PR01",
            "plan_id": "dkv",
            "specialty_id": "dermatologia",
        },
    )
    assert not d.allowed and d.reason == "provider_on_leave"


def test_provider_refuses_plan_redirect() -> None:
    d = make_engine().evaluate(
        {**PATIENT, "referrals": ["derm-2026"]},
        {
            "date": date(2026, 10, 2),
            "provider_id": "PR01",
            "plan_id": "dkv",
            "specialty_id": "dermatologia",
        },
    )
    assert not d.allowed and d.reason == "provider_not_in_network"
    assert d.redirect_provider_id == "PR02"  # Vilar takes DKV


def test_plan_uncovered_location() -> None:
    d = make_engine().evaluate(
        PATIENT, {"date": date(2026, 9, 21), "location_id": "centro", "plan_id": "adeslas"}
    )
    # Centro is not in Adeslas' uncovered list, so allowed at location level.
    assert d.allowed


def test_location_closed_that_weekday() -> None:
    d = make_engine().evaluate(PATIENT, {"date": date(2026, 9, 21), "location_id": "sur"})
    assert not d.allowed and d.reason == "location_hours"


def test_friday_sur_hours_morning_only() -> None:
    catalogue = make_catalogue()
    engine = RulesEngine(catalogue)
    sur = next(location for location in catalogue.locations if location.id == "sur")
    assert engine.location_open_on(sur, FRIDAY)
    assert engine.location_open_part(sur, FRIDAY, "morning")
    assert not engine.location_open_part(sur, FRIDAY, "afternoon")

    morning = engine.evaluate(
        PATIENT, {"date": FRIDAY, "location_id": "sur", "part_of_day": "morning"}
    )
    assert morning.allowed
    afternoon = engine.evaluate(
        PATIENT, {"date": FRIDAY, "location_id": "sur", "part_of_day": "afternoon"}
    )
    assert not afternoon.allowed and afternoon.reason == "location_hours"


def test_saturday_sur_is_closed() -> None:
    d = make_engine().evaluate(PATIENT, {"date": date(2026, 9, 19), "location_id": "sur"})
    assert not d.allowed and d.reason == "location_hours"


def test_second_policy_covers_what_first_does_not() -> None:
    patient = {**PATIENT, "referrals": ["derm-2026"], "insurer": "basic"}
    first = make_engine().evaluate(
        patient, {"date": FRIDAY, "specialty_id": "dermatologia", "plan_id": "basic"}
    )
    assert not first.allowed and first.reason == "specialty_not_covered"
    second = make_engine().evaluate(
        patient, {"date": FRIDAY, "specialty_id": "dermatologia", "plan_id": "premium"}
    )
    assert second.allowed


def test_blocked_reason_preserved_over_computed() -> None:
    """The API's restriction outranks the locally computed referral."""
    d = make_engine().evaluate(
        PATIENT,  # no referrals, so the computed rule would say referral_required
        {"date": date(2026, 9, 16), "specialty_id": "dermatologia"},
        availability_blocked=[{"provider_id": "PR03", "restriction": "allowance_exhausted"}],
    )
    assert not d.allowed and d.reason == "allowance_exhausted"
    assert d.extra.get("restriction") == "allowance_exhausted"


def test_blocked_location_reason_not_mapped_to_specialty() -> None:
    d = make_engine().evaluate(
        PATIENT,
        {"date": FRIDAY},
        availability_blocked=[{"provider_id": "PR02", "restriction": "location_not_covered"}],
    )
    assert not d.allowed and d.reason == "location_not_covered"


def test_blocked_unknown_restriction_falls_through() -> None:
    d = make_engine().evaluate(
        PATIENT,
        {"date": date(2026, 9, 16), "specialty_id": "dermatologia"},
        availability_blocked=[{"provider_id": "PR01", "restriction": "brand_new_rule"}],
    )
    assert not d.allowed and d.reason == "referral_required"


def test_blocked_ignores_other_providers() -> None:
    d = make_engine().evaluate(
        {**PATIENT, "referrals": ["derm-2026"]},
        {"date": FRIDAY, "provider_id": "PR02", "specialty_id": "dermatologia", "plan_id": "dkv"},
        availability_blocked=[{"provider_id": "PR01", "restriction": "provider_on_leave"}],
    )
    assert d.allowed


def test_map_restriction_preserves_closed_reasons() -> None:
    assert map_restriction("provider_on_leave") == "provider_on_leave"
    assert map_restriction("insurer_referral_required") == "insurer_referral_required"
    assert map_restriction("location_not_covered") == "location_not_covered"
    assert map_restriction("specialty coverage") == "specialty_not_covered"
    assert map_restriction("mystery rule") is None


def test_decision_rejects_reason_outside_vocabulary() -> None:
    with pytest.raises(ValueError, match="closed vocabulary"):
        Decision(False, "made_up_reason")
