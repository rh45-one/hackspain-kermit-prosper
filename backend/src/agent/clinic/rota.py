"""What shift is uncovered, and whether the person you are ringing is free.

The catalogue publishes every provider's week — which site, which days, which
hours — and nothing was reading it. So a cover call said "nos hemos quedado sin
ginecología" and left the colleague to ask the two questions anybody asks
first: when, and where.

The second function is the one that saves a phone call. Ringing somebody to
cover Monday morning when the catalogue already says they are in clinic on
Monday morning is the kind of thing that makes people stop picking up, and it
is a lookup, not a judgement.
"""
from __future__ import annotations

from typing import Any

_WEEKDAYS: dict[str, str] = {
    "monday": "lunes",
    "tuesday": "martes",
    "wednesday": "miércoles",
    "thursday": "jueves",
    "friday": "viernes",
    "saturday": "sábado",
    "sunday": "domingo",
}


def _days(provider: Any) -> list[tuple[str, str, list[str]]]:
    """(weekday, site name, intervals) for everything this person works."""
    out: list[tuple[str, str, list[str]]] = []
    for schedule in getattr(provider, "schedules", None) or ():
        site = getattr(schedule, "location_name", "") or getattr(schedule, "location_id", "")
        for day in getattr(schedule, "days", None) or ():
            intervals = [str(i) for i in (getattr(day, "intervals", None) or ())]
            if intervals:
                out.append((str(getattr(day, "weekday", "")), str(site), intervals))
    return out


def shift_of(cache: Any, provider_id: str, weekday: str = "") -> str:
    """The shift that is now uncovered, said the way a person would say it.

    Without a weekday it describes the whole week, which is what you want when
    somebody is off indefinitely rather than for one morning.
    """
    if cache is None or not provider_id:
        return ""
    provider = cache.provider_by_id(provider_id) if hasattr(cache, "provider_by_id") else None
    if provider is None:
        return ""

    wanted = weekday.strip().lower()
    days = [d for d in _days(provider) if not wanted or d[0].lower() == wanted]
    if not days:
        return ""

    by_site: dict[str, list[str]] = {}
    for day, site, intervals in days:
        label = _WEEKDAYS.get(day.lower(), day)
        hours = " y ".join(i.replace("–", " a ").replace("-", " a ") for i in intervals)
        by_site.setdefault(site, []).append(f"{label} de {hours}")
    return "; ".join(f"{', '.join(when)} en {site}" for site, when in by_site.items())


def already_working(cache: Any, provider_id: str, weekday: str) -> str:
    """What this colleague is already doing then, or "" when they are free.

    Returned as the sentence rather than a boolean, because the useful thing
    to say is not "no" but "ya estás en Arenal Sur esa mañana".
    """
    if not weekday:
        return ""
    return shift_of(cache, provider_id, weekday)


def gap_sentence(cache: Any, missing_provider_id: str, weekday: str = "") -> str:
    """One line naming what needs covering, for the brief.

    Empty when the catalogue cannot say. An empty line is left out of the
    prompt entirely, which is better than a confident "el lunes" nobody
    checked — the colleague will ask, and being unable to answer is worse
    than having asked them to tell you.
    """
    shift = shift_of(cache, missing_provider_id, weekday)
    return shift or ""


__all__ = ["already_working", "gap_sentence", "shift_of"]
