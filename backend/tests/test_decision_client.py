"""Offline, MockTransport-only tests for the isolated Jev sidecar client.

No network, no credentials: every test drives an ``httpx.MockTransport`` and
asserts the exact wire contract, the pinned model and the fail-closed
abstention behaviour required by the OpenSpec.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from agent.decision import (
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    SOURCE,
    AbstentionReason,
    JevClient,
    TranscriptTurn,
    TurnDecisionInput,
    TurnIntent,
    build_questions,
)
from agent.decision.client import ENDPOINT_PATH

API_KEY = "ts-test-key"
TRANSCRIPT = [
    {"role": "assistant", "text": "Clinica Arenal, buenos dias."},
    {"role": "caller", "text": "Quiero pedir cita; mi telefono es 600123456."},
]


def snapshot() -> TurnDecisionInput:
    return TurnDecisionInput.from_messages(
        TRANSCRIPT,
        context={"phase": "intake", "requested_specialty": "general"},
        language="es",
    )


def valid_body() -> dict[str, Any]:
    return {
        "model": DEFAULT_MODEL,
        "answers": {
            "intent": {
                "type": "choice",
                "choice": "book_appointment",
                "probabilities": {"book_appointment": 0.94, "other": 0.06},
                "confidence": 0.9,
            },
            "medical_emergency": {"type": "noul", "noul": 0.02},
            "needs_clarification": {"type": "noul", "noul": 0.1},
        },
        "usage": {"input_tokens": 128, "output_tokens": 12},
    }


def make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    clock: Callable[[], float] | None = None,
    **kwargs: Any,
) -> JevClient:
    ticks = iter([100.0, 100.123])
    return JevClient(
        api_key=API_KEY,
        transport=httpx.MockTransport(handler),
        clock=clock or (lambda: next(ticks)),
        **kwargs,
    )


def test_pinned_defaults_match_the_openspec():
    assert DEFAULT_MODEL == "jev-1.13.0"
    assert DEFAULT_TIMEOUT_SECONDS == 0.300
    assert ENDPOINT_PATH == "/v1/systemone"


async def test_posts_exact_payload_questions_and_auth():
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["content_type"] = request.headers.get("content-type")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=valid_body())

    client = make_client(handler)
    decision = await client.assess(snapshot())
    await client.close()

    assert seen["method"] == "POST"
    assert seen["path"] == "/v1/systemone"
    assert seen["url"] == "https://api.typesafe.ai/v1/systemone"
    assert seen["auth"] == f"Bearer {API_KEY}"
    assert seen["content_type"].startswith("application/json")
    body = seen["body"]
    assert set(body) == {"state", "model", "questions"}
    assert body["model"] == "jev-1.13.0"
    assert body["questions"] == build_questions()
    assert set(body["questions"]) == {"intent", "medical_emergency", "needs_clarification"}
    assert decision.abstained is False


async def test_payload_redacts_pii_before_serialization():
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=valid_body())

    client = make_client(handler)
    await client.assess(snapshot())
    await client.close()

    serialized = json.dumps(seen["body"], ensure_ascii=False)
    assert "600123456" not in serialized
    assert "caller_transcript" in seen["body"]["state"]
    assert seen["body"]["state"]["language"] == "es"
    assert seen["body"]["state"]["call_context"] == {
        "phase": "intake",
        "requested_specialty": "general",
    }


async def test_valid_response_parses_into_typed_decision():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=valid_body())

    client = make_client(handler)
    decision = await client.assess(snapshot())
    await client.close()

    assert decision.intent is TurnIntent.BOOK_APPOINTMENT
    assert decision.medical_emergency is False
    assert decision.needs_clarification is False
    assert decision.confidence == 0.9
    assert decision.abstained is False
    assert decision.abstention_reason is None
    assert decision.source == SOURCE
    assert decision.model == DEFAULT_MODEL
    assert decision.latency_ms == pytest.approx(123.0)
    assert decision.input_tokens == 128
    assert decision.output_tokens == 12
    assert decision.advisory is True
    assert "600123456" not in json.dumps(decision.as_audit_dict())


@pytest.mark.parametrize(
    ("noul", "expected"),
    [(0.5, True), (0.49, False), (0.9, True), (0.0, False)],
)
async def test_noul_thresholds_are_applied(noul: float, expected: bool):
    body = valid_body()
    body["answers"]["medical_emergency"] = {"type": "noul", "noul": noul}

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    client = make_client(handler)
    decision = await client.assess(snapshot())
    await client.close()
    assert decision.medical_emergency is expected


async def test_low_confidence_abstains_and_carries_confidence():
    body = valid_body()
    body["answers"]["intent"]["confidence"] = 0.2

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    client = make_client(handler)
    decision = await client.assess(snapshot())
    await client.close()

    assert decision.abstained is True
    assert decision.abstention_reason is AbstentionReason.LOW_CONFIDENCE
    assert decision.confidence == 0.2
    assert decision.intent is None
    assert decision.medical_emergency is None
    assert decision.needs_clarification is None


async def test_missing_api_key_abstains_without_network():
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=valid_body())

    client = JevClient(api_key="", transport=httpx.MockTransport(handler))
    assert client.configured is False
    decision = await client.assess(snapshot())
    await client.close()

    assert calls["n"] == 0
    assert decision.abstained is True
    assert decision.abstention_reason is AbstentionReason.MISSING_KEY


async def test_empty_state_abstains_without_network():
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=valid_body())

    client = make_client(handler)
    decision = await client.assess(TurnDecisionInput())
    await client.close()

    assert calls["n"] == 0
    assert decision.abstention_reason is AbstentionReason.EMPTY_STATE
    assert decision.intent is None


async def test_timeout_abstains_inside_the_hard_budget():
    async def handler(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1.0)
        return httpx.Response(200, json=valid_body())

    client = JevClient(
        api_key=API_KEY,
        timeout_seconds=0.05,
        transport=httpx.MockTransport(handler),
    )
    decision = await client.assess(snapshot())
    await client.close()

    assert decision.abstained is True
    assert decision.abstention_reason is AbstentionReason.TIMEOUT
    assert decision.intent is None


async def test_cancel_token_set_before_call_abstains_immediately():
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=valid_body())

    event = asyncio.Event()
    event.set()
    client = make_client(handler)
    decision = await client.assess(snapshot(), cancel=event)
    await client.close()

    assert calls["n"] == 0
    assert decision.abstention_reason is AbstentionReason.CANCELLED


async def test_cancellation_mid_flight_abstains():
    async def handler(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1.0)
        return httpx.Response(200, json=valid_body())

    event = asyncio.Event()

    async def fire() -> None:
        await asyncio.sleep(0.02)
        event.set()

    setter = asyncio.create_task(fire())
    client = JevClient(
        api_key=API_KEY,
        timeout_seconds=2.0,
        transport=httpx.MockTransport(handler),
    )
    decision = await client.assess(snapshot(), cancel=event)
    await client.close()
    await setter

    assert decision.abstained is True
    assert decision.abstention_reason is AbstentionReason.CANCELLED
    assert decision.intent is None


@pytest.mark.parametrize("status", [400, 401, 403, 422, 429, 500, 529])
async def test_non_2xx_abstains_without_retry(status: int):
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(status, json={"error": "nope"})

    client = make_client(handler)
    decision = await client.assess(snapshot())
    await client.close()

    assert calls["n"] == 1  # no retries on the turn path
    assert decision.abstained is True
    assert decision.abstention_reason is AbstentionReason.HTTP_ERROR


async def test_transport_error_abstains():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection reset")

    client = make_client(handler)
    decision = await client.assess(snapshot())
    await client.close()

    assert decision.abstained is True
    assert decision.abstention_reason is AbstentionReason.TRANSPORT_ERROR


def _malformed_cases() -> list[tuple[str, Callable[[], httpx.Response]]]:
    def invalid_json() -> httpx.Response:
        return httpx.Response(200, content=b"<html>not json</html>")

    def missing_usage() -> httpx.Response:
        body = valid_body()
        del body["usage"]
        return httpx.Response(200, json=body)

    def non_object() -> httpx.Response:
        return httpx.Response(200, json=["unexpected"])

    def missing_answer_key() -> httpx.Response:
        body = valid_body()
        del body["answers"]["needs_clarification"]
        return httpx.Response(200, json=body)

    def wrong_answer_type() -> httpx.Response:
        body = valid_body()
        body["answers"]["intent"] = {"type": "noul", "noul": 0.4}
        return httpx.Response(200, json=body)

    def unknown_choice_label() -> httpx.Response:
        body = valid_body()
        body["answers"]["intent"]["choice"] = "refund_my_money"
        return httpx.Response(200, json=body)

    def confidence_out_of_range() -> httpx.Response:
        body = valid_body()
        body["answers"]["intent"]["confidence"] = 1.5
        return httpx.Response(200, json=body)

    def noul_out_of_range() -> httpx.Response:
        body = valid_body()
        body["answers"]["medical_emergency"]["noul"] = 2.0
        return httpx.Response(200, json=body)

    return [
        ("invalid_json", invalid_json),
        ("missing_usage", missing_usage),
        ("non_object", non_object),
        ("missing_answer_key", missing_answer_key),
        ("wrong_answer_type", wrong_answer_type),
        ("unknown_choice_label", unknown_choice_label),
        ("confidence_out_of_range", confidence_out_of_range),
        ("noul_out_of_range", noul_out_of_range),
    ]


@pytest.mark.parametrize(
    ("name", "factory"),
    _malformed_cases(),
    ids=[name for name, _ in _malformed_cases()],
)
async def test_malformed_response_abstains(
    name: str,
    factory: Callable[[], httpx.Response],
):
    def handler(_request: httpx.Request) -> httpx.Response:
        return factory()

    client = make_client(handler)
    decision = await client.assess(snapshot())
    await client.close()

    assert decision.abstained is True, name
    assert decision.abstention_reason is AbstentionReason.MALFORMED_RESPONSE, name
    assert decision.intent is None


async def test_logs_never_contain_transcript_or_identifiers(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG, logger="agent.decision")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=valid_body())

    client = make_client(handler)
    await client.assess(snapshot())
    await client.close()

    assert "jev_assess" in caplog.text
    assert "600123456" not in caplog.text
    assert "Quiero pedir cita" not in caplog.text
    assert "Clinica Arenal" not in caplog.text
    assert "caller_transcript" not in caplog.text
    assert "call_context" not in caplog.text


def test_assess_exposes_no_model_supplied_transcript_argument():
    params = set(inspect.signature(JevClient.assess).parameters)
    assert params == {"self", "snapshot", "cancel"}
    assert not ({"transcript", "state", "text", "messages", "arguments"} & params)


def test_client_has_no_write_or_authorization_surface():
    forbidden = {
        "write",
        "submit",
        "book",
        "cancel",
        "authorize",
        "authorise",
        "create",
        "update",
        "delete",
        "request",
        "clinic",
    }
    public = {name for name in dir(JevClient) if not name.startswith("_")}
    assert not (public & forbidden)
    assert {"assess", "build_payload", "close", "configured", "model"} <= public


def test_constructor_rejects_out_of_range_tuning():
    with pytest.raises(ValueError):
        JevClient(api_key=API_KEY, timeout_seconds=0)
    with pytest.raises(ValueError):
        JevClient(api_key=API_KEY, min_confidence=1.5)
    with pytest.raises(ValueError):
        JevClient(api_key=API_KEY, noul_threshold=-0.1)


def test_transcript_role_is_normalized():
    turn = TranscriptTurn(role="patient", text="hola")
    assert turn.role == "caller"
    assert TranscriptTurn(role="assistant", text="hola").role == "agent"
