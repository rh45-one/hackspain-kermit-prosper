"""Read-only FrontDesk views over the call audit and the configured clinic."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, JsonValue, ValidationError

from agent.clinic.client import ProsperClient
from agent.clinic.errors import ProsperError
from agent.clinic.models import Appointment, PatientMatch
from agent.config import settings

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


class ClinicView(BaseModel):
    patients: list[PatientMatch]
    appointments: list[AppointmentView]


@router.get("/calls")
def calls() -> list[CallView]:
    config = settings()
    now = datetime.now(UTC)
    views = []
    paths = sorted(
        Path(config.calls_dir).glob("*.jsonl"),
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
async def clinic() -> ClinicView:
    config = settings()
    if not config.prosper_api_key:
        raise HTTPException(503, "PROSPER_API_KEY no configurada en el backend")
    client = ProsperClient(config)
    try:
        async with asyncio.timeout(25):
            catalogue, directory = await asyncio.gather(
                client.get_clinic(), client.search_directory()
            )
            providers = {item.id: item.name for item in catalogue.providers}
            locations = {item.id: item.name for item in catalogue.locations}
            types = {item.id: item.name for item in catalogue.appointment_types}
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
                patients=directory.matches,
                appointments=[item for group in groups for item in group],
            )
    except (ProsperError, httpx.HTTPError, TimeoutError, ValidationError) as exc:
        raise HTTPException(502, "No se pudo consultar la clínica configurada") from exc
    finally:
        await client.close()
