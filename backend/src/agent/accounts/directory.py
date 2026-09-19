"""The clinic's own people and routes, with the hand-written four underneath.

`clinic/graph.py` computes almost everything from the catalogue and declares
exactly one thing by hand: the humans the API has never heard of — a front
desk, somebody who runs the place, somebody on call, and 112 — plus which of
the eighteen endings reaches which of them. A hospital has twenty human nodes
and a consulting room has two, and neither should be editing that file.

This module turns those two hand-written tables into per-organisation data
**without becoming a second copy of them**. The defaults are not restated
here: they are read back out of `graph.build(None)`, which is exactly "the
graph with no catalogue", i.e. the hand-written part and nothing else. One
source of truth, still in `graph.py`, where it has always been.

The overlay rule, which is the whole design and is deliberately one sentence:

> A configured row **replaces** the default with the same key; every default
> nobody has replaced **stays**.

So an organisation that configures nothing behaves exactly as today, and an
organisation that configures one role or one reason does not silently lose
the other three roles and the other seventeen reasons. A clinic is never left
with nobody to call, which is the one failure this file exists to prevent.

The call profile
----------------
`Person` carries what the agent should do when it rings *that* person: the
language to open in, what to say, and what it may and may not ask them. Until
now the only one of those that existed was the language, and it came from
`provider_id` through the catalogue — which works for a doctor and has
nothing to say about a receptionist or a manager. Here the person's own row
answers first and the catalogue is the fallback, so a doctor behaves exactly
as before and everybody else finally has an answer.

Staff phone numbers and emails are in the row and are deliberately **not** in
the brief that reaches a prompt. Ringing somebody is a thing a person does
with that number; the model never needs it.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from agent.accounts.store import Person, Route, store
from agent.orgs import normalize_org_id

# PARA QUÉ llama esta llamada.
#
# Todas las llamadas salientes usaban el mismo guion: "se ha roto la agenda,
# ¿te ves cubriéndolo?". Eso está bien cuando falta un ginecólogo el lunes y
# está mal en todo lo demás — avisar a urgencias de que hay una emergencia no
# es pedirle un favor a nadie, y preguntarle con guasa si "se ve cubriéndolo"
# es exactamente la llamada que no hay que hacer.
#
# El propósito sale de dos cosas que ya están en los datos: por qué se llama,
# y qué hace quien descuelga. El cargo manda sobre el motivo, porque un
# médico de guardia es un médico de guardia le llames por lo que le llames.
_PURPOSE_BY_ROLE: dict[str, str] = {
    "guardia": (
        "Llamas a quien está de guardia. No le pides que cubra una agenda: le pasas "
        "algo que no aguanta a mañana. Sé breve, di qué pasa y qué necesitas, y "
        "cuelga pronto. Puede estar con alguien delante."
    ),
    "urgencias": (
        "Llamas a Urgencias. Esto no va de agenda: va de un paciente ahora. Di qué "
        "pasa en una frase, sin rodeos y sin gracia ninguna, y escucha lo que te "
        "digan que hay que hacer."
    ),
    "coordinación": (
        "Llamas a quien reparte el trabajo. No le pides que atienda a nadie: le pides "
        "una decisión. Dile qué ha pasado, qué opciones hay y qué necesitas que "
        "decida. Va al grano y agradece que tú también vayas."
    ),
    "mostrador": (
        "Llamas al mostrador. Es un encargo, no un favor: di qué hay que hacer, con "
        "quién y para cuándo, y confirma que queda apuntado."
    ),
    "administración": (
        "Llamas a administración. Es papeleo: pólizas, volantes, facturación. Nada "
        "clínico, y nada que tenga que decidir un médico."
    ),
    "trabajo social": (
        "Llamas a trabajo social. Va de la situación de una persona, no de una "
        "agenda. Cuenta el caso con cuidado y pregunta qué se puede hacer."
    ),
}

_PURPOSE_BY_REASON: dict[str, str] = {
    "medical_emergency": (
        "Esto es una urgencia médica. No estás pidiendo un favor ni negociando una "
        "agenda: estás avisando. Una frase con qué ha pasado, dónde y quién, y "
        "después callas y escuchas. Ni bromas, ni cortesías largas, ni ofrecer citas."
    ),
    "provider_on_leave": (
        "Falta un médico y su agenda se queda sin cubrir. Le preguntas a esta "
        "persona si puede cogerla. Un no es un no a la primera."
    ),
    "no_availability": (
        "No hay hueco para lo que pide un paciente. Le llamas para que decida: abrir "
        "agenda, doblar una consulta o derivar. No decides tú."
    ),
    "caller_not_authorised": (
        "Alguien ha pedido datos de otra persona y no le tocan. Le cuentas lo que ha "
        "pasado para que decida qué se le dice. No le des datos del paciente que no "
        "necesite para decidir."
    ),
    "patient_history": (
        "El historial impide lo que se pedía y hace falta criterio médico. Expón el "
        "caso y deja que decida."
    ),
    "referral_required": "Hace falta un volante. Es gestión, no criterio clínico.",
    "insurer_referral_required": "La aseguradora exige volante. Es gestión con el paciente.",
    "allowance_exhausted": "Al paciente se le han agotado las visitas del plan. Es gestión.",
    "specialty_not_covered": "El plan del paciente no cubre esa especialidad. Es gestión.",
    "location_not_covered": "El plan del paciente no cubre esa sede. Es gestión.",
    "provider_not_in_network": "Ese médico no acepta el plan del paciente. Es gestión.",
    "clinic_closed": "La clínica estaba cerrada cuando llamaron. Hay que recuperar a esa persona.",
}


def _purpose(reason: str, role: str) -> str:
    """Qué es esta llamada. El cargo manda sobre el motivo."""
    from agent.clinic.cache import _fold

    by_role = _PURPOSE_BY_ROLE.get(_fold(role)) if role else None
    if by_role:
        return by_role
    return _PURPOSE_BY_REASON.get(reason, "")


# Cuánto corre, dicho como lo diría una persona.
_URGENCY_SAID = {
    "now": "ahora mismo, interrumpe lo que esté haciendo",
    "today": "hoy, antes de que se acabe el día",
    "queue": "no corre prisa, cuando pueda",
}

# How a language code is said out loud in the brief. The three the catalogue
# actually returns, plus the two a Spanish clinic can reasonably hire for.
_SAID = {
    "es": "español",
    "en": "inglés",
    "ca": "català",
    "gl": "galego",
    "eu": "euskara",
}


# ---- the hand-written layer, read rather than restated --------------------
@lru_cache(maxsize=1)
def _declared() -> tuple[tuple[Person, ...], tuple[Route, ...]]:
    """The four roles and the eighteen routes `graph.py` declares by hand.

    Read off the two tables in that module rather than restated here, so a
    fifth role added there appears here the same day and a route edited there
    is not quietly overridden by a stale duplicate in the accounts layer.

    Read off the **tables** and deliberately not off `graph.build()`. Once
    `graph` calls `escalation_targets` in place of its own tables — which is
    the whole point of this module — going through `build()` would be this
    function calling the function that calls this function. Constants cannot
    recurse.

    `DECLARED_ROLES` / `DECLARED_ESCALATION` are read first so that `graph`
    can make them public without breaking this; the private names it has
    today are the fallback.

    Imported inside the function: `graph` importing this module back at
    module level would be a cycle either way.
    """
    from agent.clinic import graph

    declared_roles = getattr(graph, "DECLARED_ROLES", None) or graph._ROLES
    declared_routes = getattr(graph, "DECLARED_ESCALATION", None) or graph._ESCALATION
    people = tuple(
        Person(slug=slug, name=label, role=slug, detail=detail, source="default")
        for slug, label, detail in declared_roles
    )
    routes = tuple(
        Route(
            reason=reason,
            person_slug=target,
            urgency=urgency,
            detail=detail,
            source="default",
        )
        for reason, (target, urgency, detail) in sorted(declared_routes.items())
    )
    return people, routes


def default_people() -> tuple[Person, ...]:
    return _declared()[0]


def default_routes() -> tuple[Route, ...]:
    return _declared()[1]


def reset_defaults_cache() -> None:
    """Test isolation only."""
    _declared.cache_clear()
    _WARNED.clear()


# ---- reaching the database without ever being the reason a call fails -----
# Organisations already warned about. This is read on the path that decides
# who to ring about a medical emergency, and once per lookup would turn one
# stale schema into a log line per escalation.
_WARNED: set[str] = set()


def _rows(org_id: str, config: Any | None = None) -> tuple[list[Person], list[Route]]:
    """Configured people and routes, or nothing at all.

    A missing, locked or not-yet-migrated database yields empty lists and
    therefore the hand-written defaults. This decides who hears about a
    medical emergency; it does not get to raise.
    """
    try:
        platform = store(config)
        if not platform.exists:
            # No database on this host. The normal state of a deployment that
            # has not been provisioned, and not worth a word in the log.
            return [], []
        return platform.list_people(org_id), platform.list_routes(org_id)
    except Exception as exc:  # noqa: BLE001 - defaults are always better than an error
        if org_id not in _WARNED:
            from loguru import logger

            _WARNED.add(org_id)
            logger.warning(
                "directory unavailable for {} ({}); using the declared defaults",
                org_id,
                type(exc).__name__,
            )
        return [], []


# ---- the overlay ----------------------------------------------------------
def people_for(org_id: str, config: Any | None = None) -> list[Person]:
    """Everybody this clinic can ring: configured rows over the declared four.

    Ordered with the human roles the graph declares first and in their
    declared order, then everybody else by name, so a panel does not reshuffle
    when somebody is hired.
    """
    org_id = normalize_org_id(org_id)
    configured, _ = _rows(org_id, config)
    merged: dict[str, Person] = {person.slug: person for person in default_people()}
    declared_order = list(merged)
    for person in configured:
        if not person.active:
            # Inactive replaces nothing and is not callable. Dropping the row
            # instead would silently restore the default in its place.
            merged.pop(person.slug, None)
            continue
        merged[person.slug] = person
    rank = {slug: index for index, slug in enumerate(declared_order)}
    return sorted(merged.values(), key=lambda p: (rank.get(p.slug, len(rank)), p.name))


def person_for(org_id: str, slug: str, config: Any | None = None) -> Person | None:
    """One person by slug, defaults included. None when nobody answers to it."""
    wanted = (slug or "").strip().lower()
    if not wanted:
        return None
    for person in people_for(org_id, config):
        if person.slug == wanted:
            return person
    return None


def routes_for(org_id: str, config: Any | None = None) -> list[Route]:
    """All eighteen endings and who hears about each, configured rows on top."""
    org_id = normalize_org_id(org_id)
    _, configured = _rows(org_id, config)
    merged: dict[str, Route] = {route.reason: route for route in default_routes()}
    for route in configured:
        merged[route.reason] = route
    return [merged[reason] for reason in sorted(merged)]


def route_for(org_id: str, reason: str, config: Any | None = None) -> Route | None:
    """Who hears about this ending here, or None when it is not one of ours."""
    for route in routes_for(org_id, config):
        if route.reason == reason:
            return route
    return None


def unreachable_routes(org_id: str, config: Any | None = None) -> list[Route]:
    """Routes pointing at a slug nobody answers to.

    Never used to refuse a call — the graph always gets a target — but the
    panel should be able to say "this reason points at somebody who is not
    here any more" rather than letting it be discovered during an emergency.
    """
    known = {person.slug for person in people_for(org_id, config)}
    return [route for route in routes_for(org_id, config) if route.person_slug not in known]


# ---- what `clinic/graph.py` should call instead of its own two tables -----
# Both return exactly the shapes `_ROLES` and `_ESCALATION` already have, so
# the call sites there change and nothing else does.
def escalation_targets(org_id: str, config: Any | None = None) -> list[tuple[str, str, str]]:
    """Drop-in for `graph._ROLES`: (id, label, detail) per human node."""
    return [(p.slug, p.name, p.detail) for p in people_for(org_id, config)]


def escalation_routes(org_id: str, config: Any | None = None) -> dict[str, tuple[str, str, str]]:
    """Drop-in for `graph._ESCALATION`: reason -> (target, urgency, detail)."""
    return {r.reason: (r.person_slug, r.urgency, r.detail) for r in routes_for(org_id, config)}


def escalation_route(
    org_id: str, reason: str, config: Any | None = None
) -> tuple[str, str, str] | None:
    """Drop-in for `graph._ESCALATION.get(reason)`."""
    route = route_for(org_id, reason, config)
    return None if route is None else (route.person_slug, route.urgency, route.detail)


# ---- the call profile -----------------------------------------------------
def languages_of(person: Person | None, org_id: str, config: Any | None = None) -> tuple[str, ...]:
    """The codes this person speaks: their own row first, the catalogue after.

    A doctor with nothing written down resolves exactly as before — off
    `provider_id` through the catalogue — and somebody who is not in the
    catalogue at all finally has an answer instead of an empty string.
    """
    if person is None:
        return ()
    if person.languages:
        return person.languages
    if not person.provider_id:
        return ()
    try:
        from agent.brain import deps

        cache = deps.try_catalogue_cache(normalize_org_id(org_id))
        provider = cache.provider_by_id(person.provider_id) if cache is not None else None
    except Exception:  # noqa: BLE001 - never let a lookup table stop a call opening
        return ()
    return tuple(getattr(provider, "languages", ()) or ()) if provider is not None else ()


def said(codes: tuple[str, ...]) -> str:
    """"español, inglés" — the way a person says it, for a prompt."""
    return ", ".join(_SAID.get(code, code) for code in codes)


def cover_brief(
    org_id: str,
    reason: str,
    *,
    who: str = "",
    because: str = "",
    urgency: str = "",
    gap: str = "",
    provider_id: str = "",
    person_slug: str = "",
    missing: str = "",
    situation: str = "",
    config: Any | None = None,
) -> dict[str, str]:
    """What the clinic-rings-a-colleague call needs to know before it opens.

    Same six keys `/ws/demo?reason=` already builds — `reason`, `who`,
    `because`, `urgency`, `gap`, `speaks` — so a prompt that renders only
    those is unchanged, resolved through this organisation's routes instead
    of a hand-written map. Three more carry the per-person call profile:

    * `opening` — what to say when *this* person picks up.
    * `may_ask` / `must_not_ask` — what the agent may and may not ask them.

    An explicit argument always wins: the panel knows what it was looking at,
    and this must never argue with it.

    Contact details are not here on purpose. A phone number is how a human
    rings somebody, not something a model needs in its context.
    """
    org_id = normalize_org_id(org_id)
    route = route_for(org_id, reason, config)
    slug = person_slug or (route.person_slug if route else "")
    person = person_for(org_id, slug, config) if slug else None
    if person is None and provider_id:
        # The panel named a doctor rather than a role: find the row that says
        # it is them, so a configured doctor's profile is still used.
        person = next(
            (p for p in people_for(org_id, config) if p.provider_id == provider_id), None
        )
    if person is None and provider_id:
        person = Person(slug=provider_id, name="", role="provider", provider_id=provider_id)

    # Who is not there. Either said explicitly by whoever started the call,
    # or — when this person is somebody's substitute — the colleague they
    # stand in for, which is the reason they are being rung at all.
    stands_in_for = ""
    if person is not None and getattr(person, "covers_for", ""):
        covered = person_for(org_id, person.covers_for, config)
        stands_in_for = covered.name if covered is not None else person.covers_for

    brief = {
        "reason": reason,
        # Lo primero del informe, porque decide todo lo demás: avisar a
        # urgencias y pedirle a un compañero que doble una mañana son dos
        # llamadas distintas, y hasta ahora eran la misma.
        "purpose": _purpose(reason, person.role if person else ""),
        "who": who or (person.name if person else "") or (route.person_slug if route else ""),
        # What this person does, and whatever the clinic wrote down about
        # them. Without it the call treats a coordinator, a podiatrist and
        # the doctor on call as the same person under different names, which
        # is exactly how it sounded.
        "role": person.role if person else "",
        "about_them": person.detail if person else "",
        "stands_in_for": stands_in_for,
        "missing": missing or stands_in_for,
        # The story in somebody's own words, when there is one. It beats the
        # route's stock sentence every time: the stock sentence is true of
        # every absence, and this call is about one of them.
        "situation": situation,
        "because": because or (route.detail if route else ""),
        "urgency": urgency or (route.urgency if route else ""),
        # Dicho, no en clave. "Urgencia: today" en un informe que se lee en
        # voz alta es una palabra en inglés que nadie sabe cuánto significa.
        "urgency_said": _URGENCY_SAID.get(urgency or (route.urgency if route else ""), ""),
        "gap": gap,
        "speaks": said(languages_of(person, org_id, config)),
        "opening": person.opening if person else "",
        "may_ask": "; ".join(person.may_ask) if person else "",
        "must_not_ask": "; ".join(person.must_not_ask) if person else "",
    }
    return {key: value for key, value in brief.items() if value}


__all__ = [
    "Person",
    "Route",
    "cover_brief",
    "default_people",
    "default_routes",
    "escalation_route",
    "escalation_routes",
    "escalation_targets",
    "languages_of",
    "people_for",
    "person_for",
    "reset_defaults_cache",
    "route_for",
    "routes_for",
    "said",
    "unreachable_routes",
]
