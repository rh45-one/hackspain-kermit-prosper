"""Async client for the read-only Prosper clinic API.

Every request carries X-Api-Key. Errors are typed: 403 → ProsperAuthError,
404 → NotFoundError, 422 → ClinicValidationError, 429 → RateLimitedError.
GET requests retry only on transport failures and 5xx — never on typed
client errors, which are deterministic and must surface immediately.
"""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import httpx

from agent.clinic.errors import (
    ClinicValidationError,
    NotFoundError,
    ProsperAuthError,
    ProsperError,
    RateLimitedError,
)
from agent.clinic.models import (
    AppointmentsResponse,
    AvailabilityResponse,
    ClinicCatalogue,
    DirectoryResponse,
)

_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})


class ProsperClient:
    """Thin httpx wrapper: X-Api-Key auth, typed errors, GET retries.

    `transport` exists for offline tests (httpx.MockTransport); production
    leaves it None and gets a plain AsyncClient.
    """

    def __init__(
        self,
        settings: Any,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = settings.prosper_api_base_url.rstrip("/")
        self._api_key = settings.prosper_api_key
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={"X-Api-Key": self._api_key},
                timeout=httpx.Timeout(20.0, connect=10.0),
                transport=self._transport,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        retries: int = 2,
    ) -> dict[str, Any]:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                response = await self._http().get(path, params=clean)
                if response.status_code == 200:
                    return response.json()
                if response.status_code == 403:
                    raise ProsperAuthError("invalid API key (403)")
                if response.status_code == 404:
                    raise NotFoundError(f"{path}: not found (404)")
                if response.status_code == 422:
                    raise ClinicValidationError(f"{path}: {response.text[:200]}")
                if response.status_code == 429:
                    raise RateLimitedError("rate limited (429)")
                if response.status_code in _RETRYABLE_STATUS:
                    last_exc = ProsperError(f"{path}: server error {response.status_code}")
                else:
                    raise ProsperError(
                        f"{path}: unexpected {response.status_code}: {response.text[:200]}"
                    )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
            if attempt < retries:
                await asyncio.sleep(0.25 * (2**attempt))
        raise last_exc or ProsperError(f"{path}: failed")

    # ---- catalogue (immutable, cacheable) --------------------------------
    async def health(self) -> dict[str, Any]:
        return await self._get("/api/v1/health", retries=0)

    async def get_clinic(self) -> ClinicCatalogue:
        return ClinicCatalogue.model_validate(await self._get("/api/v1/clinic"))

    async def list_providers(self) -> dict[str, Any]:
        return await self._get("/api/v1/providers")

    async def list_locations(self) -> dict[str, Any]:
        return await self._get("/api/v1/locations")

    async def list_specialties(self) -> dict[str, Any]:
        return await self._get("/api/v1/specialties")

    async def list_appointment_types(self) -> dict[str, Any]:
        return await self._get("/api/v1/appointment-types")

    async def list_insurance_plans(self) -> dict[str, Any]:
        return await self._get("/api/v1/insurance-plans")

    # ---- per-caller lookups ---------------------------------------------
    async def search_directory(
        self,
        name: str | None = None,
        phone: str | None = None,
        national_id: str | None = None,
        date_of_birth: str | None = None,
    ) -> DirectoryResponse:
        """An exact field that does not match excludes the patient; it never downranks."""
        params: dict[str, Any] = {}
        if name:
            params["name"] = name
        if phone:
            params["phone"] = phone
        if national_id:
            params["national_id"] = national_id
        if date_of_birth:
            params["date_of_birth"] = date_of_birth
        return DirectoryResponse.model_validate(await self._get("/api/v1/directory", params))

    async def list_appointments(self, patient_id: str, when: str = "upcoming") -> AppointmentsResponse:
        if when not in ("upcoming", "past", "all"):
            raise ClinicValidationError(f"appointments when={when!r}: use upcoming|past|all")
        return AppointmentsResponse.model_validate(
            await self._get(f"/api/v1/patients/{patient_id}/appointments", {"when": when})
        )

    async def search_availability(
        self,
        date_from: date,
        date_to: date,
        provider_id: str | None = None,
        specialty_id: str | None = None,
        location_id: str | None = None,
        patient_id: str | None = None,
        insurer: list[str] | str | None = None,
    ) -> AvailabilityResponse:
        """Availability outside the calendar window or spanning >14 days is 422.

        `insurer` repeats on the wire (one param per plan). Pass patient_id so
        the server applies age/history/plan eligibility; appointment_type is
        the server's choice, not ours.
        """
        if isinstance(insurer, str):
            insurer = [insurer]
        params: dict[str, Any] = {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "provider_id": provider_id,
            "specialty_id": specialty_id,
            "location_id": location_id,
            "patient_id": patient_id,
            "insurer": insurer,
        }
        return AvailabilityResponse.model_validate(await self._get("/api/v1/availability", params))
