"""Rules engine: which requests the clinic can accept, and why not.

Input is the warmed catalogue (``ClinicCatalogue``) plus the patient and the
requested date/provider/specialty/site/plan. Output is a :class:`Decision`
whose ``reason`` always comes from the closed vocabulary in
:data:`CLOSED_REASONS`, so it maps 1:1 onto the submission API.

Precedence, most authoritative first:

1. an id that is not in the catalogue (``provider_not_found``);
2. a network-wide closure (Sunday or a published closure day);
3. the availability response's own ``blocked`` metadata, preserved verbatim --
   the API is ground truth about which standing rule stopped a provider;
4. age window;
5. provider leave;
6. provider refuses the plan (with a redirect when another provider can take
   it);
7. a specialty that requires a referral;
8. plan specialty coverage;
9. plan site coverage;
10. site opening hours, including the requested part of day.

Site hours are read from the catalogue (``location.hours``); nothing here
invents them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

MORNING_END_MINUTES = 14 * 60

CLOSED_REASONS = frozenset(
    {
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
    }
)

# Substring aliases for the clinic's own restriction kinds. Exact matches
# against CLOSED_REASONS win before this table is consulted, and the table is
# ordered so that `location_not_covered` cannot be swallowed by a generic
# "not_covered" needle.
_RESTRICTION_ALIASES: tuple[tuple[str, str], ...] = (
    ("insurer_referral", "insurer_referral_required"),
    ("location", "location_not_covered"),
    ("specialty", "specialty_not_covered"),
    ("coverage", "specialty_not_covered"),
    ("not_covered", "specialty_not_covered"),
    ("network", "provider_not_in_network"),
    ("allowance", "allowance_exhausted"),
    ("exhausted", "allowance_exhausted"),
    ("leave", "provider_on_leave"),
    ("hour", "location_hours"),
    ("closed", "location_hours"),
    ("type", "type_not_offered"),
    ("history", "patient_history"),
    ("age", "not_eligible_age"),
    ("referral", "referral_required"),
)


def map_restriction(restriction: str | None) -> str | None:
    """Map an availability ``blocked.restriction`` onto the closed vocabulary.

    An exact closed reason is preserved unchanged. Unknown text returns
    ``None`` so the caller falls through to the computed rules instead of
    silently allowing a blocked request.
    """
    text = str(restriction or "").strip().lower()
    if not text:
        return None
    if text in CLOSED_REASONS:
        return text
    for needle, reason in _RESTRICTION_ALIASES:
        if needle in text:
            return reason
    return None


@dataclass
class Decision:
    allowed: bool
    reason: str | None = None
    detail: str = ""
    redirect_provider_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.reason is not None and self.reason not in CLOSED_REASONS:
            raise ValueError(f"reason {self.reason!r} outside closed vocabulary")


class RulesEngine:
    def __init__(self, catalogue: Any) -> None:
        self.catalogue = catalogue
        self._specialties = {s.id: s for s in catalogue.specialties}
        self._providers = {p.id: p for p in catalogue.providers}
        self._locations = {l.id: l for l in catalogue.locations}
        self._plans = {p.id: p for p in catalogue.plans}

    # ---- entry point -----------------------------------------------------
    def evaluate(
        self,
        patient: dict[str, Any],
        request: dict[str, Any],
        availability_blocked: list[dict[str, Any]] | None = None,
    ) -> Decision:
        """Decide whether ``request`` is allowed.

        ``request`` keys: ``date`` (required), ``specialty_id``?,
        ``provider_id``?, ``location_id``?, ``plan_id``?, ``part_of_day``?
        (``morning`` / ``afternoon``).
        """
        on_date: date = request["date"]
        specialty_id = request.get("specialty_id")
        provider_id = request.get("provider_id")
        location_id = request.get("location_id")
        part = (request.get("part_of_day") or "").strip().lower() or None
        plan_id = str(request.get("plan_id") or patient.get("insurer") or "").strip()

        specialty = self._specialties.get(specialty_id) if specialty_id else None
        provider = self._providers.get(provider_id) if provider_id else None
        location = self._locations.get(location_id) if location_id else None
        plan = self._plans.get(plan_id) if plan_id else None

        # 1. Ids the catalogue does not know are a bug, not a clinic rule.
        if provider_id and provider is None:
            return Decision(False, "provider_not_found", str(provider_id))

        # 2. Network-wide closure.
        if not self.is_open_day(on_date):
            return Decision(False, "clinic_closed", f"{on_date} is a clinic-wide closure")

        # 3. Availability metadata is authoritative: preserve what it said.
        blocked = self._blocked_decision(provider_id, availability_blocked)
        if blocked is not None:
            return blocked

        # 4. Age window.
        if specialty is not None:
            born = _parse_date(patient.get("date_of_birth", ""))
            if born is not None:
                age_months = _months_between(born, on_date)
                if age_months < specialty.min_age_months:
                    return Decision(
                        False,
                        "not_eligible_age",
                        f"{specialty.name} starts at {specialty.min_age_months} months",
                    )
                if specialty.max_age_months is not None and age_months > specialty.max_age_months:
                    return Decision(
                        False,
                        "not_eligible_age",
                        f"{specialty.name} ends at {specialty.max_age_months} months",
                    )

        # 5. Provider leave.
        if provider is not None and self._on_leave(provider, on_date):
            return Decision(False, "provider_on_leave", provider.name)

        # 6. Provider refuses the plan.
        if provider is not None and plan_id:
            refused = {r.id for r in provider.refused_insurers}
            accepted = {a.id for a in provider.accepted_insurers}
            if plan_id in refused or (accepted and plan_id not in accepted):
                redirect = self._find_provider_taking_plan(
                    provider.specialty_id,
                    plan_id,
                    location_id,
                    on_date,
                    exclude=provider.id,
                )
                return Decision(
                    False,
                    "provider_not_in_network",
                    f"{provider.name} does not take {plan_id}",
                    redirect_provider_id=redirect,
                )

        # 7. Specialty referral.
        if specialty is not None and specialty.referral_required and not patient.get("referrals"):
            return Decision(False, "referral_required", specialty.name)

        # 8. Plan specialty coverage.
        if plan is not None and specialty is not None:
            name = specialty.name
            if name in plan.uncovered_specialty_names:
                return Decision(
                    False, "specialty_not_covered", f"{plan.name} does not cover {name}"
                )
            if plan.covered_specialty_names and name not in plan.covered_specialty_names:
                return Decision(
                    False,
                    "specialty_not_covered",
                    f"{plan.name} covers only {plan.covered_specialty_names}",
                )

        # 9. Plan site coverage.
        if plan is not None and location is not None:
            name = location.name
            if name in plan.uncovered_location_names:
                return Decision(False, "location_not_covered", f"{plan.name} does not cover {name}")
            if plan.covered_location_names and name not in plan.covered_location_names:
                return Decision(
                    False,
                    "location_not_covered",
                    f"{plan.name} covers only {plan.covered_location_names}",
                )

        # 10. Site opening hours for the requested weekday and part of day.
        if location is not None:
            intervals = self._intervals_for(location, on_date)
            if not intervals:
                return Decision(
                    False, "location_hours", f"{location.name} is closed on {on_date:%A}"
                )
            if part in ("morning", "afternoon") and not _covers_part(intervals, part):
                return Decision(
                    False,
                    "location_hours",
                    f"{location.name} has no {part} slots on {on_date:%A}",
                )

        return Decision(True)

    # ---- calendar --------------------------------------------------------
    def is_open_day(self, day: date) -> bool:
        if day.weekday() == 6:
            return False
        closures = getattr(getattr(self.catalogue, "calendar", None), "closure_days", []) or []
        return all(str(day) != str(closure)[:10] for closure in closures)

    def location_open_on(self, location: Any, on_date: date) -> bool:
        """True when ``location`` has any hours on ``on_date``'s weekday."""
        return bool(self._intervals_for(location, on_date))

    def location_open_part(self, location: Any, on_date: date, part: str) -> bool:
        """True when ``location`` has hours overlapping ``part`` on ``on_date``."""
        return _covers_part(self._intervals_for(location, on_date), part)

    # ---- helpers ---------------------------------------------------------
    def _intervals_for(self, location: Any, on_date: date) -> list[str]:
        weekday_name = on_date.strftime("%A").lower()
        for day in getattr(location, "hours", []) or []:
            if str(day.weekday).lower() == weekday_name:
                return [str(interval) for interval in (day.intervals or [])]
        return []

    def _blocked_decision(
        self,
        provider_id: str | None,
        availability_blocked: list[dict[str, Any]] | None,
    ) -> Decision | None:
        reasons: list[tuple[str, str, str]] = []
        for blocked in availability_blocked or []:
            blocked_provider = str(blocked.get("provider_id", ""))
            if provider_id and blocked_provider and blocked_provider != provider_id:
                continue
            raw = str(blocked.get("restriction", ""))
            reason = map_restriction(raw)
            if reason is None:
                continue
            reasons.append((blocked_provider, reason, raw))
        if not reasons:
            return None
        reasons.sort(key=lambda item: (item[0], item[1], item[2]))
        _, reason, raw = reasons[0]
        return Decision(False, reason, f"availability blocked: {raw}", extra={"restriction": raw})

    def _on_leave(self, provider: Any, on_date: date) -> bool:
        leave = getattr(provider, "leave", None)
        if leave is None:
            return False
        start = _parse_date(getattr(leave, "start", ""))
        end = _parse_date(getattr(leave, "end", ""))
        return start is not None and end is not None and start <= on_date <= end

    def _find_provider_taking_plan(
        self,
        specialty_id: str,
        plan_id: str,
        location_id: str | None,
        on_date: date,
        *,
        exclude: str | None = None,
    ) -> str | None:
        for provider in self._providers.values():
            if provider.id == exclude or provider.specialty_id != specialty_id:
                continue
            if self._on_leave(provider, on_date):
                continue
            accepted = {a.id for a in provider.accepted_insurers}
            refused = {r.id for r in provider.refused_insurers}
            if plan_id in refused:
                continue
            if accepted and plan_id not in accepted:
                continue
            if location_id and provider_sits_at(provider, location_id) is False:
                continue
            return provider.id
        return None


def provider_sits_at(provider: Any, location_id: str) -> bool | None:
    """Whether ``provider`` works at ``location_id``; None when unknown."""
    schedules = getattr(provider, "schedules", []) or []
    if not schedules:
        return None
    return any(s.location_id == location_id for s in schedules)


def _months_between(born: date, on: date) -> int:
    months = (on.year - born.year) * 12 + (on.month - born.month)
    if on.day < born.day:
        months -= 1
    return months


def _interval_minutes(raw: str) -> tuple[int, int] | None:
    text = str(raw).strip()
    try:
        start, end = text.split("-", 1)
        start_h, start_m = (int(part) for part in start.split(":", 1))
        end_h, end_m = (int(part) for part in end.split(":", 1))
    except (TypeError, ValueError):
        return None
    return start_h * 60 + start_m, end_h * 60 + end_m


def _covers_part(intervals: list[str], part: str) -> bool:
    if part not in ("morning", "afternoon"):
        return bool(intervals)
    window = (0, MORNING_END_MINUTES) if part == "morning" else (MORNING_END_MINUTES, 24 * 60)
    for raw in intervals:
        minutes = _interval_minutes(raw)
        if minutes is None:
            continue
        start, end = minutes
        if start < window[1] and end > window[0]:
            return True
    return False


def _parse_date(raw: Any) -> date | None:
    if raw is None:
        return None
    text = str(raw).strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None
