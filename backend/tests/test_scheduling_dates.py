"""Date resolver tests: fixed problem-5 vocabulary, Sundays, Fiesta Nacional."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from agent.scheduling.dates import MadridDateResolver

MADRID = ZoneInfo("Europe/Madrid")


def dt(y: int, m: int, d: int, hh: int = 10) -> datetime:
    return datetime(y, m, d, hh, 0, tzinfo=MADRID)


@pytest.fixture
def resolver() -> MadridDateResolver:
    return MadridDateResolver()  # closure: Mon 12 Oct 2026 baked in


def test_tomorrow(resolver: MadridDateResolver) -> None:
    assert resolver.resolve_relative("tomorrow", dt(2026, 9, 18)).date.isoformat() == "2026-09-19"


def test_day_after_tomorrow_rolls_past_sunday(resolver: MadridDateResolver) -> None:
    """Fri 18 + 2 = Sun 20 Sep; nothing opens on a Sunday, so Monday 21."""
    res = resolver.resolve_relative("the day after tomorrow", dt(2026, 9, 18))
    assert res.date.isoformat() == "2026-09-21"
    assert res.rolled_from == date(2026, 9, 20)


def test_tomorrow_from_saturday_rolls_to_monday(resolver: MadridDateResolver) -> None:
    res = resolver.resolve_relative("tomorrow", dt(2026, 9, 19))  # Saturday
    assert res.date.isoformat() == "2026-09-21"


def test_day_after_tomorrow_chains_sunday_and_fiesta(resolver: MadridDateResolver) -> None:
    """Fri 9 Oct + 2 = Sun 11 -> Mon 12 closure -> Tue 13."""
    res = resolver.resolve_relative("the day after tomorrow", dt(2026, 10, 9))
    assert res.date.isoformat() == "2026-10-13"


def test_a_week_and_fortnight(resolver: MadridDateResolver) -> None:
    assert resolver.resolve_relative("a week from today", dt(2026, 9, 18)).date.day == 25
    fortnight = resolver.resolve_relative("in a fortnight", dt(2026, 9, 18)).date
    assert (fortnight.day, fortnight.month) == (2, 10)


def test_first_thing_monday_skips_fiesta_nacional(resolver: MadridDateResolver) -> None:
    """Said Friday 9 Oct: 'first thing Monday' must land Tuesday 13 Oct."""
    res = resolver.resolve_relative("first thing Monday", dt(2026, 10, 9))
    assert res.date.isoformat() == "2026-10-13"
    assert res.part_of_day == "morning"


def test_explicit_fiesta_date_rolls_forward(resolver: MadridDateResolver) -> None:
    res = resolver.resolve_relative("first thing on Monday the twelfth of October", dt(2026, 10, 9))
    assert res.date.isoformat() == "2026-10-13"
    assert res.part_of_day == "morning"


def test_explicit_date_wins_on_the_closure_day_itself(resolver: MadridDateResolver) -> None:
    """On Mon 12 Oct the phrase names today; a weekday-only parse would say 19 Oct."""
    res = resolver.resolve_relative(
        "first thing on Monday the twelfth of October", dt(2026, 10, 12)
    )
    assert res.date.isoformat() == "2026-10-13"


def test_explicit_numeric_date(resolver: MadridDateResolver) -> None:
    res = resolver.resolve_relative("12 October", dt(2026, 9, 18))
    assert res.date.isoformat() == "2026-10-13"  # 12 Oct is the closure


def test_this_coming_thursday_said_on_thursday(resolver: MadridDateResolver) -> None:
    res = resolver.resolve_relative("this coming Thursday", dt(2026, 9, 24))
    assert (res.date.day, res.date.month) == (1, 10)


def test_saturday_morning_part_of_day(resolver: MadridDateResolver) -> None:
    res = resolver.resolve_relative("on Saturday morning", dt(2026, 9, 18))
    assert res.date.weekday() == 5
    assert res.part_of_day == "morning"


def test_weekday_afternoon(resolver: MadridDateResolver) -> None:
    res = resolver.resolve_relative("Tuesday afternoon", dt(2026, 9, 18))
    assert res.date.weekday() == 1
    assert res.part_of_day == "afternoon"


def test_plain_phrase_has_no_part_of_day(resolver: MadridDateResolver) -> None:
    assert resolver.resolve_relative("tomorrow", dt(2026, 9, 18)).part_of_day is None


def test_resolver_does_not_invent_site_hours(resolver: MadridDateResolver) -> None:
    """Friday and Saturday are returned as asked; site hours are not resolved here."""
    friday = resolver.resolve_relative("Friday afternoon", dt(2026, 9, 17))
    assert friday.date.isoformat() == "2026-09-18"
    assert friday.part_of_day == "afternoon"
    saturday = resolver.resolve_relative("Saturday morning", dt(2026, 9, 18))
    assert saturday.date.isoformat() == "2026-09-19"


def test_never_returns_today(resolver: MadridDateResolver) -> None:
    for phrase in ("tomorrow", "this coming Friday", "a week from today"):
        assert resolver.resolve_relative(phrase, dt(2026, 9, 18)).date > date(2026, 9, 18)


def test_open_day_helpers(resolver: MadridDateResolver) -> None:
    assert resolver.is_open_day(date(2026, 9, 18))
    assert not resolver.is_open_day(date(2026, 9, 20))  # Sunday
    assert not resolver.is_open_day(date(2026, 10, 12))  # Fiesta Nacional
    assert resolver.next_open_day(date(2026, 10, 11)) == date(2026, 10, 13)
    assert resolver.next_open_after(date(2026, 10, 11)) == date(2026, 10, 13)


def test_unresolvable_raises(resolver: MadridDateResolver) -> None:
    with pytest.raises(ValueError):
        resolver.resolve_relative("sometime soon-ish", dt(2026, 9, 18))


@pytest.mark.parametrize("phrase,expected,part", [
    ("2026-09-24", date(2026, 9, 24), None),
    ("on 2026-09-24 in the morning", date(2026, 9, 24), "morning"),
    ("2026-10-12", date(2026, 10, 13), None),
    ("September 24 2027", date(2027, 9, 24), None),
    ("24 September 2027", date(2027, 9, 24), None),
    ("tomorrow morning", date(2026, 9, 21), "morning"),
    ("the day after tomorrow in the afternoon", date(2026, 9, 21), "afternoon"),
    ("a week from today in the afternoon", date(2026, 9, 26), "afternoon"),
    ("in a fortnight in the morning", date(2026, 10, 3), "morning"),
    ("first thing tomorrow", date(2026, 9, 21), "morning"),
    ("el jueves", date(2026, 9, 24), None),
    ("el miércoles por la tarde", date(2026, 9, 23), "afternoon"),
    ("mañana por la mañana", date(2026, 9, 21), "morning"),
    ("el 24 de septiembre", date(2026, 9, 24), None),
    ("el 12 de octubre", date(2026, 10, 13), None),
])
def test_explicit_and_qualified_dates_keep_the_requested_day(resolver, phrase, expected, part):
    result = resolver.resolve_relative(phrase, dt(2026, 9, 19))
    assert result.date == expected
    assert result.part_of_day == part


@pytest.mark.parametrize("phrase", [
    "2026-02-30", "Monday 31 February", "el lunes 31 de febrero",
    "2026-09-19", "2026-09-18", "September 18 2026",
])
def test_invalid_or_non_future_explicit_dates_are_not_silently_changed(resolver, phrase):
    with pytest.raises(ValueError):
        resolver.resolve_relative(phrase, dt(2026, 9, 19))


# ---- the published phrase vocabulary (problems.md #5) ----------------------


PUBLISHED_PHRASES = (
    ["tomorrow", "the day after tomorrow", "a week from today", "in a fortnight",
     "on Saturday morning", "first thing on Monday the twelfth of October"]
    + [f"this coming {d}" for d in ("monday", "tuesday", "wednesday", "thursday",
                                    "friday", "saturday", "sunday")]
    + [f"first thing {d}" for d in ("monday", "tuesday", "wednesday", "thursday",
                                    "friday", "saturday", "sunday")]
    + [f"{d} afternoon" for d in ("monday", "tuesday", "wednesday", "thursday",
                                  "friday", "saturday", "sunday")]
)


@pytest.mark.parametrize("phrase", PUBLISHED_PHRASES)
def test_every_published_phrase_resolves(phrase):
    """Problem 5 publishes its whole vocabulary; none of it may be unresolvable.

    An unresolvable phrase falls back to a fourteen-day window, which answers
    a different question from the one the caller asked and loses the case.
    """
    resolver = MadridDateResolver()
    called_on_a_thursday = datetime(2026, 9, 17, 11, 0, tzinfo=MADRID)
    resolution = resolver.resolve_relative(phrase, called_on_a_thursday)

    assert resolution.date > called_on_a_thursday.date(), "nothing books same-day"
    assert resolver.is_open_day(resolution.date), "resolved onto a closed day"


def test_a_weekday_said_on_its_own_day_is_a_week_away():
    """"This coming Thursday", said on a Thursday, is not today."""
    resolver = MadridDateResolver()
    thursday = datetime(2026, 9, 17, 11, 0, tzinfo=MADRID)
    assert resolver.resolve_relative("this coming thursday", thursday).date == date(2026, 9, 24)


def test_the_closure_day_rolls_forward():
    """Monday 12 October is Fiesta Nacional: "first thing Monday" is the trap."""
    resolver = MadridDateResolver()
    before = datetime(2026, 10, 8, 11, 0, tzinfo=MADRID)  # a Thursday
    resolution = resolver.resolve_relative("first thing on Monday the twelfth of October", before)
    assert resolution.date == date(2026, 10, 13)
    assert resolution.part_of_day == "morning"
