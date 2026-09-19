"""Text adapter tests: the evaluator's contract, and the submission timing.

Offline by construction: the Gemini client is scripted, the Submitter is a
fake, and Jev abstains without a key (decision/client.py:193). Nothing here
reaches the network, and nothing here starts a server on a real port.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.ops import turns as text_turns


# ---- doubles -------------------------------------------------------------
class FakeSubmitter:
    """Records post_route calls; never touches the network."""

    instances: ClassVar[list[FakeSubmitter]] = []

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.calls: list[dict[str, Any]] = []
        self.closed = False
        FakeSubmitter.instances.append(self)

    async def post_route(self, action: dict, call_id: str, *, deadline: float | None = None):
        self.calls.append({"action": dict(action), "call_id": call_id})

    async def close(self) -> None:
        self.closed = True


class FakeCall:
    """Minimal stand-in for a Gemini FunctionCall."""

    def __init__(self, name: str, args: dict[str, Any] | None = None) -> None:
        self.name = name
        self.args = args or {}


class FakeResponse:
    def __init__(self, text: str | None = None, function_calls: list[FakeCall] | None = None):
        self.text = text
        self.function_calls = function_calls or []
        self.candidates: list[Any] = []


class FakeGemini:
    """Scripted client exposing the one call path _generate uses."""

    def __init__(self, scripted: list[FakeResponse]) -> None:
        self.scripted = list(scripted)
        self.requests: list[dict[str, Any]] = []

    @property
    def aio(self) -> FakeGemini:
        return self

    @property
    def models(self) -> FakeGemini:
        return self

    async def generate_content(self, *, model: str, contents: Any, config: Any) -> FakeResponse:
        self.requests.append({"model": model, "contents": list(contents), "config": config})
        if not self.scripted:
            return FakeResponse(text="")
        return self.scripted.pop(0)


def make_settings(tmp_path, **overrides) -> SimpleNamespace:
    base = {
        "data_dir": str(tmp_path / "data"),
        "prosper_api_base_url": "http://clinic.test",
        "prosper_api_key": "pk-local-eval",
        "submit_window_seconds": 30,
        "gemini_api_key": "unused-the-client-is-injected",
        "voice_engine": "gemini_live",
        "typesafe_api_key": "",  # Jev abstains offline
        "jev_timeout_seconds": 0.6,
        "jev_min_confidence": 0.5,
        "caller_tz": "Europe/Madrid",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture()
def fake_submitter(monkeypatch):
    FakeSubmitter.instances = []
    import agent.scheduling.submit as submit_module

    monkeypatch.setattr(submit_module, "Submitter", FakeSubmitter)
    return FakeSubmitter


def make_adapter(tmp_path, scripted: list[FakeResponse], **overrides) -> text_turns.TextAdapter:
    return text_turns.TextAdapter(
        make_settings(tmp_path, **overrides),
        model="fake-model",
        client=FakeGemini(scripted),
        data_dir=str(tmp_path / "turns"),
    )


# ---- opt-in --------------------------------------------------------------
@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_adapter_enabled_for_truthy_flags(value):
    assert text_turns.adapter_enabled({text_turns.ENV_FLAG: value})


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe"])
def test_adapter_disabled_otherwise(value):
    assert not text_turns.adapter_enabled({text_turns.ENV_FLAG: value})


def test_not_mounted_without_the_flag(tmp_path, monkeypatch):
    """The process that answers scored calls must not serve test routes."""
    monkeypatch.delenv(text_turns.ENV_FLAG, raising=False)
    app = FastAPI()

    assert text_turns.mount_if_enabled(app, make_settings(tmp_path)) is False
    # Routed, not merely absent from a list: FastAPI 0.141 keeps an included
    # router opaque, so the only honest check is asking the app.
    assert loopback(app).post("/turns", json={"call_id": "x", "text": "y"}).status_code == 404


def test_mounted_with_the_flag(tmp_path, monkeypatch):
    monkeypatch.setenv(text_turns.ENV_FLAG, "1")
    app = FastAPI()
    try:
        assert text_turns.mount_if_enabled(app, make_settings(tmp_path)) is True
        # The mount installs a real adapter; swap in the scripted one so the
        # route can be exercised without a provider.
        text_turns.set_adapter(make_adapter(tmp_path, [FakeResponse(text="Dígame.")]))
        response = loopback(app).post("/turns", json={"call_id": "m-1", "text": "Hola"})
        assert response.status_code == 200
        assert response.json() == {"reply": "Dígame.", "ended": False}
    finally:
        text_turns.set_adapter(None)


# ---- tool surface --------------------------------------------------------
def test_declarations_mirror_the_toolbox(tmp_path):
    """The bench advertises the scored tool set, derived not transcribed."""
    from agent.brain.tools import ToolBox
    from agent.voice.context import CallContext

    settings = make_settings(tmp_path)
    ctx = CallContext(data_dir=str(tmp_path / "turns"), call_id="decl")
    toolbox = ToolBox(ctx, settings)
    wrappers = text_turns._tool_wrappers(toolbox)

    assert {fn.__name__ for fn in toolbox.tools()} == set(wrappers)
    assert "book_appointment" in wrappers
    assert "assess_current_turn" in wrappers  # gemini_live engine registers it

    by_name = {d["name"]: d for d in text_turns._declarations(wrappers)}
    assert set(by_name) == set(wrappers)
    # A tool with arguments keeps its schema and its docstring description.
    book = by_name["book_appointment"]
    assert book["description"]
    assert book["parameters"]["type"] == "object"
    assert book["parameters"]["properties"]
    # A zero-argument tool declares no parameters at all.
    assert "parameters" not in by_name["assess_current_turn"]


async def test_invoke_runs_the_real_tool_and_captures_its_result(tmp_path):
    from agent.brain.tools import ToolBox
    from agent.voice.context import CallContext

    ctx = CallContext(data_dir=str(tmp_path / "turns"), call_id="invoke")
    toolbox = ToolBox(ctx, make_settings(tmp_path))
    wrappers = text_turns._tool_wrappers(toolbox)

    result = await text_turns._invoke(wrappers["finish_without_booking"], {"reason": "out_of_scope"})

    assert result == {"noted": True, "reason": "out_of_scope"}
    assert ctx.queued_actions == [{"route": "no-action", "reason": "out_of_scope"}]
    await toolbox.aclose()


# ---- the turn ------------------------------------------------------------
async def test_turn_returns_the_reply_and_records_both_sides(tmp_path, fake_submitter):
    adapter = make_adapter(tmp_path, [FakeResponse(text="Clínica Arenal, buenos días.")])

    reply = await adapter.turn("call-1", "Hola, buenos días.")

    assert reply == "Clínica Arenal, buenos días."
    ctx = adapter._calls["call-1"].ctx
    assert ctx.transcript == [
        {"role": "caller", "text": "Hola, buenos días."},
        {"role": "assistant", "text": "Clínica Arenal, buenos días."},
    ]
    assert fake_submitter.instances == []  # nothing queued, nothing submitted
    await adapter.aclose()


async def test_turn_runs_tools_then_answers(tmp_path, fake_submitter):
    """A tool round trip stays inside one /turns request."""
    adapter = make_adapter(
        tmp_path,
        [
            FakeResponse(function_calls=[FakeCall("finish_without_booking", {"reason": "out_of_scope"})]),
            FakeResponse(text="Lo siento, eso no lo lleva recepción."),
        ],
    )

    reply = await adapter.turn("call-2", "Quiero hablar de la factura de la luz.")

    assert reply == "Lo siento, eso no lo lleva recepción."
    ctx = adapter._calls["call-2"].ctx
    assert ctx.queued_actions == [{"route": "no-action", "reason": "out_of_scope"}]
    # The tool result went back to the model as a function response.
    assert len(adapter._client.requests) == 2
    await adapter.aclose()


async def test_the_turn_that_queues_an_action_submits_it_before_replying(tmp_path, fake_submitter):
    """The core timing claim.

    The runner reads the recorded actions the instant the simulated patient
    hangs up, so an action that waits for a close signal is never scored.
    """
    adapter = make_adapter(
        tmp_path,
        [
            FakeResponse(function_calls=[FakeCall("finish_without_booking", {"reason": "no_availability"})]),
            FakeResponse(text="No queda hueco, lo siento."),
        ],
    )

    await adapter.turn("call-3", "¿Hay algo para mañana?")

    assert len(fake_submitter.instances) == 1
    submitted = fake_submitter.instances[0]
    assert [c["action"]["route"] for c in submitted.calls] == ["no-action"]
    assert submitted.calls[0]["call_id"] == "call-3"
    assert submitted.closed
    await adapter.aclose()


async def test_an_action_is_never_submitted_twice(tmp_path, fake_submitter):
    """A later turn settles only what that turn queued."""
    adapter = make_adapter(
        tmp_path,
        [
            FakeResponse(function_calls=[FakeCall("finish_without_booking", {"reason": "out_of_scope"})]),
            FakeResponse(text="Nada más."),
            FakeResponse(text="Hasta luego."),
        ],
    )

    await adapter.turn("call-4", "Una cosa rara.")
    await adapter.turn("call-4", "Vale, gracias.")
    await adapter.close("call-4")

    posted = [c for inst in fake_submitter.instances for c in inst.calls]
    assert len(posted) == 1


async def test_close_without_any_action_submits_the_no_action_fallback(tmp_path, fake_submitter):
    """flush_call still owns the end of a call that queued nothing."""
    adapter = make_adapter(tmp_path, [FakeResponse(text="Buenos días.")])
    await adapter.turn("call-5", "Hola.")

    assert await adapter.close("call-5") is True

    posted = [c for inst in fake_submitter.instances for c in inst.calls]
    assert [c["action"] for c in posted] == [{"route": "no-action", "reason": "out_of_scope"}]
    assert await adapter.close("call-5") is False  # the call is gone


async def test_offline_without_a_key_logs_instead_of_posting(tmp_path, fake_submitter):
    adapter = make_adapter(
        tmp_path,
        [
            FakeResponse(function_calls=[FakeCall("finish_without_booking", {"reason": "out_of_scope"})]),
            FakeResponse(text="Nada."),
        ],
        prosper_api_key="",
    )

    await adapter.turn("call-6", "Hola.")

    assert fake_submitter.instances == []
    assert adapter._calls["call-6"].settled == 1
    await adapter.aclose()


async def test_bench_traces_are_kept_out_of_the_real_call_directory(tmp_path):
    adapter = make_adapter(tmp_path, [FakeResponse(text="Hola.")])
    await adapter.turn("call-7", "Hola.")

    assert (tmp_path / "turns" / "calls" / "call-7.jsonl").exists()
    assert not (tmp_path / "data" / "calls").exists()
    await adapter.aclose()


async def test_concurrent_calls_never_share_state(tmp_path, fake_submitter):
    import asyncio

    adapter = make_adapter(tmp_path, [FakeResponse(text="A"), FakeResponse(text="B")])
    await asyncio.gather(adapter.turn("sw-1", "uno"), adapter.turn("sw-2", "dos"))

    assert set(adapter._calls) == {"sw-1", "sw-2"}
    assert adapter._calls["sw-1"].ctx is not adapter._calls["sw-2"].ctx
    assert adapter._calls["sw-1"].toolbox is not adapter._calls["sw-2"].toolbox
    await adapter.aclose()


# ---- HTTP contract -------------------------------------------------------
def loopback(app: FastAPI) -> TestClient:
    """A client that looks like 127.0.0.1, which is what the bench really is.

    Starlette's default test client reports the host as "testclient", so
    without this every request is off-host and the access gate answers 403.
    """
    return TestClient(app, client=("127.0.0.1", 40000))


@pytest.fixture()
def client(tmp_path, fake_submitter):
    app = FastAPI()
    app.include_router(text_turns.router)
    adapter = make_adapter(tmp_path, [FakeResponse(text="Clínica Arenal, dígame.")])
    text_turns.set_adapter(adapter)
    try:
        yield loopback(app), adapter
    finally:
        text_turns.set_adapter(None)


def test_post_turns_answers_the_documented_shape(client):
    http, _ = client
    response = http.post("/turns", json={"call_id": "http-1", "text": "Hola"})

    assert response.status_code == 200
    assert response.json() == {"reply": "Clínica Arenal, dígame.", "ended": False}


def test_post_turns_accepts_an_empty_opening(client):
    http, _ = client
    assert http.post("/turns", json={"call_id": "http-2", "text": ""}).status_code == 200


def test_post_turns_rejects_a_body_without_call_id(client):
    http, _ = client
    assert http.post("/turns", json={"text": "Hola"}).status_code == 422


def test_an_adapter_defect_is_a_5xx_not_a_polite_200(client, monkeypatch):
    """A broken adapter must invalidate the case, not be scored as the agent."""
    http, adapter = client

    async def boom(*_: Any, **__: Any):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(adapter, "turn", boom)
    response = http.post("/turns", json={"call_id": "http-3", "text": "Hola"})

    assert response.status_code == 500
    assert "reply" not in response.json()


def test_close_endpoint_reports_whether_the_call_existed(client):
    http, _ = client
    http.post("/turns", json={"call_id": "http-4", "text": "Hola"})

    assert http.post("/turns/http-4/close").json()["state"] == "closed"
    assert http.post("/turns/http-4/close").json()["state"] == "unknown"


def test_turns_is_refused_off_host_without_a_token(tmp_path, fake_submitter):
    """/turns drives the real ToolBox and submits: it cannot be open on a host.

    Being opt-in is not enough. A reachable adapter lets anyone book, cancel
    or register against the live Prosper API with our key.
    """
    app = FastAPI()
    app.include_router(text_turns.router)
    text_turns.set_adapter(make_adapter(tmp_path, [FakeResponse(text="no")]))
    try:
        offhost = TestClient(app, client=("203.0.113.7", 40000))
        assert offhost.post("/turns", json={"call_id": "x", "text": "y"}).status_code == 403
    finally:
        text_turns.set_adapter(None)


def test_turns_accepts_the_ops_token_off_host(tmp_path, fake_submitter, monkeypatch):
    from agent.ops import console

    monkeypatch.setattr(console, "settings", lambda: SimpleNamespace(ops_token="s3cret"))
    app = FastAPI()
    app.include_router(text_turns.router)
    text_turns.set_adapter(make_adapter(tmp_path, [FakeResponse(text="Dígame.")]))
    try:
        offhost = TestClient(app, client=("203.0.113.7", 40000))
        body = {"call_id": "tok-1", "text": "Hola"}
        assert offhost.post("/turns", json=body).status_code == 401
        ok = offhost.post("/turns", json=body, headers={"X-Ops-Token": "s3cret"})
        assert ok.status_code == 200
        assert ok.json() == {"reply": "Dígame.", "ended": False}
    finally:
        text_turns.set_adapter(None)


# ---- the runner's end-of-call signal -------------------------------------
def test_hangup_is_accepted_with_a_null_text(client):
    """The runner posts {call_id, text: null, event: "hangup"}.

    Rejecting that with a 422 throws away the one chance to flush while the
    receiver window is still open.
    """
    http, _ = client
    http.post("/turns", json={"call_id": "hup-1", "text": "Hola"})

    response = http.post("/turns", json={"call_id": "hup-1", "text": None, "event": "hangup"})

    assert response.status_code == 200
    assert response.json() == {"reply": "", "ended": True}


def test_hangup_flushes_the_no_action_fallback_before_answering(client, fake_submitter):
    """A call that queued nothing must still record something, in time.

    The runner closes the submission window right after this response, so the
    flush has to finish inside the request, not after it.
    """
    http, adapter = client
    http.post("/turns", json={"call_id": "hup-2", "text": "Hola"})
    assert fake_submitter.instances == []  # nothing queued during the call

    http.post("/turns", json={"call_id": "hup-2", "text": None, "event": "hangup"})

    posted = [c for inst in fake_submitter.instances for c in inst.calls]
    assert [c["action"] for c in posted] == [{"route": "no-action", "reason": "out_of_scope"}]
    assert "hup-2" not in adapter._calls


def test_hangup_for_an_unknown_call_is_still_a_200(client):
    """Best effort on the runner's side means it must never fail loudly here."""
    http, _ = client
    assert http.post("/turns", json={"call_id": "nope", "event": "hangup"}).status_code == 200
