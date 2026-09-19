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

from agent.accounts import directory
from agent.brain import deps
from agent.orgs import DEFAULT_ORG_ID

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


# Del cargo a la disciplina. Las reglas cubren casi todo el cuadro médico y
# el diccionario está para lo que no se deja: un jefe de servicio no es una
# especialidad llamada "Jefe de Ginecología".
_DISCIPLINE_OF: dict[str, str] = {
    "jefe de ginecologia": "Ginecología",
    "ginecologo jr.": "Ginecología",
    "medicina general": "Medicina general",
    "guardia": "Guardia",
    "mostrador": "Recepción",
    "coordinacion": "Coordinación",
    "urgencias": "Urgencias",
    "intensivos": "Medicina intensiva",
    "matrona": "Obstetricia",
    "enfermeria": "Enfermería",
    "farmacia": "Farmacia",
    "administracion": "Administración",
    "trabajo social": "Trabajo social",
    "analisis clinicos": "Análisis clínicos",
    "nutricionista": "Nutrición",
    # Las que ninguna regla acierta. "Fisioterapeuta" con la regla de `-euta`
    # sale "Fisioterapapia", que no es una palabra y además no casa con la
    # "Fisioterapia" que ya publica el catálogo — o sea que además de fea
    # habría duplicado la disciplina.
    "fisioterapeuta": "Fisioterapia",
    "anestesista": "Anestesia",
    "digestiva": "Aparato digestivo",
    "digestivo": "Aparato digestivo",
    "endocrino": "Endocrinología",
    "endocrina": "Endocrinología",
}


def _discipline_name(role: str) -> str:
    """"Otorrinolaringólogo" -> "Otorrinolaringología". Una persona no es una
    disciplina, y la columna de la derecha es de disciplinas.

    Las tres reglas cubren el castellano médico casi entero: `-ólogo/-óloga`
    da `-ología`, `-iatra` da `-iatría` y `-euta` da `-apia`. Lo que no encaja
    en ninguna sale tal cual, que es mejor que una palabra inventada.
    """
    from agent.clinic.cache import _fold

    key = _fold(role)
    if key in _DISCIPLINE_OF:
        return _DISCIPLINE_OF[key]
    lowered = role.strip()
    for ending, replacement in (("ólogo", "ología"), ("óloga", "ología"),
                                ("iatra", "iatría"), ("terapeuta", "terapia")):
        if lowered.lower().endswith(ending):
            return lowered[: -len(ending)] + replacement
    return lowered


def _staff(org_id: str, cache: Any) -> tuple[list[Node], list[Edge]]:
    """La plantilla de la clínica, en el mismo mapa que el catálogo.

    El catálogo que publica Prosper tiene doce profesionales y es de Prosper:
    no se le pueden añadir personas. Pero la clínica tiene las suyas, con su
    cargo escrito, y hasta ahora sólo salían en la capa de escalados — así
    que "la clínica entera de un vistazo" enseñaba doce médicos de una
    plantilla de cuarenta y dos, y de los compañeros de uno, ninguno.

    Se dibujan como profesionales, porque eso es lo que son, con
    `meta.source = "plantilla"` para que el panel pueda distinguirlos de los
    que vienen del catálogo. Su disciplina sale de su cargo, y cuando esa
    disciplina ya existe en el catálogo se reutiliza el nodo en vez de crear
    uno al lado con el mismo nombre.
    """
    from agent.clinic.cache import _fold

    catalogue_specialties = {
        _fold(getattr(sp, "name", "")): f"sp:{sp.id}"
        for sp in (getattr(cache, "specialties_by_id", {}) or {}).values()
    }
    nodes: list[Node] = []
    edges: list[Edge] = []
    invented: dict[str, Node] = {}

    for person in directory.people_for(org_id):
        # Los cuatro declarados a mano ya son nodos de la capa de escalados, y
        # su "cargo" es su propio identificador. 112 no es un profesional.
        if getattr(person, "source", "") == "default":
            continue
        # Quien ya está en el catálogo sale de ahí, con sus sedes y su semana.
        # Dibujarlo otra vez sería la misma persona dos veces.
        if person.provider_id:
            continue
        discipline = _discipline_name(person.role)
        key = _fold(discipline)
        target = catalogue_specialties.get(key)
        if target is None:
            target = f"sp:plantilla:{key.replace(' ', '-')}"
            if key not in invented:
                invented[key] = Node(id=target, kind="specialty", label=discipline)
        nodes.append(
            Node(
                id=f"staff:{person.slug}",
                kind="provider",
                label=person.name,
                detail=person.role,
                meta={
                    "languages": list(person.languages or ()),
                    "specialty_id": target.removeprefix("sp:"),
                    # De dónde sale esta persona. El panel lo usa para no
                    # decir que el catálogo publica a alguien que no publica.
                    "source": "plantilla",
                    "slug": person.slug,
                },
            )
        )
        edges.append(Edge(f"staff:{person.slug}", target, "covers"))
    return nodes + list(invented.values()), edges


def _roles(org_id: str) -> list[Node]:
    """The people who answer, from this organisation's directory.

    `_ROLES` below is still the only place the four defaults are written down;
    the directory reads them and lets a clinic replace any of them by name. A
    fifth role added there appears here the same day.
    """
    return [
        Node(id=rid, kind="role", label=label, detail=detail)
        for rid, label, detail in directory.escalation_targets(org_id)
    ]


def _cover_edges(org_id: str) -> list[Edge]:
    """Who steps in for whom, drawn as an edge because that is what it is.

    Until now this lived in one column of one table and appeared nowhere on
    screen, so the second line of the rota was invisible: you could see that
    `provider_on_leave` reaches Germán, and nothing told you who reaches when
    Germán is the one who is off.

    An edge is only drawn when both ends exist. A chain pointing at somebody
    who has left is a thing the panel should be able to report as broken, and
    `directory.unreachable_routes` is where that belongs — not here, where a
    dangling edge would draw a line to a node that is not on the canvas.
    """
    people = directory.people_for(org_id)
    known = {person.slug for person in people}
    return [
        Edge(person.slug, person.covers_for, "covers_for")
        for person in people
        if getattr(person, "covers_for", "") and person.covers_for in known
    ]


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


def build(cache: Any, org_id: str = "") -> dict[str, Any]:
    """The whole clinic as nodes, edges and escalation routes.

    Returns plain data, ready to draw. A cold cache yields the roles and the
    escalation map and nothing else, which is honest: those are the parts that
    do not depend on the catalogue being reachable.
    """
    org_id = org_id or DEFAULT_ORG_ID
    nodes = _roles(org_id)
    edges: list[Edge] = []
    if cache is not None and getattr(cache, "warmed", False):
        nodes = _providers(cache) + _sites(cache) + _specialties(cache) + nodes
        edges = _edges(cache)
    # La plantilla se dibuja haya catálogo o no: es de la clínica, no de la
    # API, así que un catálogo frío no es motivo para esconder a su gente.
    staff_nodes, staff_edges = _staff(org_id, cache)
    nodes = staff_nodes + nodes
    edges = edges + staff_edges

    escalations = [
        Escalation(reason=reason, target=target, urgency=urgency, detail=detail)
        for reason, (target, urgency, detail) in sorted(
            directory.escalation_routes(org_id).items()
        )
    ]
    edges = edges + _cover_edges(org_id) + [
        Edge(f"reason:{e.reason}", e.target, "escalates_to", e.detail) for e in escalations
    ]
    return {
        "nodes": [node.__dict__ for node in nodes],
        "edges": [edge.__dict__ for edge in edges],
        "escalations": [esc.__dict__ for esc in escalations],
        "warm": bool(cache is not None and getattr(cache, "warmed", False)),
    }


def who_to_call(reason: str, org_id: str = "") -> Escalation | None:
    """Who hears about this ending, or None when the reason is not one of ours."""
    route = directory.escalation_route(org_id or DEFAULT_ORG_ID, reason)
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
    return frozenset(deps.CLOSED_REASONS) - frozenset(
        directory.escalation_routes(DEFAULT_ORG_ID)
    )


__all__ = ["URGENCY", "Edge", "Escalation", "Node", "build", "missing_reasons", "who_to_call"]
