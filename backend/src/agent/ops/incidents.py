"""Lo que va mal, mientras va mal.

Hasta ahora una llamada que acababa sin cita escribía una línea de auditoría
—`needs_a_human`— en un `.jsonl` dentro del volumen. Eso sirve para
reconstruir la llamada mañana y no sirve para que alguien se entere hoy: el
motivo estaba en el vocabulario cerrado, la persona a la que le tocaba estaba
en la tabla de rutas, y entre las dos no había ningún sitio donde mirar.

Esto es ese sitio. Una incidencia nace de una llamada que escala o de alguien
que la escribe aquí, se le asigna a quien dicen las rutas de la clínica —la
misma persona a la que llamaría el agente, no otra— y vive hasta que alguien
la cierra.

Dos cosas que deliberadamente NO hace:

* **No marca ningún teléfono.** Llamar a alguien es un producto con
  consentimiento y factura; lo que hace falta primero es la cola de gente a
  la que todavía no se ha avisado. El enlace para llamar ya existe, lleva el
  contexto dentro, y lo pulsa una persona.
* **No decide quién debe enterarse cuando ya está decidido.** La ruta
  configurada contesta en microsegundos. Jev sólo entra cuando alguien
  escribe una incidencia a mano y no dice a quién asignársela — que es una
  pantalla, no una llamada, y ahí sí hay tiempo.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from agent.accounts import directory
from agent.accounts import store as accounts_store
from agent.accounts.store import Incident
from agent.orgs import DEFAULT_ORG_ID

router = APIRouter(prefix="/ops/api/live")

# `accounts_store.store` y no `store` a secas: enlazar el nombre en el import
# deja este módulo leyendo la base de verdad aunque alguien —una prueba, otra
# organización— haya cambiado cuál es. Ya pasó con `directory`, y aquí volvió
# a pasar: un test que abría una incidencia veía trece, porque estaba
# escribiendo en la base de este portátil.


def _access(request: Request) -> None:
    from agent.ops.console import require_ops_access

    require_ops_access(request)


class IncidentView(BaseModel):
    """Una incidencia, como la dibuja el panel.

    Lleva el nombre y el cargo de quien tiene que ocuparse además del slug,
    porque una pantalla que dice `andres-vila` obliga a quien la lee a
    traducirlo de cabeza. No lleva su teléfono: el enlace de llamada lo
    resuelve el propio agente, y un número en una respuesta es un número que
    acaba en un registro.
    """

    id: str
    reason: str
    reason_label: str = ""
    summary: str = ""
    assigned_to: str = ""
    assigned_name: str = ""
    assigned_role: str = ""
    urgency: str = "today"
    status: str = "open"
    source: str = "panel"
    call_id: str = ""
    patient: str = ""
    note: str = ""
    created_at: str = ""
    updated_at: str = ""
    closed_at: str | None = None


class NewIncident(BaseModel):
    reason: str = Field(min_length=1, max_length=64)
    summary: str = Field(default="", max_length=2000)
    assigned_to: str = Field(default="", max_length=64)
    urgency: str = Field(default="", max_length=16)
    patient: str = Field(default="", max_length=64)


class StatusChange(BaseModel):
    status: str = Field(pattern="^(open|acknowledged|closed)$")
    note: str = Field(default="", max_length=2000)


def _view(incident: Incident, org_id: str) -> IncidentView:
    from agent.ops.graph import _READABLE

    person = directory.person_for(org_id, incident.assigned_to) if incident.assigned_to else None
    return IncidentView(
        id=incident.id,
        reason=incident.reason,
        reason_label=_READABLE.get(incident.reason, incident.reason),
        summary=incident.summary,
        assigned_to=incident.assigned_to,
        assigned_name=person.name if person else "",
        assigned_role=(person.role if person and person.role != person.slug else ""),
        urgency=incident.urgency,
        status=incident.status,
        source=incident.source,
        call_id=incident.call_id,
        patient=incident.patient,
        note=incident.note,
        created_at=incident.created_at,
        updated_at=incident.updated_at,
        closed_at=incident.closed_at,
    )


@router.get("/incidents")
async def list_incidents(
    request: Request,
    status: str = "",
    org_id: str = DEFAULT_ORG_ID,
    _: None = Depends(_access),
) -> dict[str, Any]:
    """La cola, y el recuento por urgencia para la cabecera."""
    platform = accounts_store.store()
    if not platform.exists:
        return {"incidents": [], "open": 0, "by_urgency": {}}
    rows = platform.list_incidents(org_id, status=status)
    open_rows = [r for r in rows if r.status != "closed"]
    counts: dict[str, int] = {}
    for row in open_rows:
        counts[row.urgency] = counts.get(row.urgency, 0) + 1
    return {
        "incidents": [_view(r, org_id).model_dump() for r in rows],
        "open": len(open_rows),
        "by_urgency": counts,
    }


@router.get("/shifts")
async def cover_shifts(
    request: Request,
    org_id: str = DEFAULT_ORG_ID,
    _: None = Depends(_access),
) -> dict[str, Any]:
    """Los turnos que alguien se ha comprometido a cubrir, por teléfono.

    Lo que una incidencia cerrada no dice: quién está el martes por la mañana.
    """
    platform = accounts_store.store()
    if not platform.exists:
        return {"shifts": []}
    return {
        "shifts": [
            {
                "id": row.id,
                "person_slug": row.person_slug,
                "person_name": row.person_name,
                "covers_when": row.covers_when,
                "site": row.site,
                "instead_of": row.instead_of,
                "reason": row.reason,
                "incident_id": row.incident_id,
                "note": row.note,
                "created_at": row.created_at,
            }
            for row in platform.list_cover_shifts(org_id)
        ]
    }


@router.post("/incidents")
async def open_incident(
    request: Request,
    body: NewIncident,
    org_id: str = DEFAULT_ORG_ID,
    _: None = Depends(_access),
) -> dict[str, Any]:
    """Abre una a mano. Sin destinatario, lo decide la ruta de la clínica."""
    platform = accounts_store.store()
    if not platform.exists:
        raise HTTPException(status_code=503, detail="No hay base de datos en este host.")

    assigned = body.assigned_to
    urgency = body.urgency
    if not assigned or not urgency:
        route = directory.route_for(org_id, body.reason)
        assigned = assigned or (route.person_slug if route else "")
        urgency = urgency or (route.urgency if route else "today")

    row = platform.open_incident(
        org_id,
        Incident(
            id="",
            reason=body.reason,
            summary=body.summary,
            assigned_to=assigned,
            urgency=urgency,
            source="panel",
            patient=body.patient,
        ),
    )
    return _view(row, org_id).model_dump()


@router.post("/incidents/{incident_id}/status")
async def change_status(
    request: Request,
    incident_id: str,
    body: StatusChange,
    org_id: str = DEFAULT_ORG_ID,
    _: None = Depends(_access),
) -> dict[str, Any]:
    platform = accounts_store.store()
    if not platform.exists:
        raise HTTPException(status_code=503, detail="No hay base de datos en este host.")
    row = platform.set_incident_status(org_id, incident_id, body.status, note=body.note)
    if row is None:
        raise HTTPException(status_code=404, detail="Esa incidencia no existe aquí.")
    return _view(row, org_id).model_dump()


# ---- el simulador ---------------------------------------------------------
# Incidencias falsas, para ver el reparto funcionando sin esperar a que se
# rompa algo de verdad. Cada una es una frase como la diría una persona, no
# un identificador: es justo lo que Jev tiene que leer para decidir a quién
# le toca, y escribir "provider_on_leave" sería darle la respuesta hecha.
_SIMULATED: tuple[tuple[str, str], ...] = (
    ("provider_on_leave", "El jefe de ginecología se ha puesto malo y el lunes tiene consulta llena"),
    ("provider_on_leave", "Hugo está de vacaciones toda la semana y hay pacientes de otorrino el martes"),
    ("medical_emergency", "Un paciente ha llamado con dolor en el pecho y le cuesta respirar"),
    ("medical_emergency", "Una embarazada de ocho meses dice que ha roto aguas"),
    ("no_availability", "Tres pacientes de traumatología sin hueco esta semana"),
    ("provider_on_leave", "Marina no puede venir el jueves y hay dos primeras visitas de psiquiatría"),
    ("no_availability", "Un niño con fiebre alta y pediatría con la agenda cerrada"),
    ("caller_not_authorised", "Un hombre pide el historial de su mujer y no está autorizado"),
    ("patient_history", "El historial de una paciente desaconseja la prueba que ha pedido"),
    ("clinic_closed", "Han llamado a las once de la noche y nadie ha cogido el teléfono"),
    ("allowance_exhausted", "A un paciente se le han agotado las visitas del plan y quiere otra cita"),
    ("provider_on_leave", "Jose está de baja y hay consultas de podología toda la mañana"),
    ("no_availability", "Se ha caído una consulta de cardiología y hay cuatro pacientes esperando"),
    ("provider_on_leave", "La matrona no llega al turno de tarde"),
)


async def _jev_assigns(org_id: str, situation: str) -> tuple[str, float, str]:
    """A quién le toca esto, según Jev. Vacío cuando no lo tiene claro.

    Va aquí y no en una llamada por la misma razón de siempre: una lectura de
    Jev son unos 600 ms, y al otro lado de una llamada puntuable hay una
    persona esperando en silencio. Al otro lado de una incidencia no hay
    nadie esperando.
    """
    try:
        from agent.brain.tools import _build_jev_client
        from agent.config import settings
        from agent.ops.cover import _describe

        people = [p for p in directory.people_for(org_id) if p.active]
        if not people:
            return "", 0.0, "sin gente"
        client = _build_jev_client(settings())
        if client is None:
            return "", 0.0, "sin sidecar"
        names = {p.slug: p.name for p in people}
        choice = await client.choose_cover(
            situation, {p.slug: _describe(p, names) for p in people}, timeout_seconds=1.5
        )
        return (choice.slug or ""), choice.confidence, choice.why
    except Exception:  # noqa: BLE001 - la ruta configurada siempre contesta
        return "", 0.0, "error"


@router.post("/incidents/simulate")
async def simulate_incident(
    request: Request,
    org_id: str = DEFAULT_ORG_ID,
    _: None = Depends(_access),
) -> dict[str, Any]:
    """Lanza una incidencia falsa y deja que Jev decida a quién le toca.

    La gracia de verla repartir está en que la frase llega en castellano y la
    persona sale del turno de esta clínica — no de una tabla de ejemplos. Si
    Jev no lo tiene claro contesta la ruta configurada, y la respuesta dice
    cuál de las dos ha decidido, que es la mitad de lo que hay que enseñar.
    """
    import random

    platform = accounts_store.store()
    if not platform.exists:
        raise HTTPException(status_code=503, detail="No hay base de datos en este host.")

    reason, summary = random.choice(_SIMULATED)
    route = directory.route_for(org_id, reason)
    fallback = route.person_slug if route else ""
    urgency = route.urgency if route else "today"

    chosen, confidence, why = await _jev_assigns(org_id, summary)
    assigned = chosen or fallback

    row = platform.open_incident(
        org_id,
        Incident(
            id="",
            reason=reason,
            summary=summary,
            assigned_to=assigned,
            urgency=urgency,
            source="simulador",
            note=(
                f"Jev: {confidence:.2f}" if chosen else f"Ruta configurada ({why})"
            ),
        ),
    )
    view = _view(row, org_id).model_dump()
    view["decided_by"] = "jev" if chosen else "route"
    view["confidence"] = round(confidence, 3)
    view["fallback"] = fallback
    return view


__all__ = ["router"]
