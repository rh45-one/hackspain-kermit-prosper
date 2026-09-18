"""Deterministic slot selection for the Prosper scheduling core.

The availability endpoint is authoritative about *which* slots exist. This
module only ranks the slots the API returned, and it never invents an id or
a timestamp: the selected match keeps the API's own mapping field-for-field,
so ``provider_id``, ``location_id``, ``appointment_type_id`` and the ISO
``start_time`` string are submitted verbatim.

Rules implemented here:
  * nothing on the day of the call is eligible ("earliest from tomorrow");
  * every comparison happens in Europe/Madrid, whatever offset the API used;
  * optional provider / site / specialty / part-of-day / language filters;
  * earliest start first;
  * ties broken deterministically by load spreading: among providers free at
    the same minute, the one with more free slots in the searched window is
    preferred (the busiest diary is never picked first), then provider id and
    location id break any remaining tie.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")
MORNING_END_HOUR = 14  # "morning" is before 14:00, "afternoon" is from 14:00


def parse_start_time(raw: str | None) -> datetime | None:
    """Parse an availability ``start_time`` into an aware Europe/Madrid instant.

    A trailing ``Z`` is accepted; a naive value is read as Madrid wall time
    because the clinic only ever speaks Madrid. Returns ``None`` when the
    value is not a parseable ISO timestamp.
    """
    if not raw:
        return None
    text = str(raw).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MADRID)
    return parsed.astimezone(MADRID)


def madrid(moment: datetime) -> datetime:
    """Return ``moment`` as an aware Europe/Madrid datetime."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=MADRID)
    return moment.astimezone(MADRID)


def classify_part_of_day(start: datetime, *, morning_end_hour: int = MORNING_END_HOUR) -> str:
    """Return ``morning`` or ``afternoon`` for a Madrid start instant."""
    return "morning" if start.astimezone(MADRID).hour < morning_end_hour else "afternoon"


@dataclass(frozen=True)
class SlotMatch:
    """One eligible slot, preserving the API object verbatim."""

    slot: dict[str, Any]
    start: datetime
    free_slots: int

    @property
    def provider_id(self) -> str:
        return str(self.slot.get("provider_id", ""))

    @property
    def location_id(self) -> str:
        return str(self.slot.get("location_id", ""))

    @property
    def start_time(self) -> str:
        return str(self.slot.get("start_time", ""))


@dataclass
class SlotSelection:
    """Ranked result of a :meth:`SlotMatcher.select` call."""

    matches: list[SlotMatch] = field(default_factory=list)
    rejected: dict[str, int] = field(default_factory=dict)
    considered: int = 0

    @property
    def best(self) -> SlotMatch | None:
        return self.matches[0] if self.matches else None

    def best_slot(self) -> dict[str, Any] | None:
        """The chosen slot exactly as the API returned it."""
        match = self.best
        return match.slot if match is not None else None

    def slots(self) -> list[dict[str, Any]]:
        return [match.slot for match in self.matches]

    def reject(self, reason: str) -> None:
        self.rejected[reason] = self.rejected.get(reason, 0) + 1


class SlotMatcher:
    """Rank availability slots: earliest first, deterministic load spreading.

    ``languages_by_provider`` maps a provider id to the languages that
    provider speaks. It is optional; the language filter only applies when a
    language is requested *and* a map was supplied.
    """

    def __init__(
        self,
        languages_by_provider: Mapping[str, Iterable[str]] | None = None,
        *,
        morning_end_hour: int = MORNING_END_HOUR,
    ) -> None:
        self.morning_end_hour = morning_end_hour
        self._languages: dict[str, set[str]] = {
            str(provider_id): {str(lang).lower() for lang in langs}
            for provider_id, langs in (languages_by_provider or {}).items()
        }

    # ---- selection -------------------------------------------------------
    def select(
        self,
        slots: Sequence[dict[str, Any]],
        now: datetime,
        *,
        on_date: date | None = None,
        provider_id: str | None = None,
        location_id: str | None = None,
        specialty_id: str | None = None,
        part_of_day: str | None = None,
        language: str | None = None,
        exclude_same_day: bool = True,
        max_results: int | None = None,
    ) -> SlotSelection:
        """Filter and rank ``slots`` for a call that connected at ``now``.

        ``on_date`` (when given) keeps only slots on that Madrid calendar day.
        ``part_of_day`` accepts ``morning`` or ``afternoon``.
        """
        now_madrid = madrid(now)
        today = now_madrid.date()
        wanted_part = (part_of_day or "").strip().lower() or None
        wanted_language = (language or "").strip().lower() or None
        free_slots = self._free_counts(slots)
        selection = SlotSelection(considered=len(slots))

        candidates: list[SlotMatch] = []
        for slot in slots:
            start = parse_start_time(slot.get("start_time"))
            if start is None:
                selection.reject("unparseable_time")
                continue
            if exclude_same_day and start.date() <= today:
                selection.reject("same_day")
                continue
            if on_date is not None and start.date() != on_date:
                selection.reject("off_date")
                continue
            if provider_id and str(slot.get("provider_id", "")) != provider_id:
                selection.reject("provider")
                continue
            if location_id and str(slot.get("location_id", "")) != location_id:
                selection.reject("location")
                continue
            if specialty_id and str(slot.get("specialty_id", "")) != specialty_id:
                selection.reject("specialty")
                continue
            if wanted_part in ("morning", "afternoon") and (
                classify_part_of_day(start, morning_end_hour=self.morning_end_hour) != wanted_part
            ):
                selection.reject("part_of_day")
                continue
            slot_provider = str(slot.get("provider_id", ""))
            if wanted_language and not self._speaks(slot_provider, wanted_language):
                selection.reject("language")
                continue
            candidates.append(
                SlotMatch(slot=slot, start=start, free_slots=free_slots.get(slot_provider, 0))
            )

        candidates.sort(
            key=lambda match: (
                match.start,
                -match.free_slots,  # less busy first among providers tied on time
                match.provider_id,
                match.location_id,
                match.start_time,
            )
        )
        selection.matches = candidates[:max_results] if max_results is not None else candidates
        return selection

    def select_from_availability(
        self,
        availability: Mapping[str, Any],
        now: datetime,
        **kwargs: Any,
    ) -> SlotSelection:
        """Convenience wrapper over an ``AvailabilityResponse`` mapping."""
        slots = availability.get("slots") or []
        return self.select(slots, now, **kwargs)

    # ---- helpers ---------------------------------------------------------
    def _free_counts(self, slots: Sequence[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for slot in slots:
            provider = str(slot.get("provider_id", ""))
            counts[provider] = counts.get(provider, 0) + 1
        return counts

    def _speaks(self, provider_id: str, language: str) -> bool:
        if not self._languages:
            return True  # no catalogue map supplied: cannot filter, do not drop
        return language in self._languages.get(provider_id, set())
