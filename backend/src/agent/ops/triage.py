"""Por qué es más probable que llame cada paciente.

Una lista de pacientes ordenada por apellido no dice nada que quien la mira
no supiera ya. (Y "la lista" no existe: el directorio de Prosper es una API
de búsqueda, no un volcado, así que esto trabaja sobre lo que se busca.) Lo que hace falta antes de abrir la agenda de mañana es a
quién conviene mirar: quién tiene un volante sin usar, quién viene cada tres
meses, quién es un adulto sano que no ha venido nunca.

Eso lo decide Jev sobre una elección cerrada de las especialidades que ESTA
clínica ofrece, leídas del catálogo. No se inventa especialidades y no puede
contestar una que no exista aquí.

**La abstención es el caso normal y es la mitad del valor.** Un adulto sano
sin historial no apunta a ninguna parte, y una columna que contesta
"cardiología" para todo el mundo parece conocimiento y es ruido. Cuando Jev
no ve nada, la fila se queda en blanco y lo dice.

Nada de esto toca una llamada. Es una pantalla, y una pantalla tiene todo el
tiempo del mundo.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request

from agent.orgs import DEFAULT_ORG_ID

router = APIRouter(prefix="/ops/api/live")

# Cuántos pacientes se miran de una tanda. Jev tarda medio segundo largo por
# lectura y van en paralelo, pero una lista de doscientos pacientes son
# doscientas peticiones a un servicio que no es nuestro.
MAX_PATIENTS = 24


def _access(request: Request) -> None:
    from agent.ops.console import require_ops_access

    require_ops_access(request)


def _record_of(patient: Any) -> str:
    """El historial en una frase, que es lo que Jev lee.

    Sin nombre, sin documento y sin teléfono: para decidir una especialidad
    no hacen falta, y lo que no se manda no se puede filtrar mal en el otro
    extremo.
    """
    bits: list[str] = []
    born = str(getattr(patient, "date_of_birth", "") or "")
    if born[:4].isdigit():
        bits.append(f"nacido en {born[:4]}")
    if getattr(patient, "sex", ""):
        bits.append(str(patient.sex))
    if getattr(patient, "insurer", ""):
        bits.append(f"plan {patient.insurer}")
    bits.append(
        "ya ha venido antes" if getattr(patient, "has_visited_before", False) else "nunca ha venido"
    )
    referrals = [str(r) for r in (getattr(patient, "referrals", None) or [])]
    if referrals:
        bits.append("volantes en vigor: " + ", ".join(referrals))
    note = str(getattr(patient, "note", "") or "")
    if note:
        bits.append(note)
    return ". ".join(bits)


@router.get("/triage")
async def triage(
    request: Request,
    name: str = "",
    national_id: str = "",
    org_id: str = DEFAULT_ORG_ID,
    limit: int = MAX_PATIENTS,
    _: None = Depends(_access),
) -> dict[str, Any]:
    """Los pacientes que salen de una búsqueda, cada uno con su especialidad.

    Sobre una búsqueda y no sobre "todos los pacientes", porque no existe tal
    cosa: el directorio de Prosper es una API de búsqueda, no un volcado.
    Pedir un listado completo sería inventarse un endpoint que no está — y
    una pantalla construida sobre un endpoint imaginario se cae el día de la
    demo, no antes.
    """
    from agent.brain import deps
    from agent.brain.tools import _build_jev_client
    from agent.clinic.client import ProsperClient
    from agent.config import settings

    name, national_id = name.strip(), national_id.strip()
    if not name and not national_id:
        return {"patients": [], "asked": False}

    config = settings()
    cache = deps.try_catalogue_cache(org_id)
    specialties = {
        str(sp.id): str(getattr(sp, "name", "") or sp.id)
        for sp in (getattr(cache, "specialties_by_id", {}) or {}).values()
    }
    if not config.prosper_api_key or not specialties:
        return {"patients": [], "asked": True, "warm": bool(specialties)}

    try:
        async with asyncio.timeout(25):
            found = await ProsperClient(config).search_directory(
                name=name or None, national_id=national_id or None
            )
    except Exception:  # noqa: BLE001 - una pantalla no cae por una búsqueda
        return {"patients": [], "asked": True, "warm": True}

    patients = list(found.matches)[: max(1, min(limit, 60))]
    client = _build_jev_client(config)
    if not patients or client is None:
        return {"patients": [], "asked": True, "warm": True}

    from agent.accounts import store as accounts_store
    from agent.accounts.store import PatientRow

    platform = accounts_store.store()

    def remember(patient: Any, specialty: str, confidence: float) -> None:
        """Deja al paciente en la tabla de la clínica, con lo que Jev cree.

        Sin documento ni teléfono. La misma regla que `PatientCard`: esta
        base acaba dentro de una copia de seguridad.
        """
        try:
            if not platform.exists:
                return
            platform.remember_patient(
                org_id,
                PatientRow(
                    patient_id=str(getattr(patient, "patient_id", "") or ""),
                    given_name=str(getattr(patient, "given_name", "") or ""),
                    first_surname=str(getattr(patient, "first_surname", "") or ""),
                    second_surname=str(getattr(patient, "second_surname", "") or ""),
                    date_of_birth=str(getattr(patient, "date_of_birth", "") or ""),
                    sex=str(getattr(patient, "sex", "") or ""),
                    insurer=str(getattr(patient, "insurer", "") or ""),
                    has_visited_before=bool(getattr(patient, "has_visited_before", False)),
                    referrals=tuple(str(r) for r in (getattr(patient, "referrals", None) or [])),
                    note=str(getattr(patient, "note", "") or ""),
                    likely_specialty=specialty,
                    likely_confidence=confidence,
                ),
            )
        except Exception:  # noqa: BLE001 - una tabla no tumba una pantalla
            return

    async def one(patient: Any) -> dict[str, Any]:
        choice = await client.triage_patient(
            _record_of(patient), specialties, timeout_seconds=2.0
        )
        remember(patient, specialties.get(choice.slug or "", ""), choice.confidence)
        return {
            "patient_id": str(getattr(patient, "patient_id", "") or ""),
            # El nombre para poder casarlo con la tabla; nunca el documento
            # ni el teléfono, que es la misma regla que sigue `PatientCard`.
            "name": " ".join(
                str(getattr(patient, part, "") or "")
                for part in ("given_name", "first_surname", "second_surname")
            ).strip(),
            "specialty_id": choice.slug or "",
            "specialty": specialties.get(choice.slug or "", ""),
            "confidence": round(choice.confidence, 3),
            "why": choice.why,
        }

    rows = await asyncio.gather(*(one(p) for p in patients), return_exceptions=True)
    return {
        "patients": [r for r in rows if isinstance(r, dict)],
        "asked": True,
        "warm": True,
        "specialties": [{"id": k, "name": v} for k, v in specialties.items()],
    }


@router.get("/patients")
async def patients(
    request: Request,
    q: str = "",
    org_id: str = DEFAULT_ORG_ID,
    _: None = Depends(_access),
) -> dict[str, Any]:
    """Los pacientes que esta clínica ha visto, filtrables.

    Esta tabla empieza vacía y se llena sola: cada persona que una llamada
    busca y cada resultado de una búsqueda del panel. Es lo que hace una
    clínica de verdad su primer día, y es la única tabla honesta que se puede
    construir sobre una API que no exporta pacientes.
    """
    from agent.accounts import store as accounts_store

    platform = accounts_store.store()
    if not platform.exists:
        return {"patients": [], "total": 0}
    rows = platform.list_patients(org_id, query=q)
    return {
        "patients": [
            {
                "patient_id": row.patient_id,
                "name": row.name,
                "date_of_birth": row.date_of_birth,
                "sex": row.sex,
                "insurer": row.insurer,
                "has_visited_before": row.has_visited_before,
                "referrals": list(row.referrals),
                "note": row.note,
                "likely_specialty": row.likely_specialty,
                "likely_confidence": round(row.likely_confidence, 3),
                "times_seen": row.times_seen,
                "last_seen_at": row.last_seen_at,
            }
            for row in rows
        ],
        "total": len(rows),
    }


__all__ = ["router"]
