"""The clinic's people and routes, over HTTP, for the panel to edit.

Read by any member of the organisation, written only by an owner or an admin
— the same two rules the credential routes already use, through the same two
dependencies, because a third way of deciding who may write is how one of
them ends up wrong.

Every read returns the **effective** directory: the organisation's own rows
laid over the four roles and eighteen routes `clinic/graph.py` declares by
hand. Each row says which it is, in `source`. A panel can therefore show a
clinic that has configured nothing as four greyed-out defaults rather than as
an empty screen that looks broken, and deleting a row is visibly a return to
the default rather than a deletion of the target.

Staff telephone numbers and emails are here, and they are the reason this is
behind a membership check rather than merely behind the ops door.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from agent.accounts import directory
from agent.accounts.store import Person, Route, StoreError, normalize_slug
from agent.brain import deps
from agent.config import settings
from agent.ops.auth import require_admin, require_member

router = APIRouter(prefix="/ops/api/orgs")


def _config() -> Any:
    """The settings these reads resolve against.

    Named rather than left to `directory`'s own default so that this router
    reads the same configuration the rest of the console reads. A module that
    silently falls back to the process-wide settings is a module whose tests
    are talking to a different database than its routes are.
    """
    return settings()


def _access(request: Request) -> None:
    """The ops door, lazily imported because console registers this router."""
    from agent.ops.console import require_ops_access

    require_ops_access(request)


# ---- what goes over the wire ----------------------------------------------
class PersonView(BaseModel):
    """A person, and everything the agent needs in order to ring them."""

    slug: str
    name: str
    role: str
    detail: str = ""
    languages: list[str] = Field(default_factory=list)
    provider_id: str | None = None
    phone: str = ""
    email: str = ""
    # The call profile. This is the part that belongs to the person and not to
    # the deployment: two colleagues on the same line can be opened
    # differently, in different languages, with different things the agent is
    # allowed to ask them.
    opening: str = ""
    may_ask: list[str] = Field(default_factory=list)
    must_not_ask: list[str] = Field(default_factory=list)
    # Con qué voz llama la clínica a ESTA persona. Vacío usa la del
    # despliegue, que es como se comportaba todo antes de existir el campo.
    voice: str = ""
    active: bool = True
    # "configured" or "default". A panel showing the difference is a panel
    # that cannot pretend somebody set this up.
    source: str = "configured"


class PersonWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(default="other", max_length=40)
    detail: str = Field(default="", max_length=400)
    languages: list[str] = Field(default_factory=list)
    provider_id: str | None = None
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=200)
    opening: str = Field(default="", max_length=600)
    may_ask: list[str] = Field(default_factory=list)
    must_not_ask: list[str] = Field(default_factory=list)
    voice: str = Field(default="", max_length=40)
    active: bool = True


class RouteView(BaseModel):
    reason: str
    person_slug: str
    urgency: str
    detail: str = ""
    source: str = "configured"
    # Whether anybody actually answers to `person_slug`. False is not a
    # refusal — the graph always has a target — but it is the thing a panel
    # must be able to show before it is discovered during an emergency.
    reachable: bool = True


class RouteWrite(BaseModel):
    person_slug: str = Field(min_length=1, max_length=64)
    urgency: str
    detail: str = Field(default="", max_length=400)


class CallProfileView(BaseModel):
    """Exactly what a clinic-rings-a-colleague call would open with.

    Served so that somebody editing a profile can see the result without
    placing a call. It is the same `directory.cover_brief` the call itself
    uses, so the screen cannot drift from the behaviour.
    """

    person: PersonView
    brief: dict[str, str]


def _person_view(person: Person) -> PersonView:
    return PersonView(
        slug=person.slug,
        name=person.name,
        role=person.role,
        detail=person.detail,
        languages=list(person.languages),
        provider_id=person.provider_id,
        phone=person.phone,
        email=person.email,
        opening=person.opening,
        may_ask=list(person.may_ask),
        must_not_ask=list(person.must_not_ask),
        voice=person.voice,
        active=person.active,
        source=person.source,
    )


def _route_view(route: Route, known: set[str]) -> RouteView:
    return RouteView(
        reason=route.reason,
        person_slug=route.person_slug,
        urgency=route.urgency,
        detail=route.detail,
        source=route.source,
        reachable=route.person_slug in known,
    )


def _slug(raw: str) -> str:
    try:
        return normalize_slug(raw)
    except StoreError as exc:
        raise HTTPException(400, str(exc)) from exc


def _urgency() -> tuple[str, ...]:
    from agent.clinic import graph

    return tuple(graph.URGENCY)


# ---- people ---------------------------------------------------------------
@router.get("/{org_id}/people", dependencies=[Depends(_access)])
async def list_people(request: Request, org_id: str) -> list[PersonView]:
    """Everybody this clinic can ring, defaults included."""
    _, wanted, _ = require_member(request, org_id)
    return [_person_view(person) for person in directory.people_for(wanted, _config())]


@router.put("/{org_id}/people/{slug}", dependencies=[Depends(_access)])
async def put_person(request: Request, org_id: str, slug: str, body: PersonWrite) -> PersonView:
    """Create or replace one person.

    A row whose slug is one of the four declared roles replaces that default;
    any other slug is somebody new alongside them. Nobody can configure their
    way into a clinic with no front desk.
    """
    platform, wanted, _ = require_admin(request, org_id)
    try:
        saved = platform.upsert_person(
            wanted,
            Person(
                slug=_slug(slug),
                name=body.name,
                role=body.role,
                detail=body.detail,
                languages=tuple(code.strip().lower() for code in body.languages if code.strip()),
                provider_id=body.provider_id,
                phone=body.phone,
                email=body.email,
                opening=body.opening,
                may_ask=tuple(item.strip() for item in body.may_ask if item.strip()),
                must_not_ask=tuple(item.strip() for item in body.must_not_ask if item.strip()),
                voice=body.voice.strip(),
                active=body.active,
            ),
        )
    except StoreError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _person_view(saved)


@router.delete("/{org_id}/people/{slug}", dependencies=[Depends(_access)])
async def delete_person(request: Request, org_id: str, slug: str) -> list[PersonView]:
    """Remove a configured person.

    Returns the directory afterwards rather than an empty body, because the
    interesting part is what took their place: deleting a row whose slug was a
    declared role restores that role, and the panel should see that happen.
    """
    platform, wanted, _ = require_admin(request, org_id)
    if not platform.delete_person(wanted, _slug(slug)):
        raise HTTPException(404, "esa persona no está configurada en esta organización")
    return [_person_view(person) for person in directory.people_for(wanted, _config())]


# ---- routes ---------------------------------------------------------------
@router.get("/{org_id}/routes", dependencies=[Depends(_access)])
async def list_routes(request: Request, org_id: str) -> list[RouteView]:
    """All eighteen endings and who hears about each one here."""
    _, wanted, _ = require_member(request, org_id)
    known = {person.slug for person in directory.people_for(wanted, _config())}
    return [_route_view(route, known) for route in directory.routes_for(wanted, _config())]


@router.put("/{org_id}/routes/{reason}", dependencies=[Depends(_access)])
async def put_route(request: Request, org_id: str, reason: str, body: RouteWrite) -> RouteView:
    """Point one of the eighteen reasons at somebody.

    The reason must be one of the clinic's own eighteen and the urgency one of
    the three the graph draws. A route invented here would be a node nobody
    renders and an escalation nobody sorts.
    """
    platform, wanted, _ = require_admin(request, org_id)
    if reason not in deps.CLOSED_REASONS:
        raise HTTPException(400, f"«{reason}» no es una de las razones de la clínica")
    if body.urgency not in _urgency():
        raise HTTPException(400, f"urgencia no válida; usa una de {list(_urgency())}")
    target = _slug(body.person_slug)
    if directory.person_for(wanted, target, _config()) is None:
        # Refused rather than stored: a route is only worth writing if
        # somebody answers to it, and finding out otherwise during a medical
        # emergency is the failure this whole table exists to avoid.
        raise HTTPException(400, f"nadie responde a «{target}» en esta organización")
    try:
        saved = platform.upsert_route(
            wanted, Route(reason=reason, person_slug=target, urgency=body.urgency, detail=body.detail)
        )
    except StoreError as exc:
        raise HTTPException(400, str(exc)) from exc
    known = {person.slug for person in directory.people_for(wanted, _config())}
    return _route_view(saved, known)


@router.delete("/{org_id}/routes/{reason}", dependencies=[Depends(_access)])
async def delete_route(request: Request, org_id: str, reason: str) -> RouteView:
    """Back to the hand-written route. A reason is never left with nobody."""
    platform, wanted, _ = require_admin(request, org_id)
    if not platform.delete_route(wanted, reason):
        raise HTTPException(404, "esa razón no está configurada en esta organización")
    restored = directory.route_for(wanted, reason, _config())
    if restored is None:
        raise HTTPException(404, "esa razón no es una de las de la clínica")
    known = {person.slug for person in directory.people_for(wanted, _config())}
    return _route_view(restored, known)


# ---- the call profile, as the call would use it ---------------------------
@router.get("/{org_id}/voices", dependencies=[Depends(_access)])
async def voices(org_id: str) -> dict[str, list[dict[str, str]]]:
    """Las voces que publica el motor, para el selector.

    Servidas desde aquí en vez de escritas en el panel: son una propiedad del
    modelo que este proceso tiene pinchado, no una preferencia de una
    pantalla. El día que cambie el modelo, el selector cambia solo.
    """
    from agent.voice.gemini_live import GEMINI_VOICES

    return {"voices": [{"id": name, "detail": detail} for name, detail in GEMINI_VOICES]}


@router.get("/{org_id}/people/{slug}/call-profile", dependencies=[Depends(_access)])
async def call_profile(
    request: Request, org_id: str, slug: str, reason: str = "", gap: str = ""
) -> CallProfileView:
    """What ringing this person would open with, without ringing them.

    The brief is built by the same function the call builds it with, so this
    screen cannot drift from what actually happens on the line.
    """
    _, wanted, _ = require_member(request, org_id)
    person = directory.person_for(wanted, _slug(slug), _config())
    if person is None:
        raise HTTPException(404, "nadie responde a ese identificador")
    brief = directory.cover_brief(
        wanted,
        reason,
        gap=gap,
        person_slug=person.slug,
        provider_id=person.provider_id or "",
        config=_config(),
    )
    return CallProfileView(person=_person_view(person), brief=brief)


def unreachable(org_id: str) -> list[dict[str, Any]]:
    """Routes pointing at nobody. What the panel's warning banner reads."""
    return [route.__dict__ for route in directory.unreachable_routes(org_id, _config())]
