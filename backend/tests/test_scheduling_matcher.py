"""SlotMatcher tests: no same-day, Madrid timezone, filters, load spreading."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from agent.scheduling.matcher import (
    SlotMatcher,
    classify_part_of_day,
    parse_start_time,
)

MADRID = ZoneInfo("Europe/Madrid")


def slot(
    provider: str,
    start: str,
    *,
    location: str = "centro",
    specialty: str = "medicina-general",
    appointment_type: str = "review",
) -> dict[str, object]:
    return {
        "provider_id": provider,
        "provider_name": provider,
        "specialty_id": specialty,
        "location_id": location,
        "appointment_type_id": appointment_type,
        "start_time": start,
        "duration_minutes": 15,
        "payable_with": ["sanitas"],
    }


def now(y: int, m: int, d: int, hh: int = 8) -> datetime:
    return datetime(y, m, d, hh, 0, tzinfo=MADRID)


def test_earliest_start_first() -> None:
    slots = [slot("PR01", "2026-09-22T10:00:00+02:00"), slot("PR02", "2026-09-22T09:00:00+02:00")]
    selection = SlotMatcher().select(slots, now(2026, 9, 21))
    assert selection.best is not None
    assert selection.best.provider_id == "PR02"


def test_same_day_is_never_eligible() -> None:
    slots = [slot("PR01", "2026-09-21T16:00:00+02:00"), slot("PR01", "2026-09-22T09:00:00+02:00")]
    selection = SlotMatcher().select(slots, now(2026, 9, 21))
    assert selection.best is not None
    assert selection.best.start_time == "2026-09-22T09:00:00+02:00"
    assert selection.rejected.get("same_day") == 1


def test_same_day_is_compared_in_madrid() -> None:
    # 23:00 UTC on the 20th is 01:00 Madrid on the 21st -> same day as the call.
    slots = [slot("PR01", "2026-09-20T23:00:00+00:00")]
    selection = SlotMatcher().select(slots, now(2026, 9, 21))
    assert selection.best is None
    assert selection.rejected.get("same_day") == 1


def test_utc_offset_normalized_to_madrid() -> None:
    parsed = parse_start_time("2026-09-22T08:00:00+00:00")
    assert parsed is not None
    assert parsed.hour == 10
    assert classify_part_of_day(parsed) == "morning"


def test_provider_and_location_filters() -> None:
    slots = [
        slot("PR01", "2026-09-22T09:00:00+02:00", location="centro"),
        slot("PR02", "2026-09-22T09:00:00+02:00", location="sur"),
    ]
    by_provider = SlotMatcher().select(slots, now(2026, 9, 21), provider_id="PR02")
    assert [m.provider_id for m in by_provider.matches] == ["PR02"]
    by_location = SlotMatcher().select(slots, now(2026, 9, 21), location_id="centro")
    assert [m.location_id for m in by_location.matches] == ["centro"]


def test_specialty_filter() -> None:
    slots = [
        slot("PR01", "2026-09-22T09:00:00+02:00", specialty="dermatologia"),
        slot("PR02", "2026-09-22T09:00:00+02:00", specialty="medicina-general"),
    ]
    selection = SlotMatcher().select(slots, now(2026, 9, 21), specialty_id="dermatologia")
    assert [m.provider_id for m in selection.matches] == ["PR01"]


def test_part_of_day_filter() -> None:
    slots = [
        slot("PR01", "2026-09-22T09:00:00+02:00"),
        slot("PR02", "2026-09-22T16:00:00+02:00"),
    ]
    morning = SlotMatcher().select(slots, now(2026, 9, 21), part_of_day="morning")
    assert [m.provider_id for m in morning.matches] == ["PR01"]
    afternoon = SlotMatcher().select(slots, now(2026, 9, 21), part_of_day="afternoon")
    assert [m.provider_id for m in afternoon.matches] == ["PR02"]


def test_language_filter() -> None:
    slots = [
        slot("PR01", "2026-09-22T09:00:00+02:00"),
        slot("PR02", "2026-09-22T09:00:00+02:00"),
    ]
    matcher = SlotMatcher({"PR01": ["es"], "PR02": ["es", "ca"]})
    catalan = matcher.select(slots, now(2026, 9, 21), language="ca")
    assert [m.provider_id for m in catalan.matches] == ["PR02"]
    spanish = matcher.select(slots, now(2026, 9, 21), language="es")
    assert {m.provider_id for m in spanish.matches} == {"PR01", "PR02"}


def test_tie_break_prefers_less_busy_provider() -> None:
    # Both providers are free at 09:00, but PR02 has three free slots and PR01 one.
    slots = [
        slot("PR01", "2026-09-22T09:00:00+02:00"),
        slot("PR02", "2026-09-22T09:00:00+02:00"),
        slot("PR02", "2026-09-22T10:00:00+02:00"),
        slot("PR02", "2026-09-22T11:00:00+02:00"),
    ]
    selection = SlotMatcher().select(slots, now(2026, 9, 21))
    assert selection.best is not None
    assert selection.best.provider_id == "PR02"


def test_earliest_beats_load_spreading() -> None:
    slots = [
        slot("PR01", "2026-09-22T09:00:00+02:00"),
        slot("PR02", "2026-09-22T10:00:00+02:00"),
        slot("PR02", "2026-09-22T11:00:00+02:00"),
        slot("PR02", "2026-09-22T12:00:00+02:00"),
    ]
    selection = SlotMatcher().select(slots, now(2026, 9, 21))
    assert selection.best is not None
    assert selection.best.provider_id == "PR01"


def test_tie_break_is_deterministic() -> None:
    slots = [
        slot("PR02", "2026-09-22T09:00:00+02:00"),
        slot("PR01", "2026-09-22T09:00:00+02:00"),
    ]
    first = SlotMatcher().select(slots, now(2026, 9, 21))
    second = SlotMatcher().select(list(reversed(slots)), now(2026, 9, 21))
    assert first.best is not None and second.best is not None
    assert first.best.provider_id == second.best.provider_id == "PR01"


def test_selected_slot_is_verbatim() -> None:
    original = slot("PR01", "2026-09-22T09:00:00+02:00")
    selection = SlotMatcher().select([original], now(2026, 9, 21))
    assert selection.best_slot() is original
    assert selection.best is not None
    assert selection.best.start_time == "2026-09-22T09:00:00+02:00"


def test_on_date_filter() -> None:
    slots = [slot("PR01", "2026-09-22T09:00:00+02:00"), slot("PR01", "2026-09-23T09:00:00+02:00")]
    selection = SlotMatcher().select(slots, now(2026, 9, 21), on_date=date(2026, 9, 23))
    assert [m.start.date().isoformat() for m in selection.matches] == ["2026-09-23"]


def test_unparseable_slot_rejected() -> None:
    selection = SlotMatcher().select([slot("PR01", "not-a-date")], now(2026, 9, 21))
    assert selection.best is None
    assert selection.rejected.get("unparseable_time") == 1


def test_max_results_caps_ranking() -> None:
    slots = [slot(f"PR{i:02d}", "2026-09-22T09:00:00+02:00") for i in range(1, 6)]
    selection = SlotMatcher().select(slots, now(2026, 9, 21), max_results=2)
    assert len(selection.matches) == 2
    assert selection.considered == 5
