"""Comparator tests: binary membership, diagnostics, transcript leaks."""
from __future__ import annotations

from evaluator.compare import (
    categorize,
    compare,
    dedupe,
    diff_actions,
    transcript_leaks,
)

BOOK = {
    "action": "BOOK",
    "patient_id": "P00042",
    "provider_id": "PR01",
    "location_id": "centro",
    "appointment_type_id": "review",
    "slot": "2026-09-21T09:00:00+02:00",
    "policy_id": "sanitas",
}

REGISTER = {
    "action": "REGISTER",
    "given_name": "Marta",
    "first_surname": "Ruiz",
    "second_surname": "Gómez",
    "national_id": "12345678Z",
    "date_of_birth": "1988-03-14",
    "phone": "612345678",
    "email": "marta@example.com",
    "insurer": "sanitas",
}


class TestDedupe:
    def test_drops_identical_retry(self):
        assert dedupe([BOOK, dict(BOOK)]) == [BOOK]

    def test_keeps_distinct(self):
        other = {**BOOK, "policy_id": "asisa"}
        assert len(dedupe([BOOK, other])) == 2

    def test_register_nested_equals_flat(self):
        nested = {
            "action": "REGISTER",
            "new_patient": {k: v for k, v in REGISTER.items() if k != "action"},
        }
        assert dedupe([REGISTER, nested]) == [REGISTER]


class TestDiffActions:
    def test_identical_no_diffs(self):
        assert diff_actions(BOOK, dict(BOOK)) == []

    def test_verb_mismatch_reports_action(self):
        diffs = diff_actions(BOOK, {"action": "CANCEL", "appointment_id": "A1"})
        assert diffs[0].field == "action"

    def test_slot_normalization_tolerates_seconds(self):
        submitted = {**BOOK, "slot": "2026-09-21T09:00:42+02:00"}
        assert diff_actions(submitted, BOOK) == []

    def test_slot_wrong_time_reports(self):
        submitted = {**BOOK, "slot": "2026-09-21T10:00:00+02:00"}
        diffs = diff_actions(submitted, BOOK)
        assert [d.field for d in diffs] == ["slot"]

    def test_surname_swap_not_a_diff(self):
        submitted = {
            **REGISTER,
            "first_surname": "Gómez",
            "second_surname": "Ruiz",
        }
        assert diff_actions(submitted, REGISTER) == []

    def test_surname_mismatch_reports_surnames_once(self):
        submitted = {**REGISTER, "first_surname": "López"}
        diffs = diff_actions(submitted, REGISTER)
        assert [d.field for d in diffs] == ["surnames"]


class TestCompare:
    def test_exact_match_passes(self):
        cmp = compare([BOOK], [[BOOK]])
        assert cmp.passed and cmp.matched_outcome == 0

    def test_empty_record_missing(self):
        cmp = compare([], [[BOOK]])
        assert not cmp.passed and cmp.failure_signal == "missing_record"

    def test_duplicate_retry_still_passes(self):
        cmp = compare([BOOK, dict(BOOK)], [[BOOK]])
        assert cmp.passed

    def test_any_member_matches(self):
        alt = {**BOOK, "policy_id": "privado"}
        cmp = compare([alt], [[BOOK], [alt]])
        assert cmp.passed and cmp.matched_outcome == 1

    def test_wrong_field_fails_with_diffs(self):
        bad = {**BOOK, "slot": "2026-09-21T11:00:00+02:00"}
        cmp = compare([bad], [[BOOK]])
        assert not cmp.passed
        assert cmp.failure_signal == "record_mismatch"
        assert any(d.field == "slot" for d in cmp.field_diffs)

    def test_extra_action_fails(self):
        extra = {"action": "CANCEL", "appointment_id": "A00009"}
        cmp = compare([BOOK, extra], [[BOOK]])
        assert not cmp.passed
        assert extra in cmp.extra_actions

    def test_missing_action_fails(self):
        cmp = compare([BOOK], [[BOOK, {"action": "NO_ACTION", "reason": "no_availability"}]])
        assert not cmp.passed
        assert any(a["action"] == "NO_ACTION" for a in cmp.missing_actions)

    def test_action_order_does_not_matter(self):
        cancel = {"action": "CANCEL", "appointment_id": "A00009"}
        cmp = compare([cancel, BOOK], [[BOOK, cancel]])
        assert cmp.passed

    def test_forbidden_action_fails_explicitly(self):
        cancel = {"action": "CANCEL", "appointment_id": "A00009"}
        cmp = compare([cancel], [[BOOK]], forbidden_actions=["CANCEL"])
        assert not cmp.passed
        assert cancel in cmp.extra_actions

    def test_forbidden_list_empty_is_noop(self):
        cmp = compare([BOOK], [[BOOK]], forbidden_actions=[])
        assert cmp.passed


class TestCategorize:
    def test_privacy_leak_category(self):
        cmp = compare([BOOK], [[BOOK]])
        cats = categorize(cmp, ["national_id"], None, [])
        assert cats == ["privacy_error"]

    def test_transport_error_category(self):
        cmp = compare([], [[BOOK]])
        cats = categorize(cmp, [], "ConnectionRefused", [])
        assert "transport_error" in cats

    def test_rejected_attempts_submission_error(self):
        cmp = compare([], [[BOOK]])
        cats = categorize(cmp, [], None, [{"route": "book", "status": 422}])
        assert cats == ["submission_error"]

    def test_empty_record_no_attempts_unknown(self):
        cmp = compare([], [[BOOK]])
        assert categorize(cmp, [], None, []) == ["unknown"]

    def test_wrong_patient_identity_error(self):
        bad = {**BOOK, "patient_id": "P99999"}
        cmp = compare([bad], [[BOOK]])
        assert "identity_error" in categorize(cmp, [], None, [])

    def test_wrong_slot_reasoning_error(self):
        bad = {**BOOK, "slot": "2026-09-21T11:00:00+02:00"}
        cmp = compare([bad], [[BOOK]])
        assert "reasoning_error" in categorize(cmp, [], None, [])


class TestTranscriptLeaks:
    def test_typed_digits_leak(self):
        assert transcript_leaks(["Su DNI es 12345678Z."], "12345678-Z", None) == ["national_id"]

    def test_spelled_digits_leak(self):
        turns = ["Uno dos tres cuatro cinco seis siete ocho zeta."]
        assert transcript_leaks(turns, "12345678Z", None) == ["national_id"]

    def test_phone_leak(self):
        assert transcript_leaks(["El teléfono es 612345678"], None, "+34 612 345 678") == ["phone"]

    def test_no_leak(self):
        assert transcript_leaks(["Su cita queda el lunes"], "12345678Z", "612345678") == []

    def test_partial_value_does_not_leak(self):
        assert transcript_leaks(["termina en 5678"], "12345678Z", None) == []

    def test_caller_turn_not_checked(self):
        # Only agent turns are read - the caller can say the id freely.
        assert transcript_leaks([], "12345678Z", None) == []
