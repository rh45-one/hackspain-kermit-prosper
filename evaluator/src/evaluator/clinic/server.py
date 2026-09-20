"""Local clinic + submission receiver.

Serves the Prosper read API over the versioned dataset and implements the
submit contract's deadline rules: 404 unknown call, 410 past the 30-second
window, 409 identical action retry, 422 malformed body (including a bad
national-id check letter). Two extra evaluator-only routes under `/eval/`
open/close call windows and read back the recorded actions.

The agent under test points at this server through PROSPER_API_BASE_URL -
one base URL covers both clinic reads and submissions, exactly like the
official platform.
"""
from __future__ import annotations

import json as _json
import time
from datetime import UTC, datetime
from typing import Annotated, Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from evaluator.clinic.dataset import Dataset
from evaluator.models import OUTCOME_REASONS, ROUTE_FIELDS, ROUTE_TO_VERB, canonical_action
from evaluator.normalize import national_id_check_ok, norm_enum


class _Call:
    __slots__ = ("actions", "attempts", "call_id", "closed_at", "opened_at")

    def __init__(self, call_id: str) -> None:
        self.call_id = call_id
        self.opened_at = time.monotonic()
        self.closed_at: float | None = None
        self.actions: list[dict[str, Any]] = []
        # Every HTTP submit the receiver saw, accepted or not - evidence for
        # the submission_error diagnostic category.
        self.attempts: list[dict[str, Any]] = []


class CallRegistry:
    """Per-call submission window, per the contract's §2 table."""

    def __init__(self, window_seconds: float = 30.0) -> None:
        self.window_seconds = window_seconds
        self.calls: dict[str, _Call] = {}

    def open(self, call_id: str) -> None:
        self.calls[call_id] = _Call(call_id)

    def close(self, call_id: str) -> None:
        call = self.calls.get(call_id)
        if call and call.closed_at is None:
            call.closed_at = time.monotonic()

    def record(self, call_id: str) -> list[dict[str, Any]] | None:
        call = self.calls.get(call_id)
        return list(call.actions) if call else None

    def submit(self, call_id: str, route: str, body: dict[str, Any]) -> tuple[int, dict]:
        call = self.calls.get(call_id)
        if call is None:
            return 404, {"detail": "unknown call_id"}

        def _fail(status: int, detail: str) -> tuple[int, dict]:
            call.attempts.append(
                {"route": route, "status": status, "detail": detail,
                 "at": datetime.now(UTC).isoformat()}
            )
            return status, {"detail": detail}

        if call.closed_at is not None and time.monotonic() - call.closed_at > self.window_seconds:
            return _fail(410, "submission window closed")

        # 422 malformed: required route fields must be present and non-empty.
        missing = [f for f in ROUTE_FIELDS[route] if body.get(f) in (None, "")]
        if missing:
            return _fail(422, f"missing fields: {', '.join(missing)}")
        if route == "register" and not national_id_check_ok(str(body["national_id"])):
            return _fail(422, "national_id check letter does not match digits")
        if route in ("no-action", "escalate") and norm_enum(str(body["reason"])) not in OUTCOME_REASONS:
            return _fail(422, "reason not in the closed vocabulary")

        verb = ROUTE_TO_VERB[route]
        if route == "register":
            record_action = {
                "action": verb,
                "new_patient": {f: body[f] for f in ROUTE_FIELDS[route]},
            }
        else:
            record_action = {"action": verb, **{f: body[f] for f in ROUTE_FIELDS[route]}}

        # An identical action already accepted for this call is a retry.
        if any(canonical_action(a) == canonical_action(record_action) for a in call.actions):
            return _fail(409, "identical action already recorded")
        call.attempts.append(
            {"route": route, "status": 200, "detail": "accepted",
             "at": datetime.now(UTC).isoformat()}
        )
        call.actions.append(record_action)
        return 200, {
            "call_id": call_id,
            "received_at": datetime.now(UTC).isoformat(),
            "record": {"actions": call.actions},
        }


class _OpenCallBody(BaseModel):
    call_id: str


def create_app(dataset: Dataset, api_key: str = "pk-local-eval", window_seconds: float = 30.0) -> FastAPI:
    registry = CallRegistry(window_seconds)
    app = FastAPI(title="Prosper evaluator - local clinic")

    @app.exception_handler(RequestValidationError)
    async def _validation_422(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    async def _auth(x_api_key: str | None = Header(default=None)) -> None:
        if api_key and x_api_key != api_key:
            raise HTTPException(status_code=403, detail="Invalid API key")

    # --- clinic read API -------------------------------------------------------

    @app.get("/eval/identity", dependencies=[Depends(_auth)])
    def identity() -> dict[str, str]:
        return {"service": "evaluator-clinic", "dataset_fingerprint": dataset.fingerprint}

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/directory", dependencies=[Depends(_auth)])
    def directory(
        name: str | None = None,
        national_id: str | None = None,
        phone: str | None = None,
        date_of_birth: str | None = None,
    ) -> dict[str, Any]:
        q = {
            k: v
            for k, v in {
                "name": name,
                "national_id": national_id,
                "phone": phone,
                "date_of_birth": date_of_birth,
            }.items()
            if v is not None
        }
        return dataset.directory(q)

    @app.get("/api/v1/patients/{patient_id}/appointments", dependencies=[Depends(_auth)])
    def appointments(patient_id: str, when: str = "upcoming") -> dict[str, Any]:
        if when not in ("upcoming", "past", "all"):
            raise HTTPException(status_code=422, detail="bad 'when' value")
        return dataset.patient_appointments(patient_id, when)

    @app.get("/api/v1/availability", dependencies=[Depends(_auth)])
    def availability(
        date_from: str,
        date_to: str,
        provider_id: str | None = None,
        specialty_id: str | None = None,
        location_id: str | None = None,
        patient_id: str | None = None,
        insurer: Annotated[list[str] | None, Query()] = None,
        appointment_type_id: str | None = None,
    ) -> dict[str, Any]:
        from datetime import date

        try:
            df = date.fromisoformat(date_from)
            dt = date.fromisoformat(date_to)
        except ValueError:
            raise HTTPException(status_code=422, detail="bad date format") from None
        try:
            return dataset.availability(
                df,
                dt,
                provider_id=provider_id,
                specialty_id=specialty_id,
                location_id=location_id,
                patient_id=patient_id,
                insurers=insurer or None,
                appointment_type_id=appointment_type_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

    @app.get("/api/v1/clinic", dependencies=[Depends(_auth)])
    def clinic() -> dict[str, Any]:
        return dataset.clinic_response()

    @app.get("/api/v1/providers", dependencies=[Depends(_auth)])
    def providers() -> dict[str, Any]:
        return dataset.providers_response()

    @app.get("/api/v1/locations", dependencies=[Depends(_auth)])
    def locations() -> dict[str, Any]:
        return dataset.locations_response()

    @app.get("/api/v1/specialties", dependencies=[Depends(_auth)])
    def specialties() -> dict[str, Any]:
        return dataset.specialties_response()

    @app.get("/api/v1/appointment-types", dependencies=[Depends(_auth)])
    def appointment_types() -> dict[str, Any]:
        return dataset.appointment_types_response()

    @app.get("/api/v1/insurance-plans", dependencies=[Depends(_auth)])
    def insurance_plans() -> dict[str, Any]:
        return dataset.insurance_plans_response()

    # --- submissions ------------------------------------------------------------

    @app.post("/api/v1/submit/{route}", dependencies=[Depends(_auth)])
    async def submit(route: str, request: Request) -> JSONResponse:
        if route not in ROUTE_TO_VERB:
            raise HTTPException(status_code=404, detail="unknown route")
        try:
            body = await request.json()
        except (_json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse(status_code=422, content={"detail": "body is not JSON"})
        if not isinstance(body, dict) or not isinstance(body.get("call_id"), str):
            return JSONResponse(status_code=422, content={"detail": "missing call_id"})
        status, payload = registry.submit(body["call_id"], route, body)
        return JSONResponse(status_code=status, content=payload)

    # --- evaluator control ------------------------------------------------------

    @app.post("/eval/calls")
    def eval_open(body: _OpenCallBody) -> dict[str, str]:
        registry.open(body.call_id)
        return {"call_id": body.call_id, "state": "open"}

    @app.post("/eval/calls/{call_id}/close")
    def eval_close(call_id: str) -> dict[str, str]:
        registry.close(call_id)
        return {"call_id": call_id, "state": "closed"}

    @app.get("/eval/calls/{call_id}/record")
    def eval_record(call_id: str) -> dict[str, Any]:
        record = registry.record(call_id)
        if record is None:
            raise HTTPException(status_code=404, detail="unknown call_id")
        call = registry.calls[call_id]
        return {
            "call_id": call_id,
            "actions": record,
            "attempts": list(call.attempts),
            "closed": call.closed_at is not None,
        }

    @app.get("/eval/calls")
    def eval_calls() -> dict[str, Any]:
        return {
            "calls": [
                {"call_id": c.call_id, "actions": len(c.actions), "closed": c.closed_at is not None}
                for c in registry.calls.values()
            ]
        }

    @app.post("/eval/reset")
    def eval_reset() -> dict[str, str]:
        registry.calls.clear()
        return {"state": "reset"}

    return app


def serve(dataset_path: str, host: str = "127.0.0.1", port: int = 18090, api_key: str = "pk-local-eval") -> None:
    dataset = Dataset.load(dataset_path)
    uvicorn.run(create_app(dataset, api_key=api_key), host=host, port=port, log_level="warning")


__all__ = ["CallRegistry", "create_app", "serve"]
