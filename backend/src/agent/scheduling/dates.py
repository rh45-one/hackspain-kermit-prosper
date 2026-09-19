"""Deterministic resolution of relative dates (problem 5's fixed vocabulary).

The LLM never does date math. Every phrase resolves against the moment the
call connects, in Europe/Madrid, and a weekday phrase means the first such
weekday *strictly after* the day of the call.

This module owns **calendar** rollovers only: Sundays, when nothing in the
network opens, and the one published closure day, Monday 12 October 2026
(Fiesta Nacional). It deliberately knows nothing about site opening hours --
Sur shutting on Friday afternoon, or only Centro opening on a Saturday, comes
from the catalogue's ``location.hours`` and is applied by the rules engine and
by which slots availability returns. Inventing those hours here would make the
resolver disagree with the clinic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
    "lunes": 0,
    "martes": 1,
    "miércoles": 2,
    "miercoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sábado": 5,
    "sabado": 5,
    "domingo": 6,
}

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_ORDINALS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
    "thirteenth": 13,
    "fourteenth": 14,
    "fifteenth": 15,
    "sixteenth": 16,
    "seventeenth": 17,
    "eighteenth": 18,
    "nineteenth": 19,
    "twentieth": 20,
    "twenty-first": 21,
    "twenty-second": 22,
    "twenty-third": 23,
    "twenty-fourth": 24,
    "twenty-fifth": 25,
    "twenty-sixth": 26,
    "twenty-seventh": 27,
    "twenty-eighth": 28,
    "twenty-ninth": 29,
    "thirtieth": 30,
    "thirty-first": 31,
}

# Fixed problem-5 phrases and their day offset from the day of the call.
_FIXED_OFFSETS = {
    "tomorrow": 1,
    "mañana": 1,
    "the day after tomorrow": 2,
    "pasado mañana": 2,
    "a week from today": 7,
    "in a week": 7,
    "next week": 7,
    "in a fortnight": 14,
    "a fortnight from now": 14,
    "in two weeks": 14,
}

_ORDINAL_SUFFIX = re.compile(r"^(\d+)(?:st|nd|rd|th)$")


class InvalidAppointmentDate(ValueError):
    pass


@dataclass
class Resolution:
    """A resolved date plus the part of day the caller asked for."""

    date: date
    part_of_day: str | None = None  # 'morning' | 'afternoon' | None
    phrase: str = ""
    rolled_from: date | None = None

    @property
    def date_iso(self) -> str:
        return self.date.isoformat()


class MadridDateResolver:
    """Resolve the fixed vocabulary of When Exactly (problem 5)."""

    def __init__(self, closure_days: set[date] | None = None) -> None:
        # Monday 12 October 2026, Fiesta Nacional: the one published closure.
        if closure_days is None:
            closure_days = {date(2026, 10, 12)}
        self.closure_days = frozenset(closure_days)

    # ---- calendar --------------------------------------------------------
    def is_open_day(self, day: date) -> bool:
        """True when the network is open: not a Sunday and not a closure day."""
        return day.weekday() != 6 and day not in self.closure_days

    def next_open_day(self, day: date) -> date:
        """First open day on or after ``day``."""
        while not self.is_open_day(day):
            day += timedelta(days=1)
        return day

    def next_open_after(self, day: date) -> date:
        """First open day strictly after ``day``."""
        return self.next_open_day(day + timedelta(days=1))

    # ---- resolution ------------------------------------------------------
    def resolve_relative(self, phrase: str, now: datetime | None = None) -> Resolution:
        """Resolve a caller phrase against the call-connect moment."""
        now = now or datetime.now(MADRID)
        today = _as_madrid(now).date()
        low = _normalize(phrase)
        part = _part_of_day(low)
        date_phrase = " ".join(re.sub(
            r"\b(?:in the morning|in the afternoon|morning|afternoon|first thing|"
            r"por la mañana|por la tarde)\b", "", low,
        ).split())

        offset = _FIXED_OFFSETS.get(date_phrase)
        if offset is not None:
            return self._resolution(today + timedelta(days=offset), part, phrase)

        iso = re.fullmatch(r"(?:on |el )?(\d{4}-\d{2}-\d{2})", date_phrase)
        try:
            explicit = date.fromisoformat(iso[1]) if iso else self._parse_explicit(low, today)
        except ValueError as exc:
            raise InvalidAppointmentDate(str(exc)) from exc
        if explicit is not None:
            result = self._resolution(explicit, part, phrase)
            if result.date <= today:
                raise InvalidAppointmentDate("appointments must be after the day of the call")
            return result

        weekday = _find_weekday(low)
        if weekday is not None:
            offset = (weekday - today.weekday()) % 7
            if offset == 0:
                offset = 7  # strictly after the day of the call
            return self._resolution(today + timedelta(days=offset), part, phrase)

        raise ValueError(f"unresolvable when phrase: {phrase!r}")

    # ---- helpers ---------------------------------------------------------
    def _resolution(self, day: date, part: str | None, phrase: str) -> Resolution:
        rolled = self.next_open_day(day)
        return Resolution(
            date=rolled,
            part_of_day=part,
            phrase=phrase,
            rolled_from=day if rolled != day else None,
        )

    def _parse_explicit(self, low: str, today: date) -> date | None:
        tokens = [raw.strip(",.") for raw in low.split()]
        month_index = next((index for index, token in enumerate(tokens) if token in _MONTHS), None)
        if month_index is None:
            return None
        month_num = _MONTHS[tokens[month_index]]
        day_num = None
        # The day is the token before the month, optionally with "of" between;
        # anything further back ("first thing", "this coming") is not a day.
        for index in range(max(0, month_index - 2), month_index):
            number = _ordinal(tokens[index])
            if number is not None and 1 <= number <= 31:
                day_num = number
                break
        if day_num is None and month_index + 1 < len(tokens):
            number = _ordinal(tokens[month_index + 1])
            if number is not None and 1 <= number <= 31:
                day_num = number
        if day_num is None:
            return None
        year = next((int(token) for token in tokens if re.fullmatch(r"\d{4}", token)), None)
        candidate = _safe_date(today.year if year is None else year, month_num, day_num)
        if candidate is None:
            raise ValueError(f"invalid calendar date: {low!r}")
        if candidate < today and year is None:
            candidate = _safe_date(today.year + 1, month_num, day_num)
        return candidate


def _as_madrid(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=MADRID)
    return moment.astimezone(MADRID)


def _normalize(phrase: str) -> str:
    text = " ".join(str(phrase or "").lower().replace(",", " ").split())
    return text.strip(" .;")


def _part_of_day(low: str) -> str | None:
    if "afternoon" in low or "tarde" in low:
        return "afternoon"
    if "morning" in low or "first thing" in low or "por la mañana" in low:
        return "morning"
    return None


def _find_weekday(low: str) -> int | None:
    for raw in low.split():
        token = raw.strip(",.")
        if token in WEEKDAYS:
            return WEEKDAYS[token]
    return None


def _ordinal(token: str) -> int | None:
    token = token.strip().rstrip(",.")
    if token.isdigit():
        return int(token)
    match = _ORDINAL_SUFFIX.match(token)
    if match:
        return int(match.group(1))
    return _ORDINALS.get(token)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None
