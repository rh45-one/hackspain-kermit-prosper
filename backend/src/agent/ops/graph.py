"""The clinic graph, served for drawing.

Read-only, behind the same ops door as everything else here. Nothing in it is
patient data: it is the shape of the clinic — who works where, who covers what,
and who hears about each of the eighteen ways a call can end without a booking.

The graph itself is computed in `agent.clinic.graph` off the catalogue this
process already holds. This module only shapes it for a screen and adds the
one thing a drawing needs that a graph does not: where to put things.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from agent.clinic import graph as clinic_graph
from agent.orgs import DEFAULT_ORG_ID

router = APIRouter(prefix="/ops/api/live")

# What each kind of node means on screen. The colours are named, not chosen:
# a panel that invents its own palette per component drifts the first time
# somebody adds a node kind.
_LAYERS: dict[str, dict[str, Any]] = {
    "role": {"layer": 0, "tone": "human", "title": "Quién responde"},
    "specialty": {"layer": 1, "tone": "discipline", "title": "Especialidades"},
    "provider": {"layer": 2, "tone": "person", "title": "Profesionales"},
    "site": {"layer": 3, "tone": "place", "title": "Sedes"},
    "reason": {"layer": 0, "tone": "failure", "title": "Qué puede fallar"},
}


def _access(request: Request) -> None:
    """The ops door. Imported lazily because console registers this router."""
    from agent.ops.console import require_ops_access

    require_ops_access(request)


async def _cache() -> Any | None:
    """The shared catalogue, warmed at startup by the server's lifespan."""
    try:
        from agent.brain import deps
        from agent.config import settings

        cache = deps.try_catalogue_cache(DEFAULT_ORG_ID)
        if cache is None:
            return None
        if not cache.warmed:
            client = deps.try_clinic_client(settings())
            if client is not None:
                await deps.warm_shared_catalogue(client, DEFAULT_ORG_ID)
        return cache
    except Exception:  # noqa: BLE001 - a cold catalogue draws less, never 500s
        return None


@router.get("/graph")
async def clinic_map(_: None = Depends(_access)) -> dict[str, Any]:
    """The whole clinic, ready to draw.

    Every failure mode is a node of its own here, which it is not in the graph
    itself. On a screen an escalation is a thing you point at — "this is what
    happens when there is no slot" — and a drawing needs it to exist before it
    can be pointed at.
    """
    built = clinic_graph.build(await _cache(), DEFAULT_ORG_ID)

    nodes = [{**node, **_LAYERS.get(node["kind"], {})} for node in built["nodes"]]
    nodes += [
        {
            "id": f"reason:{esc['reason']}",
            "kind": "reason",
            "label": _READABLE.get(esc["reason"], esc["reason"]),
            "detail": esc["detail"],
            "available": True,
            "meta": {"urgency": esc["urgency"], "reason": esc["reason"]},
            **_LAYERS["reason"],
        }
        for esc in built["escalations"]
    ]

    return {
        "nodes": nodes,
        "edges": built["edges"],
        "escalations": built["escalations"],
        "warm": built["warm"],
        "legend": {
            "kinds": _LAYERS,
            "urgency": {
                "now": "Interrumpe a alguien ahora.",
                "today": "Le llega antes de que termine el día.",
                "queue": "Espera a que alguien lo mire.",
            },
        },
    }


# The challenge's vocabulary is English and belongs to the API. A person
# reading a screen is not, so the label is translated and the id travels
# untouched underneath it in `meta.reason`.
_READABLE: dict[str, str] = {
    "medical_emergency": "Urgencia médica",
    "caller_not_authorised": "Pide datos de otro",
    "patient_history": "Lo impide el historial",
    "out_of_scope": "No es cosa de la agenda",
    "no_availability": "Sin hueco",
    "provider_on_leave": "Médico de baja",
    "location_hours": "Sede cerrada a esa hora",
    "clinic_closed": "Clínica cerrada",
    "specialty_not_covered": "El plan no cubre la especialidad",
    "location_not_covered": "El plan no cubre la sede",
    "provider_not_in_network": "El médico no acepta el plan",
    "insurer_referral_required": "La aseguradora pide volante",
    "allowance_exhausted": "Visitas agotadas",
    "referral_required": "Hace falta volante",
    "not_eligible_age": "Fuera del rango de edad",
    "type_not_offered": "Ese tipo de cita no existe ahí",
    "patient_not_found": "No está en el fichero",
    "provider_not_found": "Ese médico no existe aquí",
}
