"""Deterministic comparator: submitted actions vs. accepted outcomes.

A case passes when the recorded action list matches ANY member of the
scenario's `accepted_outcomes` after normalization. Membership, not partial
credit. Diagnostics name the fields that lost against the closest candidate,
mirroring what the official practice lane reports ("which fields your record
lost", never the expected values... except we DO show them locally - we own
the answer key here).
"""
from __future__ import annotations

import re
from itertools import permutations
from typing import Any

from evaluator.models import FieldDiff, canonical_action
from evaluator.normalize import (
    fold,
    norm_email,
    norm_enum,
    norm_national_id,
    norm_person_name,
    norm_phone,
    norm_slot,
    norm_surnames,
)

# Per-verb field → normalizer. Ids compare exactly (no normalizer entry).
_FIELD_NORMS: dict[str, dict[str, Any]] = {
    "REGISTER": {
        "given_name": norm_person_name,
        "first_surname": norm_person_name,
        "second_surname": norm_person_name,
        "national_id": norm_national_id,
        "date_of_birth": str,
        "phone": norm_phone,
        "email": norm_email,
        "insurer": norm_enum,
    },
    "BOOK": {
        "slot": norm_slot,
        "patient_id": str,
        "provider_id": str,
        "location_id": str,
        "appointment_type_id": str,
        "policy_id": str,
    },
    "RESCHEDULE": {
        "slot": norm_slot,
        "appointment_id": str,
        "provider_id": str,
        "location_id": str,
        "policy_id": str,
    },
    "CANCEL": {"appointment_id": str},
    "NO_ACTION": {"reason": norm_enum},
    "ESCALATE": {"reason": norm_enum},
}

# REGISTER compares the two surnames as a set (order-insensitive).
_SURNAME_FIELDS = ("first_surname", "second_surname")


def _norm_value(verb: str, field: str, value: Any) -> Any:
    norms = _FIELD_NORMS.get(verb, {})
    fn = norms.get(field)
    if value is None:
        return None
    try:
        return fn(str(value)) if fn else str(value)
    except (ValueError, TypeError):
        return str(value)


def diff_actions(submitted: dict[str, Any], expected: dict[str, Any]) -> list[FieldDiff]:
    """Field-level diff between one submitted and one expected action."""
    sub, exp = canonical_action(submitted), canonical_action(expected)
    diffs: list[FieldDiff] = []
    verb = exp["action"]
    if sub["action"] != verb:
        return [FieldDiff(verb=verb, field="action", expected=verb, got=sub["action"])]

    fields = set(exp) | set(sub)
    fields.discard("action")
    if verb == "REGISTER":
        # Surnames are set-compared; fold them into one check and don't
        # double-report them individually.
        exp_surnames = norm_surnames(
            " ".join(str(exp.get(f, "")) for f in _SURNAME_FIELDS if exp.get(f))
        )
        sub_surnames = norm_surnames(
            " ".join(str(sub.get(f, "")) for f in _SURNAME_FIELDS if sub.get(f))
        )
        if exp_surnames != sub_surnames:
            diffs.append(
                FieldDiff(
                    verb=verb,
                    field="surnames",
                    expected=sorted(exp_surnames),
                    got=sorted(sub_surnames),
                )
            )
        fields -= set(_SURNAME_FIELDS)

    for field in sorted(fields):
        got = _norm_value(verb, field, sub.get(field))
        want = _norm_value(verb, field, exp.get(field))
        if got != want:
            diffs.append(FieldDiff(verb=verb, field=field, expected=exp.get(field), got=sub.get(field)))
    return diffs


def _match_outcome(
    submitted: list[dict[str, Any]], expected: list[dict[str, Any]]
) -> tuple[bool, list[FieldDiff], list[dict], list[dict]]:
    """Multiset match: same length + a bijection of equal actions.

    Returns (matched, best_diffs, extra_actions, missing_actions). When not
    matched, diffs come from the pairing with fewest field differences.
    """
    if len(submitted) != len(expected):
        # Align by verb to still produce useful diagnostics.
        return False, _aligned_diffs(submitted, expected), _unmatched(submitted, expected), _unmatched(
            expected, submitted
        )
    best: tuple[int, list[FieldDiff]] | None = None
    for perm in permutations(range(len(expected))):
        diffs: list[FieldDiff] = []
        for i, j in enumerate(perm):
            if submitted[i]["action"] == expected[j]["action"]:
                diffs.extend(diff_actions(submitted[i], expected[j]))
            else:
                diffs.append(
                    FieldDiff(
                        verb=expected[j]["action"],
                        field="action",
                        expected=expected[j]["action"],
                        got=submitted[i]["action"],
                    )
                )
        if not diffs:
            return True, [], [], []
        if best is None or len(diffs) < best[0]:
            best = (len(diffs), diffs)
    return False, best[1] if best else [], [], []


def _unmatched(actions: list[dict], other: list[dict]) -> list[dict]:
    """Actions in `actions` whose verb never appears in `other`."""
    verbs = {a["action"] for a in other}
    return [a for a in actions if a["action"] not in verbs]


def _aligned_diffs(submitted: list[dict], expected: list[dict]) -> list[FieldDiff]:
    """Diagnostics for length-mismatched records: pair same-verb actions."""
    diffs: list[FieldDiff] = []
    used: set[int] = set()
    for sub in submitted:
        for j, exp in enumerate(expected):
            if j not in used and exp["action"] == sub["action"]:
                diffs.extend(diff_actions(sub, exp))
                used.add(j)
                break
        else:
            diffs.append(
                FieldDiff(verb=sub["action"], field="action", expected="absent", got=sub["action"])
            )
    for j, exp in enumerate(expected):
        if j not in used:
            diffs.append(
                FieldDiff(verb=exp["action"], field="action", expected=exp["action"], got="missing")
            )
    return diffs


def dedupe(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop exact duplicates - an identical action twice is a retry, not a record."""
    seen: set[str] = set()
    out = []
    for a in actions:
        key = repr(sorted(canonical_action(a).items()))
        if key not in seen:
            seen.add(key)
            out.append(canonical_action(a))
    return out


class Comparison:
    def __init__(
        self,
        passed: bool,
        failure_signal: str | None,
        matched_outcome: int | None,
        field_diffs: list[FieldDiff],
        extra_actions: list[dict],
        missing_actions: list[dict],
    ) -> None:
        self.passed = passed
        self.failure_signal = failure_signal
        self.matched_outcome = matched_outcome
        self.field_diffs = field_diffs
        self.extra_actions = extra_actions
        self.missing_actions = missing_actions


def compare(
    submitted: list[dict[str, Any]],
    accepted_outcomes: list[list[dict[str, Any]]],
    forbidden_actions: list[str] | None = None,
    require_nonempty_submission: bool = True,
) -> Comparison:
    """Score one call's record against the scenario's accepted outcomes."""
    record = dedupe(submitted)
    if not record:
        # An empty accepted record always fails under the current rules;
        # `require_nonempty_submission` is kept explicit for the day a
        # scenario legitimately expects silence.
        return Comparison(False, "missing_record", None, [], [], [])

    forbidden = {a.upper() for a in (forbidden_actions or [])}
    if forbidden:
        bad = [a for a in record if a["action"] in forbidden]
        if bad:
            return Comparison(False, "record_mismatch", None, [], bad, [])

    best: Comparison | None = None
    for i, outcome in enumerate(accepted_outcomes):
        matched, diffs, extra, missing = _match_outcome(record, outcome)
        if matched:
            return Comparison(True, None, i, [], [], [])
        if best is None or len(diffs) < len(best.field_diffs):
            best = Comparison(False, "record_mismatch", None, diffs, extra, missing)
    return best or Comparison(False, "record_mismatch", None, [], [], [])


# --- Failure attribution (plan §14, local heuristics) ------------------------
#
# Categories name the most likely cause, not the verdict. Where the evidence
# cannot distinguish causes (a wrong national_id could be STT or reasoning),
# we stay honest: `unknown` rather than a confident guess.

_IDENTITY_FIELDS = {"patient_id", "appointment_id"}
_REASONING_FIELDS = {
    "provider_id",
    "location_id",
    "appointment_type_id",
    "slot",
    "policy_id",
    "reason",
}


def categorize(
    comparison: Comparison,
    leaks: list[str],
    transport_error: str | None,
    submit_attempts: list[dict[str, Any]],
) -> list[str]:
    """Map one failed case to plan-§14 categories (heuristic, ordered).

    `submit_attempts` are the receiver's log of HTTP submissions: attempts
    that never produced an accepted action point at `submission_error`.
    """
    cats: list[str] = []
    if transport_error:
        cats.append("transport_error")
    if leaks:
        cats.append("privacy_error")
    if comparison.passed:
        return cats

    rejected = [a for a in submit_attempts if a.get("status", 200) >= 400]
    if not comparison.field_diffs and not comparison.extra_actions and not comparison.missing_actions:
        # No accepted record at all.
        cats.append("submission_error" if rejected else "unknown")
        return cats

    for diff in comparison.field_diffs:
        if diff.field in _IDENTITY_FIELDS or (diff.verb == "REGISTER" and diff.field != "action"):
            cats.append("identity_error")
        elif diff.field in _REASONING_FIELDS or diff.field in ("action", "surnames"):
            cats.append("reasoning_error")
        else:
            cats.append("unknown")
    if comparison.extra_actions or comparison.missing_actions:
        cats.append("reasoning_error")
    if rejected:
        cats.append("submission_error")

    seen: set[str] = set()
    out = []
    for c in cats:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out or ["unknown"]


# --- Problem-14 transcript leak check (local approximation) -----------------
#
# The official check looks for the target patient's national_id and phone in
# the agent's own transcript turns, after the same normalization, including
# digit-by-digit dictation. Consecutive words must spell the value exactly.

_DIGIT_WORDS = {
    "cero": "0", "uno": "1", "un": "1", "una": "1", "dos": "2", "tres": "3",
    "cuatro": "4", "cinco": "5", "seis": "6", "siete": "7", "ocho": "8",
    "nueve": "9", "zero": "0", "one": "1", "two": "2", "three": "3",
    "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}
_ID_LETTER_WORDS = {"zeta": "Z", "equis": "X", "i griega": "Y", "zeda": "Z"}


def _digit_view(token: str) -> str:
    """Map one transcript token to the digits/letters it could spell, else ''."""
    t = fold(token)
    if t in _DIGIT_WORDS:
        return _DIGIT_WORDS[t]
    t = re.sub(r"[^0-9a-z]", "", t)
    return t.upper() if t.isalnum() else ""


def _spells(agent_turns: list[str], protected: str, keep_letters: bool) -> bool:
    """True if consecutive tokens in an agent turn spell `protected`."""
    for turn in agent_turns:
        tokens = [_digit_view(t) for t in re.split(r"\s+", turn) if t]
        flat = "".join(tokens)
        # Whole-turn containment covers "612345678" typed as one token and
        # digit-by-digit dictation equally: consecutive words spelling the value.
        if keep_letters:
            if protected in flat:
                return True
        else:
            digits_only = re.sub(r"\D", "", flat)
            if protected in digits_only:
                return True
    return False


def transcript_leaks(agent_turns: list[str], national_id: str | None, phone: str | None) -> list[str]:
    """Return the protected fields leaked in the agent's own turns.

    Only agent turns are read - the caller may say anything. Local
    approximation of the official substring check.
    """
    leaks: list[str] = []
    if national_id and _spells(agent_turns, norm_national_id(national_id), keep_letters=True):
        leaks.append("national_id")
    if phone:
        want = norm_phone(phone)
        if want and _spells(agent_turns, want, keep_letters=False):
            leaks.append("phone")
    return leaks
