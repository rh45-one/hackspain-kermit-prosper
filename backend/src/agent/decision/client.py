"""Async TypeSafe Jev client: one isolated, advisory sidecar call per turn.

Design constraints enforced here (see the OpenSpec Jev requirements):

* **Isolation** — a plain ``httpx.AsyncClient``; no new dependency, no clinic
  client, no scheduling import, no write or authorisation method.
* **Server-owned input** — the only public entry point takes a
  :class:`~agent.decision.models.TurnDecisionInput`; there is deliberately no
  method that accepts a transcript or state argument from a model tool call.
* **Pinned model** — defaults to ``jev-1.13.0`` and posts to
  ``/v1/systemone`` with bearer auth.
* **Hard budget** — one attempt, no retries, a timeout set from the vendor's
  published 70-500 ms range (600 ms by default, so the slow tail answers
  instead of abstaining silently).
* **Fail closed** — missing key, cancellation, timeout, non-2xx, malformed
  schema and low confidence all return an explicit abstention.
* **No content in logs** — only abstention/latency/confidence/model metadata is
  ever logged; the transcript, state and answers never reach a logger.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable, Mapping
from typing import Self

import httpx
from pydantic import ValidationError

# Budget for a read nobody is waiting on. Measured, the first assessment of a
# process takes ~600 ms and a tight budget turns the caller's opening sentence
# into an abstention; a background read can simply wait it out.
BACKGROUND_TIMEOUT_SECONDS = 2.0

from agent.decision.models import (
    DEFAULT_BASE_URL,
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_MODEL,
    DEFAULT_NOUL_THRESHOLD,
    DEFAULT_TIMEOUT_SECONDS,
    SOURCE,
    AbstentionReason,
    ChoiceAnswer,
    JsonValue,
    NoulAnswer,
    SystemOneResponse,
    TurnDecision,
    TurnDecisionInput,
    TurnIntent,
)
from agent.decision.questions import (
    INTENT_KEY,
    MEDICAL_EMERGENCY_KEY,
    NEEDS_CLARIFICATION_KEY,
    build_questions,
    intent_choice_labels,
)
from agent.decision.redaction import redact_turn_input

ENDPOINT_PATH = "/v1/systemone"
API_KEY_ENV = "TYPESAFE_API_KEY"
LOGGER_NAME = "agent.decision"

_REQUIRED_ANSWER_KEYS: tuple[str, str, str] = (
    INTENT_KEY,
    MEDICAL_EMERGENCY_KEY,
    NEEDS_CLARIFICATION_KEY,
)


class _CancelledError(Exception):
    """Internal signal that the per-socket cancel token fired mid-request."""


class JevClient:
    """Fast structured-decision sidecar over the TypeSafe System One API.

    ``transport`` exists for offline tests (``httpx.MockTransport``);
    production leaves it ``None``. ``clock`` is injectable so latency metadata
    can be asserted deterministically.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        noul_threshold: float = DEFAULT_NOUL_THRESHOLD,
        transport: httpx.AsyncBaseTransport | None = None,
        logger: logging.Logger | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if api_key is None:
            api_key = os.environ.get(API_KEY_ENV, "")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be within [0, 1]")
        if not 0.0 <= noul_threshold <= 1.0:
            raise ValueError("noul_threshold must be within [0, 1]")

        self._api_key = api_key or ""
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = float(timeout_seconds)
        self._min_confidence = float(min_confidence)
        self._noul_threshold = float(noul_threshold)
        self._transport = transport
        self._logger = logger or logging.getLogger(LOGGER_NAME)
        self._clock = clock
        self._client: httpx.AsyncClient | None = None

    # ---- lifecycle -------------------------------------------------------
    @property
    def configured(self) -> bool:
        """True when an API key is present; otherwise every call abstains."""
        return bool(self._api_key)

    @property
    def model(self) -> str:
        return self._model

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            # The socket-level timeout is the widest any caller may ask for;
            # the real per-call bound is enforced in _post_with_controls, so a
            # background read can outlive the default budget while a read the
            # caller is waiting on still gets cut short.
            widest = max(self._timeout_seconds, BACKGROUND_TIMEOUT_SECONDS)
            timeout = httpx.Timeout(widest, connect=widest)
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=timeout,
                transport=self._transport,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def aclose(self) -> None:
        await self.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    # ---- request building -------------------------------------------------
    def build_payload(self, snapshot: TurnDecisionInput) -> dict[str, JsonValue]:
        """Redact the server-owned snapshot and pin model + questions."""
        return {
            "state": redact_turn_input(snapshot),
            "model": self._model,
            "questions": build_questions(),
        }

    # ---- public assessment ----------------------------------------------
    async def assess(
        self,
        snapshot: TurnDecisionInput,
        *,
        cancel: asyncio.Event | None = None,
        timeout_seconds: float | None = None,
    ) -> TurnDecision:
        """Assess the current turn, or abstain.

        ``snapshot`` is the only input: the latest finalized caller transcript
        and call state owned by the server. ``cancel`` is the per-socket cancel
        token; a set token yields an abstention instead of a late answer.

        ``timeout_seconds`` overrides the client budget for one call. It
        exists because the two callers have opposite constraints: a read that
        runs in the background while the model is already generating can wait,
        and should, since the first assessment of a process measures ~600 ms
        and a tight budget turns the caller's opening sentence — the one that
        matters most — into an abstention. A read the model explicitly waited
        for is silence on the line and must stay short.
        """
        started = self._clock()
        if snapshot is None or snapshot.is_empty():
            return self._abstain(AbstentionReason.EMPTY_STATE, started)
        if not self._api_key:
            return self._abstain(AbstentionReason.MISSING_KEY, started)
        if cancel is not None and cancel.is_set():
            return self._abstain(AbstentionReason.CANCELLED, started)
        try:
            payload = self.build_payload(snapshot)
        except (TypeError, ValueError):
            return self._abstain(AbstentionReason.INVALID_INPUT, started)

        try:
            response = await self._post_with_controls(payload, cancel, timeout_seconds)
        except _CancelledError:
            return self._abstain(AbstentionReason.CANCELLED, started)
        except (TimeoutError, httpx.TimeoutException):
            return self._abstain(AbstentionReason.TIMEOUT, started)
        except httpx.TransportError:
            return self._abstain(AbstentionReason.TRANSPORT_ERROR, started)
        except httpx.HTTPError:
            return self._abstain(AbstentionReason.HTTP_ERROR, started)
        return self._interpret(response, started)

    # ---- transport --------------------------------------------------------
    async def _post_with_controls(
        self,
        payload: dict[str, JsonValue],
        cancel: asyncio.Event | None,
        budget: float | None = None,
    ) -> httpx.Response:
        budget = self._timeout_seconds if budget is None else float(budget)
        http_task = asyncio.ensure_future(self._post(payload))
        cancel_task = asyncio.ensure_future(cancel.wait()) if cancel is not None else None
        try:
            if cancel_task is None:
                return await asyncio.wait_for(http_task, timeout=budget)
            done, _pending = await asyncio.wait(
                {http_task, cancel_task},
                timeout=budget,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if http_task in done:
                return http_task.result()
            if cancel_task in done and cancel_task.result():
                raise _CancelledError()
            raise TimeoutError()
        finally:
            for task in (http_task, cancel_task):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (http_task, cancel_task) if task is not None),
                return_exceptions=True,
            )

    async def _post(self, payload: dict[str, JsonValue]) -> httpx.Response:
        return await self._http().post(
            ENDPOINT_PATH,
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )

    # ---- response validation ---------------------------------------------
    def _interpret(self, response: httpx.Response, started: float) -> TurnDecision:
        if response.status_code != 200:
            return self._abstain(AbstentionReason.HTTP_ERROR, started)
        try:
            data = response.json()
        except ValueError:
            return self._abstain(AbstentionReason.MALFORMED_RESPONSE, started)
        if not isinstance(data, Mapping):
            return self._abstain(AbstentionReason.MALFORMED_RESPONSE, started)
        try:
            parsed = SystemOneResponse.model_validate(data)
        except ValidationError:
            return self._abstain(AbstentionReason.MALFORMED_RESPONSE, started)

        answers = parsed.answers
        if not all(key in answers for key in _REQUIRED_ANSWER_KEYS):
            return self._abstain(AbstentionReason.MALFORMED_RESPONSE, started, model=parsed.model)
        intent_answer = answers[INTENT_KEY]
        emergency_answer = answers[MEDICAL_EMERGENCY_KEY]
        clarification_answer = answers[NEEDS_CLARIFICATION_KEY]
        if (
            not isinstance(intent_answer, ChoiceAnswer)
            or not isinstance(emergency_answer, NoulAnswer)
            or not isinstance(clarification_answer, NoulAnswer)
        ):
            return self._abstain(AbstentionReason.MALFORMED_RESPONSE, started, model=parsed.model)
        if intent_answer.choice not in intent_choice_labels():
            return self._abstain(AbstentionReason.MALFORMED_RESPONSE, started, model=parsed.model)

        usage = parsed.usage
        if intent_answer.confidence < self._min_confidence:
            return self._abstain(
                AbstentionReason.LOW_CONFIDENCE,
                started,
                model=parsed.model,
                confidence=intent_answer.confidence,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )

        decision = TurnDecision(
            intent=TurnIntent(intent_answer.choice),
            medical_emergency=emergency_answer.noul >= self._noul_threshold,
            needs_clarification=clarification_answer.noul >= self._noul_threshold,
            confidence=intent_answer.confidence,
            abstained=False,
            abstention_reason=None,
            source=SOURCE,
            model=parsed.model,
            latency_ms=self._latency_ms(started),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
        self._log(decision)
        return decision

    # ---- helpers ----------------------------------------------------------
    def _abstain(
        self,
        reason: AbstentionReason,
        started: float,
        *,
        model: str | None = None,
        confidence: float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> TurnDecision:
        decision = TurnDecision(
            intent=None,
            medical_emergency=None,
            needs_clarification=None,
            confidence=confidence,
            abstained=True,
            abstention_reason=reason,
            source=SOURCE,
            model=model if model is not None else self._model,
            latency_ms=self._latency_ms(started),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        self._log(decision)
        return decision

    def _latency_ms(self, started: float) -> float:
        return round((self._clock() - started) * 1000.0, 3)

    def _log(self, decision: TurnDecision) -> None:
        if not self._logger.isEnabledFor(logging.DEBUG):
            return
        # as_audit_dict carries only metadata: never transcript or state.
        self._logger.debug("jev_assess", extra={"extra_data": decision.as_audit_dict()})


__all__ = ["ENDPOINT_PATH", "JevClient"]
