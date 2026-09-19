"""Who should cover this, asked of Jev — on a page refresh, never on a call.

The rota answers "who covers a gynaecologist" with a route, and a route is one
answer for every absence. Jev can read the situation in words and pick out of
the clinic's own rota, which is the thing a fixed route cannot do: *this*
Monday, *this* specialty, *this* colleague already in clinic.

Why it is here and not in `brain/tools.py`
------------------------------------------
Because of what it costs and when. A Jev read is a network round trip with a
600 ms budget, and the thing on the other end of a scored call is a person
waiting through the silence. Three minutes of call has no room for a lookup
that is *advisory* — the configured route already answers, correctly, in
microseconds, and the model already has the brief.

A panel refresh has all the room in the world. Nobody is on hold, the answer
arrives before the page finishes painting, and if it does not arrive at all
the panel shows the configured route, which is what it showed yesterday. So
the suggestion is offered exactly where a human is reading it and deciding,
and never where a caller is waiting for it.

The answer is a *suggestion*, and it says so. `source` is "jev" or "route",
the configured fallback is returned alongside it either way, and the phone
number that rings is the one a person taps. Nothing here dials anything.
"""
from __future__ import annotations

from time import perf_counter
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from agent.accounts import directory
from agent.accounts.store import Person
from agent.clinic import graph as clinic_graph
from agent.orgs import DEFAULT_ORG_ID

router = APIRouter(prefix="/ops/api/live")


def _access(request: Request) -> None:
    from agent.ops.console import require_ops_access

    require_ops_access(request)


def _describe(person: Person, names: dict[str, str]) -> str:
    """The line Jev chooses by. Role, what they cover, what they may be asked.

    `names` turns the `covers_for` slug into the colleague's actual name. That
    is not cosmetic: the situation arrives in words — "Germán is off too" —
    and a criterion that reads "steps in for german-padua" makes the model
    match a slug against a sentence. With the name in it, the second line of
    the rota is reachable, which is the whole reason the column exists.

    Deliberately not the phone number and not the email. Jev is being asked
    which colleague fits a situation; a mobile number cannot help it decide
    and has no business leaving this process.
    """
    parts = [person.role]
    if person.detail:
        parts.append(person.detail)
    if person.covers_for:
        covered = names.get(person.covers_for, person.covers_for)
        parts.append(f"Sustituye a {covered} cuando {covered} no puede")
    if person.may_ask:
        parts.append("may be asked: " + "; ".join(person.may_ask))
    if person.must_not_ask:
        parts.append("must not be asked: " + "; ".join(person.must_not_ask))
    return ". ".join(part for part in parts if part)


def _card(person: Person | None, *, source: str) -> dict[str, Any] | None:
    """One person, as the panel shows them. Contact details included here:

    this side of the wire is a member of their own organisation looking at
    their own colleagues, which is the one place a staff mobile belongs.
    """
    if person is None:
        return None
    return {
        "slug": person.slug,
        "name": person.name,
        "role": person.role,
        "detail": person.detail,
        "phone": person.phone,
        "covers_for": person.covers_for,
        "source": source,
    }


@router.get("/cover")
async def suggest_cover(
    request: Request,
    situation: str = Query("", description="What happened, in words."),
    reason: str = Query("", description="One of the eighteen endings, for the fallback."),
    org_id: str = Query(DEFAULT_ORG_ID),
    _: None = Depends(_access),
) -> dict[str, Any]:
    """A suggestion for who to ring, and the configured route underneath it.

    Both are always returned. The panel renders the suggestion as a suggestion
    and the route as the thing that happens if nobody intervenes, so a wrong
    guess costs a glance rather than a phone call.
    """
    people = [p for p in directory.people_for(org_id) if p.active]
    fallback = None
    escalation = clinic_graph.who_to_call(reason, org_id) if reason else None
    if escalation is not None:
        fallback = directory.person_for(org_id, escalation.target)

    chosen: Person | None = None
    latency_ms = 0.0
    asked = bool(situation.strip()) and bool(people)
    if asked:
        started = perf_counter()
        names = {p.slug: p.name for p in people}
        options = {p.slug: _describe(p, names) for p in people}
        slug = await _ask_jev(situation, options)
        latency_ms = round((perf_counter() - started) * 1000.0, 1)
        if slug:
            chosen = next((p for p in people if p.slug == slug), None)

    suggested = _card(chosen, source="jev") or _card(fallback, source="route")
    return {
        "situation": situation.strip(),
        "reason": reason,
        "asked": asked,
        "suggested": suggested,
        "fallback": _card(fallback, source="route"),
        "urgency": escalation.urgency if escalation is not None else "",
        "considered": [{"slug": p.slug, "name": p.name, "role": p.role} for p in people],
        "latency_ms": latency_ms,
    }


async def _ask_jev(situation: str, people: dict[str, str]) -> str | None:
    """The sidecar, or None. Never raises: a panel does not 500 over a hint."""
    try:
        from agent.brain.tools import _build_jev_client
        from agent.config import settings

        client = _build_jev_client(settings())
        if client is None:
            return None
        # A second of budget rather than the call path's 600 ms. Nobody is on
        # hold here, and an abstention on a slow day is a worse answer than a
        # page that paints 400 ms later.
        return await client.classify_cover(situation, people, timeout_seconds=1.0)
    except Exception:  # noqa: BLE001 - the route below is always a valid answer
        return None


__all__ = ["router"]
