"""Text adapter for the local evaluator bench: ``POST /turns``.

The contract is the evaluator's, read from
``evaluator/src/evaluator/runner/experiment.py::_run_text_call``::

    POST {text_url}/turns  {"call_id": str, "text": str}  ->  200 {"reply": str}

Anything other than 200 is counted by the runner as an adapter failure, and a
transport error with nothing submitted invalidates the case instead of scoring
it against the agent. So a defect in here must surface as a 5xx, never as an
apologetic 200: a broken adapter that answers politely is scored as a broken
agent.

Two facts about the runner drive the whole design:

- It opens and closes the submission window on the FAKE CLINIC
  (``POST /eval/calls`` / ``/eval/calls/{id}/close``), never here. This
  adapter is told when a call speaks and never told when it ends.
- It reads the recorded actions moments after the call ends. There IS an
  end-of-call signal now (``event: "hangup"``), but the runner documents it
  as best effort and does not penalise an agent that ignores it.

So each turn settles its own new actions: whatever the brain queued during
this turn goes on the wire before the reply is returned, which is correct
with or without a hangup, and keeps a conversation cut short by
``max_call_seconds`` from losing what it had already decided. The hangup then
runs ``flush_call``, which is what the call that queued *nothing* needs — its
no-action fallback is only reachable through that signal.

Text skips STT and TTS and nothing else: same ``CallContext``, same
``ToolBox``, same ``SYSTEM_PROMPT``, same submission path. It is not the
scored pipeline — see the limitations in the module tests and in the task
brief — and a green bench run validates logic, not correctness.

Opt-in, always. The process that answers scored calls must not mount test
routes: :func:`mount_if_enabled` is a no-op unless ``TURNS_ADAPTER`` is set.
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from loguru import logger
from pydantic import BaseModel

from agent.brain import prompts
from agent.brain.tools import ToolBox
from agent.voice.context import CallContext
from agent.voice.flush import flush_call

# Environment flag that mounts the adapter. Absent = not mounted.
ENV_FLAG = "TURNS_ADAPTER"
ENV_MODEL = "TURNS_MODEL"
ENV_DATA_DIR = "TURNS_DATA_DIR"
# Deliberate escape hatch for submitting somewhere that is not loopback. It
# exists so the refusal below can be overridden on purpose, in one place, by
# somebody who typed the words.
ENV_SUBMIT_REMOTE = "TURNS_SUBMIT_REMOTE"

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

# The text sibling of the pinned audio host. gemini-3.8-live is audio-only,
# so the bench CANNOT run the scored path's model; this is the closest text
# model the project key can reach (verified against models.list()). Override
# with TURNS_MODEL.
DEFAULT_MODEL = "gemini-3.8-flash"

# One caller turn may need several tool rounds. Measured on the bench, the
# third-party reschedule spends eight on its FIRST turn and is not looping:
# lookup -> confirm -> list_appointments -> describe_clinic -> four searches.
# So the cap is only a guard against a hard loop; the wall-clock budget below
# is what actually bounds a turn.
MAX_TOOL_ROUNDS = 16

# Whole-turn budget. A hung provider must cost one turn, never the experiment.
TURN_TIMEOUT_SECONDS = 90.0

# The runner's end-of-call signal. Best effort on its side, load-bearing on
# ours: it is what lets flush_call run while the receiver window is open.
HANGUP_EVENT = "hangup"

# A call with no turn for this long is closed and its sidecar resources freed.
# Swept lazily on the next request: a background task is one more thing to be
# wrong, and nothing here needs one.
IDLE_CLOSE_SECONDS = 180.0

__all__ = [
    "DEFAULT_MODEL",
    "ENV_FLAG",
    "ENV_SUBMIT_REMOTE",
    "TextAdapter",
    "TurnRequest",
    "adapter_enabled",
    "may_submit",
    "mount_if_enabled",
    "router",
]


class TurnRequest(BaseModel):
    """The runner's body.

    ``text`` may be empty (the patient's opening can be) and is explicitly
    nullable: the end-of-call signal is posted as
    ``{"call_id": ..., "text": null, "event": "hangup"}``, and rejecting that
    with a 422 would throw away the one chance to flush inside the window.
    """

    call_id: str
    text: str | None = None
    event: str | None = None


class TurnReply(BaseModel):
    reply: str
    # "the agent hung up"; the runner stops talking to a closed call.
    ended: bool = False


@dataclass
class _TextCall:
    """One simulated call: the same per-call state a socket would own."""

    ctx: CallContext
    toolbox: ToolBox
    history: list[Any] = field(default_factory=list)
    # How many of ctx.queued_actions have already been POSTed.
    settled: int = 0
    last_seen: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def adapter_enabled(env: dict[str, str] | None = None) -> bool:
    """True when this process is allowed to expose the text adapter."""
    raw = (env or os.environ).get(ENV_FLAG, "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def submits_to_loopback(base_url: str) -> bool:
    """True when the submission target is this machine."""
    host = (urlparse(base_url or "").hostname or "").lower()
    return host in _LOOPBACK_HOSTS


def may_submit(settings: Any, env: dict[str, str] | None = None) -> bool:
    """Whether this adapter is allowed to write to the submission API.

    Being opt-in and access-gated answers *who may call*, which is a different
    question from *where a legitimate call writes*. The natural way to start
    this backend for a bench run is `set -a && . ./.env && set +a`, which loads
    the real `PROSPER_API_BASE_URL` and key; forgetting to point it at the
    local clinic would post every bench case to the live platform under
    invented call ids. That has already happened once today, from probes.

    So the default fails the way `mount_if_enabled` fails: towards doing
    nothing. Loopback submits; anything else needs TURNS_SUBMIT_REMOTE.
    """
    if submits_to_loopback(getattr(settings, "prosper_api_base_url", "")):
        return True
    raw = (env or os.environ).get(ENV_SUBMIT_REMOTE, "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _tool_wrappers(toolbox: ToolBox) -> dict[str, Any]:
    """Wrap the ToolBox direct functions, keyed by the name the model sees.

    Pipecat derives every schema from the signature and docstring, which is
    exactly what the voice path advertises — so the bench cannot drift from
    the scored tool surface by transcribing it by hand.
    """
    from pipecat.adapters.schemas.direct_function import DirectFunctionWrapper

    wrappers = {}
    for fn in toolbox.tools():
        wrapper = DirectFunctionWrapper(fn)
        wrappers[wrapper.name] = wrapper
    return wrappers


def _declarations(wrappers: dict[str, Any]) -> list[dict[str, Any]]:
    """Pipecat FunctionSchemas -> Gemini function declarations."""
    out: list[dict[str, Any]] = []
    for wrapper in wrappers.values():
        schema = wrapper.to_function_schema().to_default_dict()
        # A zero-argument tool (assess_current_turn) must declare no
        # parameters at all; an empty object schema is rejected.
        if not schema.get("parameters", {}).get("properties"):
            schema.pop("parameters", None)
        out.append(schema)
    return out


async def _invoke(wrapper: Any, args: dict[str, Any]) -> Any:
    """Run one ToolBox tool and capture what it handed back to the model.

    The tools only ever touch ``params.result_callback`` (verified across all
    44 call sites in brain/tools.py), so the rest of FunctionCallParams —
    which belongs to a running pipeline that does not exist here — is left
    unset rather than faked.
    """
    from pipecat.services.llm_service import FunctionCallParams

    captured: dict[str, Any] = {}

    async def result_callback(result: Any, *_: Any, **__: Any) -> None:
        captured["result"] = result

    params = FunctionCallParams(
        function_name=wrapper.name,
        tool_call_id=uuid.uuid4().hex,
        arguments=args,
        llm=None,  # type: ignore[arg-type]
        pipeline_worker=None,  # type: ignore[arg-type]
        context=None,  # type: ignore[arg-type]
        result_callback=result_callback,
    )
    await wrapper.invoke(args, params)
    return captured.get("result")


class TextAdapter:
    """Per-call brains over text. One instance per process."""

    def __init__(
        self,
        settings: Any,
        *,
        model: str | None = None,
        client: Any = None,
        data_dir: str | None = None,
    ) -> None:
        self.settings = settings
        self.model = model or os.environ.get(ENV_MODEL) or DEFAULT_MODEL
        # Bench traces never land among the real ones: /ops reads the same
        # directory and a run would bury 60 scored calls under 63 fake ones.
        self.data_dir = data_dir or os.environ.get(ENV_DATA_DIR) or f"{settings.data_dir}/turns"
        self._client = client
        self.submit_actions = may_submit(settings)
        if not self.submit_actions:
            logger.warning(
                "text adapter will NOT submit: {} is not loopback and {} is unset. "
                "Actions are queued and audited only.",
                getattr(settings, "prosper_api_base_url", ""),
                ENV_SUBMIT_REMOTE,
            )
        self._calls: dict[str, _TextCall] = {}
        self._calls_lock = asyncio.Lock()

    # ---- provider --------------------------------------------------------
    def _genai(self) -> Any:
        """The Gemini text client, created once. Raises without a key."""
        if self._client is None:
            from google import genai

            key = getattr(self.settings, "gemini_api_key", "") or os.environ.get("GEMINI_API_KEY", "")
            if not key:
                raise RuntimeError("GEMINI_API_KEY is required by the /turns adapter")
            self._client = genai.Client(api_key=key)
        return self._client

    # ---- call lifecycle --------------------------------------------------
    async def _call_for(self, call_id: str) -> _TextCall:
        async with self._calls_lock:
            call = self._calls.get(call_id)
            if call is not None:
                call.last_seen = time.monotonic()
                return call
            ctx = CallContext(data_dir=self.data_dir, call_id=call_id)
            # The route-owned boundary flush_call already honours. Setting it
            # here is what keeps a bench run off the real platform.
            ctx.submit_actions = self.submit_actions
            ctx.audit(
                "text_adapter_call_open",
                {"model": self.model, "submit_actions": self.submit_actions},
            )
            toolbox = ToolBox(ctx, self.settings)
            # Same background reading of every finalised caller turn the
            # voice path does; it abstains by itself when Jev is absent.
            toolbox.watch_caller_turns()
            call = _TextCall(ctx=ctx, toolbox=toolbox)
            self._calls[call_id] = call
            return call

    async def _sweep_idle(self, now: float) -> None:
        stale = [
            call_id
            for call_id, call in self._calls.items()
            if now - call.last_seen > IDLE_CLOSE_SECONDS
        ]
        for call_id in stale:
            await self.close(call_id)

    async def close(self, call_id: str) -> bool:
        """End a call: settle the tail, free the sidecar. True when it existed."""
        async with self._calls_lock:
            call = self._calls.pop(call_id, None)
        if call is None:
            return False
        async with call.lock:
            call.ctx.mark_stopped()
            if call.settled == 0:
                # Nothing ever reached the wire, so flush_call's no-action
                # fallback is exactly right. It cannot rescue a bench case —
                # the runner already read the record — but it keeps the trace
                # honest and matches what the scored path would have done.
                await flush_call(call.ctx, self.settings)
            else:
                call.ctx.submitted = True  # already on the wire, turn by turn
                call.ctx.audit("flush_done", {"settled": call.settled})
            await call.toolbox.aclose()
        return True

    async def aclose(self) -> None:
        for call_id in list(self._calls):
            await self.close(call_id)

    # ---- submission ------------------------------------------------------
    async def _settle(self, call: _TextCall) -> None:
        """POST whatever the brain queued during this turn. Never waits."""
        pending = call.ctx.queued_actions[call.settled :]
        if not pending:
            return
        if not call.ctx.submit_actions:
            # Same boundary flush_call checks. This path builds its own
            # Submitter, so the check has to be repeated here or the guard
            # only covers the end of the call and not the middle of it.
            call.ctx.audit(
                "flush_skipped", {"reason": "not_loopback", "actions": len(pending)}
            )
            call.settled = len(call.ctx.queued_actions)
            return
        if not self.settings.prosper_api_key:
            for action in pending:
                logger.error(
                    "WOULD SUBMIT call={} route={} fields={}",
                    call.ctx.call_id,
                    action.get("route"),
                    sorted(k for k in action if k != "route"),
                )
            call.settled = len(call.ctx.queued_actions)
            return

        from agent.scheduling.submit import Submitter

        deadline = time.monotonic() + self.settings.submit_window_seconds
        submitter = Submitter(self.settings.prosper_api_base_url, self.settings.prosper_api_key)
        try:
            for action in pending:
                route = action.get("route", "")
                try:
                    await submitter.post_route(action, call.ctx.call_id, deadline=deadline)
                    call.ctx.audit("submitted", {"route": route})
                except Exception as exc:  # noqa: BLE001 - one action must not end the call
                    logger.error("call {}: submit {} failed: {}", call.ctx.call_id, route, exc)
                    call.ctx.audit("submit_failed", {"route": route, "error": str(exc)})
        finally:
            await submitter.close()
        call.settled = len(call.ctx.queued_actions)

    # ---- the turn --------------------------------------------------------
    async def turn(self, call_id: str, text: str) -> str:
        """One caller utterance in, one agent reply out."""
        await self._sweep_idle(time.monotonic())
        call = await self._call_for(call_id)
        async with call.lock:
            try:
                reply = await asyncio.wait_for(
                    self._generate(call, text), timeout=TURN_TIMEOUT_SECONDS
                )
            except TimeoutError:
                call.ctx.audit("text_turn_timeout", {"seconds": TURN_TIMEOUT_SECONDS})
                raise
            await self._settle(call)
            return reply

    async def _generate(self, call: _TextCall, text: str) -> str:
        from google.genai import types

        wrappers = _tool_wrappers(call.toolbox)
        config = types.GenerateContentConfig(
            system_instruction=prompts.SYSTEM_PROMPT,
            tools=[{"function_declarations": _declarations(wrappers)}],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        call.ctx.add_transcript("caller", text)
        call.history.append(types.Content(role="user", parts=[types.Part(text=text)]))

        client = self._genai()
        reply = ""
        for _ in range(MAX_TOOL_ROUNDS):
            response = await client.aio.models.generate_content(
                model=self.model, contents=call.history, config=config
            )
            candidate = (response.candidates or [None])[0]
            content = getattr(candidate, "content", None)
            if content is not None:
                call.history.append(content)
            calls = response.function_calls or []
            if not calls:
                reply = response.text or ""
                break
            parts = []
            for fc in calls:
                wrapper = wrappers.get(fc.name or "")
                args = dict(fc.args or {})
                if wrapper is None:
                    result: Any = {"error": f"unknown tool {fc.name!r}"}
                else:
                    call.ctx.audit("text_tool_call", {"tool": fc.name})
                    result = await _invoke(wrapper, args)
                parts.append(
                    types.Part.from_function_response(
                        name=fc.name or "", response={"result": result}
                    )
                )
            call.history.append(types.Content(role="user", parts=parts))
        else:
            # Out of rounds with the model still reaching for tools. Silence is
            # the worst answer a receptionist can give, so ask once more with
            # the tools withdrawn: it has to answer in words or not at all.
            logger.error("call {}: tool rounds exhausted, answering without tools", call.ctx.call_id)
            call.ctx.audit("text_tool_rounds_exhausted", {"limit": MAX_TOOL_ROUNDS})
            closing = types.GenerateContentConfig(system_instruction=prompts.SYSTEM_PROMPT)
            response = await client.aio.models.generate_content(
                model=self.model, contents=call.history, config=closing
            )
            reply = response.text or ""

        if reply:
            call.ctx.add_transcript("assistant", reply)
        return reply


# ---- HTTP surface --------------------------------------------------------
router = APIRouter(tags=["turns"])
_adapter: TextAdapter | None = None


def _ops_access(request: Request) -> None:
    """Same gate the ops console uses: loopback, or OPS_TOKEN.

    Being opt-in is not enough on its own. A reachable /turns lets anyone
    drive the real ToolBox and POST submissions against the live Prosper API
    with our key — strictly worse than reading a transcript. The bench runs
    on 127.0.0.1, so it is unaffected; a deployed host that sets
    TURNS_ADAPTER by accident answers nothing until OPS_TOKEN is set too.

    Imported lazily so the console app is not built just by importing the
    voice server.
    """
    from agent.ops.console import require_ops_access

    require_ops_access(request)


def set_adapter(adapter: TextAdapter | None) -> None:
    """Install the process-wide adapter. Tests and mount_if_enabled only."""
    global _adapter
    _adapter = adapter


def _require_adapter() -> TextAdapter:
    if _adapter is None:  # pragma: no cover - the router is never mounted without one
        raise HTTPException(503, "text adapter not configured")
    return _adapter


@router.post("/turns")
async def post_turn(body: TurnRequest, _: None = Depends(_ops_access)) -> TurnReply:
    """The evaluator's only call. A failure here is a 5xx on purpose."""
    adapter = _require_adapter()
    if body.event == HANGUP_EVENT:
        # The caller hung up. Close now, synchronously: the runner closes the
        # submission window right after this response and only then reads the
        # record, so a flush that starts later is a flush nobody counts.
        await adapter.close(body.call_id)
        return TurnReply(reply="", ended=True)
    try:
        reply = await adapter.turn(body.call_id, body.text or "")
    except TimeoutError as exc:
        raise HTTPException(504, "turn timed out") from exc
    except Exception as exc:  # surface adapter defects to the runner, never as a 200
        logger.exception("text turn failed for call {}: {}", body.call_id, exc)
        raise HTTPException(500, f"text turn failed: {type(exc).__name__}") from exc
    return TurnReply(reply=reply)


@router.post("/turns/{call_id}/close")
async def post_close(call_id: str, _: None = Depends(_ops_access)) -> dict[str, str]:
    """End a call deterministically. The runner does not call this today."""
    existed = await _require_adapter().close(call_id)
    return {"call_id": call_id, "state": "closed" if existed else "unknown"}


def mount_if_enabled(app: FastAPI, settings: Any) -> bool:
    """Mount the adapter when TURNS_ADAPTER is set. True when mounted."""
    if not adapter_enabled():
        return False
    set_adapter(TextAdapter(settings))
    app.include_router(router)
    logger.warning(
        "text adapter MOUNTED at POST /turns ({}={}) - test surface, never the scored process",
        ENV_FLAG,
        os.environ.get(ENV_FLAG),
    )
    return True
