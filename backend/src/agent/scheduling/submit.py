"""Submission client: one POST per action, inside the 30-second window.

Contract rules implemented here:

* route per action; the body is exactly the fields that route carries plus
  ``call_id`` (see :func:`agent.scheduling.recorder.build_body`);
* ``X-Api-Key`` header and a bounded connect/read timeout;
* retry transport errors and 5xx only -- never a 4xx;
* ``200`` accepted, ``409`` duplicate (also accepted, per the contract);
* ``404`` / ``410`` terminal (unknown call / window closed), not retried;
* ``422`` is an explicit data bug, logged with the body, not retried;
* the HTTP client is always closable, including as an async context manager.

Every request can be given a ``deadline`` (a :func:`time.monotonic` instant).
The deadline shortens the per-attempt timeout and stops retries, so a slow
provider can never blow the submission window.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Self

import httpx
from loguru import logger

from agent.scheduling.recorder import ACTION_VERBS, ROUTE_FIELDS, build_body

# Kept for callers that still import the route table from this module.
ROUTES = {route: route for route in ROUTE_FIELDS}


@dataclass
class SubmitOutcome:
    """Result of one submission attempt sequence for a single action."""

    route: str
    status: str  # accepted | duplicate | terminal | data_bug | skipped | failed
    http_status: int | None = None
    body: dict[str, Any] | None = None
    detail: str = ""
    attempts: int = 0

    @property
    def verb(self) -> str:
        return ACTION_VERBS.get(self.route, self.route.upper())

    @property
    def accepted(self) -> bool:
        return self.status in ("accepted", "duplicate")

    @property
    def terminal(self) -> bool:
        return self.status in ("terminal", "data_bug")


class Submitter:
    """Async submitter for ``/api/v1/submit/<route>``."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 4.0,
        connect_timeout: float = 2.0,
        retries: int = 2,
        backoff_base: float = 0.25,
        transport: httpx.AsyncBaseTransport | httpx.BaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = client is None
        self._timeout = timeout
        self._retries = max(0, retries)
        self._backoff_base = backoff_base
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-Api-Key": api_key},
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            transport=transport,
        )

    @property
    def worst_case_seconds(self) -> float:
        """Upper bound on one action's transport time, timeouts plus backoff."""
        sleeps = sum(self._backoff_base * (2**attempt) for attempt in range(self._retries))
        return self._timeout * (self._retries + 1) + sleeps

    @property
    def closed(self) -> bool:
        return self._client.is_closed

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # ---- public API ------------------------------------------------------
    async def submit(
        self,
        action: dict[str, Any],
        call_id: str,
        *,
        deadline: float | None = None,
    ) -> SubmitOutcome:
        """Validate and submit one action, returning a typed outcome."""
        route = str(action.get("route", ""))
        try:
            body = build_body(action, call_id)
        except ValueError as exc:
            logger.error("submit: invalid action route={} detail={}", route, exc)
            return SubmitOutcome(route=route, status="data_bug", detail=str(exc))
        return await self._post(route, body, deadline=deadline)

    async def post_route(
        self,
        action: dict[str, Any],
        call_id: str,
        *,
        deadline: float | None = None,
    ) -> dict[str, Any] | None:
        """Backwards-compatible wrapper returning the accepted body, if any."""
        outcome = await self.submit(action, call_id, deadline=deadline)
        return outcome.body if outcome.accepted else None

    # ---- transport -------------------------------------------------------
    async def _post(
        self,
        route: str,
        body: dict[str, Any],
        *,
        deadline: float | None = None,
    ) -> SubmitOutcome:
        path = f"/api/v1/submit/{route}"
        attempts = 0

        for attempt in range(self._retries + 1):
            if deadline is not None and time.monotonic() >= deadline:
                return SubmitOutcome(
                    route=route,
                    status="skipped",
                    detail="deadline reached",
                    attempts=attempts,
                )
            timeout = self._attempt_timeout(deadline)
            attempts += 1
            try:
                response = await self._client.post(path, json=body, timeout=timeout)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                detail = f"{type(exc).__name__}: {exc}"
                if attempt < self._retries:
                    await self._backoff(attempt, deadline)
                    continue
                logger.error(
                    "submit {} transport failed after {} attempts: {}", path, attempts, detail
                )
                return SubmitOutcome(route, "failed", detail=detail, attempts=attempts)

            status = response.status_code
            if status == 200:
                return SubmitOutcome(
                    route, "accepted", status, _json_or_none(response), attempts=attempts
                )
            if status == 409:
                return SubmitOutcome(
                    route, "duplicate", status, _json_or_none(response), attempts=attempts
                )
            if status in (404, 410):
                logger.warning("submit {} -> {} (terminal, not retried)", path, status)
                return SubmitOutcome(
                    route, "terminal", status, detail=response.text[:200], attempts=attempts
                )
            if status == 422:
                logger.error("submit {} -> 422 DATA BUG body={}", path, body)
                return SubmitOutcome(
                    route, "data_bug", status, detail=response.text[:200], attempts=attempts
                )
            if 500 <= status < 600:
                detail = f"server error {status}: {response.text[:200]}"
                if attempt < self._retries:
                    await self._backoff(attempt, deadline)
                    continue
                logger.error("submit {} -> {} after {} attempts", path, status, attempts)
                return SubmitOutcome(route, "failed", status, detail=detail, attempts=attempts)
            # Any other 4xx is a contract/data bug; retrying cannot help.
            logger.error("submit {} -> unexpected {} body={}", path, status, body)
            return SubmitOutcome(
                route, "failed", status, detail=response.text[:200], attempts=attempts
            )

        return SubmitOutcome(route, "failed", detail="retries exhausted", attempts=attempts)

    def _attempt_timeout(self, deadline: float | None) -> float:
        if deadline is None:
            return self._timeout
        remaining = deadline - time.monotonic()
        return max(min(self._timeout, remaining), 0.1)

    async def _backoff(self, attempt: int, deadline: float | None) -> None:
        delay = self._backoff_base * (2**attempt)
        if deadline is not None:
            delay = max(min(delay, deadline - time.monotonic()), 0.0)
        if delay > 0:
            await asyncio.sleep(delay)


def _json_or_none(response: httpx.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None
