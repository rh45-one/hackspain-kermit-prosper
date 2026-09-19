"""Read-only FrontDesk views over the call audit and the configured clinic."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, JsonValue, ValidationError

from agent.clinic.client import ProsperClient
from agent.clinic.errors import ClinicValidationError, ProsperError
from agent.clinic.models import Appointment, PatientMatch
from agent.config import settings
from agent.orgs import DEFAULT_ORG_ID

router = APIRouter(prefix="/ops/api/frontdesk")


class AuditEvent(BaseModel):
    ts: datetime
    event: str
    data: dict[str, JsonValue] = Field(default_factory=dict)


class TranscriptLine(BaseModel):
    role: Literal["agent", "caller"]
    text: str


class CallView(BaseModel):
    callId: str
    socketId: str = "—"
    virtualPhone: str = "—"
    status: Literal["active", "ended", "unknown"]
    turn: Literal["listening", "speaking"] = "listening"
    startedAt: datetime
    transcript: list[TranscriptLine] = Field(default_factory=list)
    script: list[TranscriptLine] = Field(default_factory=list)
    entities: dict[str, str] = Field(default_factory=dict)
    diagnostic: dict[str, JsonValue] | None = None


class AppointmentView(Appointment):
    provider_name: str
    location_name: str
    appointment_type_name: str
    action: Literal["BOOK"] = "BOOK"


async def _warm_catalogue() -> Any | None:
    """The shared catalogue cache, warmed once if nobody has warmed it yet.

    Inside `agent.serve` the server's lifespan has already warmed this exact
    object, so this fetches nothing at all. `live.py` does the same thing for
    the same reason.
    """
    try:
        from agent.brain import deps

        cache = deps.try_catalogue_cache(DEFAULT_ORG_ID)
        if cache is None:
            return None
        if not cache.warmed:
            client = deps.try_clinic_client(settings())
            if client is not None:
                await deps.warm_shared_catalogue(client, DEFAULT_ORG_ID)
        return cache
    except Exception:  # noqa: BLE001 - a cold cache degrades to ids, never a 500
        return None


def _names(cache: Any | None, kind: str) -> dict[str, str]:
    """id -> display name, or an empty map when the cache is cold."""
    index = getattr(cache, f"{kind}_by_id", None) if cache is not None else None
    return {key: getattr(item, "name", key) for key, item in (index or {}).items()}


class PatientCard(BaseModel):
    """A patient as a person at a front desk needs to see them.

    Deliberately not `PatientMatch`, which carries `national_id` and `phone`
    in clear. This panel is published, so serving those would put a patient's
    id one URL and one token away from the internet — and the sibling module
    `live.py` redacts exactly those two from transcripts on purpose. Two views
    of the same data cannot disagree about it.

    The name stays, because it is how a person knows who they are looking at
    and the challenge's privacy rules protect the id and the telephone, never
    the name. The date of birth stays with it: two patients share a name often
    enough that without it the card identifies nobody, and it is what the
    agent itself asks for on the line.
    """

    patient_id: str
    given_name: str
    first_surname: str
    second_surname: str
    date_of_birth: str
    sex: str
    has_visited_before: bool
    insurer: str
    referrals: list[str] = []
    note: str = ""

    @classmethod
    def of(cls, match: PatientMatch) -> PatientCard:
        return cls(**match.model_dump(include=set(cls.model_fields)))


class ClinicView(BaseModel):
    patients: list[PatientCard]
    appointments: list[AppointmentView]


def _gated(request: Request) -> None:
    """Same door as the rest of /ops. Written here so no route can forget it.

    These views serve whole transcripts, and a caller dictates their national
    id and telephone aloud during a registration. Imported lazily because
    console.py registers this router, and a module-level import would be a
    cycle.
    """
    from agent.ops.console import require_ops_access

    require_ops_access(request)


@router.get("/calls")
def calls(_: None = Depends(_gated)) -> list[CallView]:
    config = settings()
    now = datetime.now(UTC)
    views = []
    # Both layouts for the default organisation: the traces recorded before
    # organisations existed are still the only record of 190-odd scored calls.
    paths = sorted(
        config.call_trace_paths(DEFAULT_ORG_ID),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:30]
    for path in paths:
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = AuditEvent.model_validate_json(line)
                if event.ts.tzinfo is not None:
                    events.append(event)
            except ValidationError:
                continue
        if not events:
            continue
        ended = any(e.event in {"socket_stop", "flush_done"} for e in events)
        recent = (now - events[-1].ts).total_seconds() <= config.max_call_minutes * 60
        view = CallView(
            callId=path.stem,
            status="ended" if ended else "active" if recent else "unknown",
            startedAt=events[0].ts,
        )
        for event in events:
            if event.event == "transcript":
                role, text = event.data.get("role"), event.data.get("text")
                if role in ("caller", "assistant") and isinstance(text, str):
                    view.transcript.append(
                        TranscriptLine(role="agent" if role == "assistant" else "caller", text=text)
                    )
                    view.turn = "speaking" if role == "assistant" else "listening"
            elif event.event == "call_outcome_summary":
                view.diagnostic = event.data
        views.append(view)
    return sorted(views, key=lambda view: view.status != "active")


@router.get("/clinic")
async def clinic(
    name: str = "", national_id: str = "", _: None = Depends(_gated)
) -> ClinicView:
    config = settings()
    if not config.prosper_api_key:
        raise HTTPException(503, "PROSPER_API_KEY no configurada en el backend")
    name, national_id = name.strip(), national_id.strip()
    # The official directory is a search API, not a full patient export.
    if not name and not national_id:
        return ClinicView(patients=[], appointments=[])
    if name and len(name.split()) < 2:
        raise HTTPException(422, "Introduce el nombre y al menos un apellido")
    client = ProsperClient(config)
    try:
        async with asyncio.timeout(25):
            # The catalogue is NOT fetched here. It was, once per request: 30 KB
            # off the challenge API to build three id-to-name dictionaries that
            # are already indexed in the process-wide cache, warmed at startup
            # and immutable for the life of the event. A panel that polls would
            # have made a round trip to Prosper on every poll. Only the
            # directory search is live, because only it can change.
            directory = await client.search_directory(
                name=name or None, national_id=national_id or None
            )
            cache = await _warm_catalogue()
            providers = _names(cache, "providers")
            locations = _names(cache, "locations")
            types = _names(cache, "types")
            semaphore = asyncio.Semaphore(4)

            async def appointments_for(patient: PatientMatch) -> list[AppointmentView]:
                async with semaphore:
                    response = await client.list_appointments(patient.patient_id, when="all")
                return [
                    AppointmentView(
                        **item.model_dump(),
                        provider_name=providers.get(item.provider_id, item.provider_id),
                        location_name=locations.get(item.location_id, item.location_id),
                        appointment_type_name=types.get(
                            item.appointment_type_id, item.appointment_type_id
                        ),
                    )
                    for item in response.appointments
                ]

            groups = await asyncio.gather(*(appointments_for(p) for p in directory.matches))
            return ClinicView(
                patients=[PatientCard.of(m) for m in directory.matches],
                appointments=[item for group in groups for item in group],
            )
    except ClinicValidationError as exc:
        raise HTTPException(422, "Revisa el nombre y apellido o el documento completo") from exc
    except (ProsperError, httpx.HTTPError, TimeoutError, ValidationError) as exc:
        raise HTTPException(502, "No se pudo consultar la clínica configurada") from exc
    finally:
        await client.close()
