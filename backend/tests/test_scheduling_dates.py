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
