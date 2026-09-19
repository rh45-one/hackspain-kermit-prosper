"""The clinic as a graph: who exists, who covers what, and who to call when.

Almost none of this is invented. The people, the sites, the specialties and
every edge between them are computed from the catalogue the clinic publishes,
so a doctor hired tomorrow is a node tomorrow and a doctor who goes on leave
stops being callable without anyone editing a file.

The failure modes are not invented either. The clinic defines exactly eighteen
reasons a request can end without a booking — `deps.CLOSED_REASONS` — and that
closed vocabulary is the complete list of what can go wrong on this line. Each
one is an edge from a situation to whoever has to hear about it.

What IS declared here is the handful of humans the catalogue does not know
about: a front desk, someone who runs the place, someone on call, and the
emergency services. A clinic has those and the API has never heard of them, so
they are named in `_ROLES` and nowhere else, and they are the only part of this
file anybody should have to edit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.brain import deps

# Where a human sits when the catalogue cannot answer. These four are the only
# invented nodes in the graph; everything else is computed. Keep it that way:
# every role added here is a thing that has to be kept true by hand.
_ROLES: tuple[tuple[str, str, str], ...] = (
    ("front_desk", "Recepción", "Atiende y resuelve lo que no necesita un médico."),
    ("manager", "Coordinación", "Decide cuando ninguna regla de la clínica decide."),
    ("on_call", "Médico de guardia", "Disponible fuera del horario de consulta."),
    ("emergency", "112 · Emergencias", "Fuera de la clínica. Se marca, no se consulta."),
)

# How loud each situation is. `now` interrupts a person; `today` reaches them
# before they go home; `queue` waits for someone to look. Nothing here decides
# on its own — it is what the panel colours and what a human sorts by.
URGENCY = ("now", "today", "queue")

# Every reason the clinic allows a call to end on, and who hears about it.
# The keys are checked against deps.CLOSED_REASONS at import: a reason added to
# the challenge and not to this map is a loud failure, not a silent gap.
_ESCALATION: dict[str, tuple[str, str, str]] = {
    # The patient is in danger. Nothing else on this list matters next to it.
    "medical_emergency": ("emergency", "now", "Cuelga y llama al 112."),
    # Somebody has to decide, and no rule can.
    "caller_not_authorised": ("manager", "today", "Un tercero pide datos que no le tocan."),
    "patient_history": ("manager", "today", "El historial lo impide; hace falta criterio."),
    "out_of_scope": ("front_desk", "queue", "No es una petición de agenda."),
    # The diary is the problem. The person who owns the diary hears it.
    "no_availability": ("manager", "today", "Sin hueco: hay que abrir agenda o derivar."),
    "provider_on_leave": ("manager", "today", "Ese médico no está; alguien tiene que cubrir."),
    "location_hours": ("front_desk", "queue", "La sede está cerrada a esa hora."),
    "clinic_closed": ("front_desk", "queue", "La clínica está cerrada."),
    # The plan is the problem. Recepción lo resuelve con el paciente.
    "specialty_not_covered": ("front_desk", "today", "Su plan no cubre esa especialidad."),
    "location_not_covered": ("front_desk", "today", "Su plan no cubre esa sede."),
    "provider_not_in_network": ("front_desk", "today", "Ese médico no acepta su plan."),
    "insurer_referral_required": ("front_desk", "today", "Su aseguradora exige volante."),
    "allowance_exhausted": ("front_desk", "today", "Se le han agotado las visitas."),
    "referral_required": ("front_desk", "today", "Esa especialidad necesita volante."),
    # The clinic's own rules. Nobody is at fault and nobody has to be called.
    "not_eligible_age": ("front_desk", "queue", "Fuera del rango de edad."),
    "type_not_offered": ("front_desk", "queue", "Esa especialidad no ofrece ese tipo de cita."),
    # Identification failed. Recepción lo arregla con el paciente delante.
    "patient_not_found": ("front_desk", "queue", "No está en el fichero."),
    "provider_not_found": ("front_desk", "queue", "Ese médico no existe aquí."),
}


@dataclass(frozen=True)
class Node:
    """A person, a place or a discipline. `kind` is what the panel draws."""

    id: str
    kind: str  # provider | site | specialty | role
    label: str
    detail: str = ""
    available: bool = True
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Edge:
    """A fact that connects two nodes. Never a judgement."""

    source: str
    target: str
    kind: str  # works_at | covers | escalates_to
    label: str = ""


@dataclass(frozen=True)
class Escalation:
    """One of the clinic's eighteen endings, and who hears about it."""

    reason: str
    target: str
    urgency: str
    detail: str


def _providers(cache: Any) -> list[Node]:
    out: list[Node] = []
    for provider in getattr(cache, "providers_by_id", {}).values():
        on_leave = bool(getattr(provider, "on_leave_until", None) or getattr(provider, "leave", None))
        languages = list(getattr(provider, "languages", ()) or ())
        out.append(
            Node(
                id=provider.id,
                kind="provider",
                label=provider.name,
                detail=getattr(provider, "specialty_name", "") or "",
                # A doctor on leave stays in the graph and stops being callable.
                # Removing them would hide why a request cannot be served.
                available=not on_leave,
                meta={"languages": languages, "specialty_id": provider.specialty_id},
            )
        )
    return out


def _sites(cache: Any) -> list[Node]:
    return [
        Node(id=loc.id, kind="site", label=loc.name, detail=getattr(loc, "address", "") or "")
        for loc in getattr(cache, "locations_by_id", {}).values()
    ]


def _specialties(cache: Any) -> list[Node]:
    return [
        Node(id=f"sp:{sp.id}", kind="specialty", label=sp.name)
        for sp in getattr(cache, "specialties_by_id", {}).values()
    ]


def _roles() -> list[Node]:
    return [Node(id=rid, kind="role", label=label, detail=detail) for rid, label, detail in _ROLES]


def _edges(cache: Any) -> list[Edge]:
    """Who works where and who covers what, straight off the catalogue."""
    out: list[Edge] = []
    locations = getattr(cache, "locations_by_name", {})
    for provider in getattr(cache, "providers_by_id", {}).values():
        for name in getattr(provider, "location_names", ()) or ():
            site = locations.get(_key(name))
            if site is not None:
                out.append(Edge(provider.id, site.id, "works_at"))
        if getattr(provider, "specialty_id", None):
            out.append(Edge(provider.id, f"sp:{provider.specialty_id}", "covers"))
    return out


def _key(name: str) -> str:
    from agent.clinic.cache import _fold

    return _fold(name)


def build(cache: Any) -> dict[str, Any]:
    """The whole clinic as nodes, edges and escalation routes.

    Returns plain data, ready to draw. A cold cache yields the roles and the
    escalation map and nothing else, which is honest: those are the parts that
    do not depend on the catalogue being reachable.
    """
    nodes = _roles()
    edges: list[Edge] = []
    if cache is not None and getattr(cache, "warmed", False):
        nodes = _providers(cache) + _sites(cache) + _specialties(cache) + nodes
        edges = _edges(cache)

    escalations = [
        Escalation(reason=reason, target=target, urgency=urgency, detail=detail)
        for reason, (target, urgency, detail) in sorted(_ESCALATION.items())
    ]
    edges = edges + [
        Edge(f"reason:{e.reason}", e.target, "escalates_to", e.detail) for e in escalations
    ]
    return {
        "nodes": [node.__dict__ for node in nodes],
        "edges": [edge.__dict__ for edge in edges],
        "escalations": [esc.__dict__ for esc in escalations],
        "warm": bool(cache is not None and getattr(cache, "warmed", False)),
    }


def who_to_call(reason: str) -> Escalation | None:
    """Who hears about this ending, or None when the reason is not one of ours."""
    route = _ESCALATION.get(reason)
    if route is None:
        return None
    target, urgency, detail = route
    return Escalation(reason=reason, target=target, urgency=urgency, detail=detail)


def missing_reasons() -> frozenset[str]:
    """Reasons the challenge defines that this graph has no route for.

    Checked by a test rather than asserted at import: a new reason appearing in
    the challenge should fail the build loudly, not take the process down on a
    live call.
    """
    return frozenset(deps.CLOSED_REASONS) - frozenset(_ESCALATION)


__all__ = ["URGENCY", "Edge", "Escalation", "Node", "build", "missing_reasons", "who_to_call"]
