"""Test double: a minimal agent that speaks the wire contract and submits
canned actions. Exists to prove the evaluator works end-to-end before the
real agent is plugged in - it verifies call setup, the submission window,
and scoring, not the agent.

It speaks both paths the runner knows: the Twilio-style WebSocket at
`/ws` and the text adapter at `/turns` (README, "Adaptador de texto
`/turns`"). The text side exists so the text path can be verified
end-to-end here, before the real agent implements it.

Control channel (evaluator side, not part of the wire contract):

    POST /control {"call_id": "C-1", "actions": [{"route": "book", "fields": {...}}]}
    POST /control {"actions": [...]}          # legacy FIFO, applies to next socket
    POST /control {"actions": null}           # next call submits nothing
    POST /control {"call_id": "C-1", "replies": ["...", "..."]}   # text script
    POST /control {"call_id": "C-1", "leak": "12345678Z"}         # leaky reply

    GET  /usage/calls/{call_id}               # deterministic usage + cost

Per-call control is required for concurrent runs: global FIFO queues let
one socket consume another call's canned actions and contaminate results.
Usage/cost is fabricated deterministically from what the double observed,
so the runner's cost plumbing can be tested end-to-end. `replies` and
`leak` only affect `/turns`; `leak` makes the double say a protected field
out loud so the problem-14 check can be exercised against a known failure.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
from collections import deque
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

TONE_FRAME = bytes((i % 40) + 100 for i in range(160))  # quiet non-silence pattern


class _Control(BaseModel):
    call_id: str | None = None
    actions: list[dict[str, Any]] | None = None  # [{"route": ..., "fields": {...}}]
    replies: list[str] | None = None  # text path: what the double says, in order
    leak: str | None = None  # text path: a protected value to blurt out


class _TurnBody(BaseModel):
    """Text adapter request body - the contract the real agent implements."""

    call_id: str
    text: str | None = None
    event: str | None = None  # "hangup" closes the call; anything else is a turn


# Default text script: greet, then confirm. The second line trips the rules
# patient's closing markers, so a scripted conversation terminates by itself
# instead of running to `limits.max_turns`.
DEFAULT_REPLIES = (
    "Clínica Arenal, ¿en qué puedo ayudarle?",
    "De acuerdo, confirmo la cita. ¿Algo más?",
    "Gracias por llamar. Hasta luego.",
)


def create_app(submit_base: str, api_key: str = "pk-local-eval") -> FastAPI:
    app = FastAPI(title="Prosper evaluator - test double")
    pending_fifo: deque[list[dict[str, Any]] | None] = deque()
    per_call: dict[str, list[dict[str, Any]] | None] = {}
    usage: dict[str, dict[str, Any]] = {}
    scripts: dict[str, list[str]] = {}
    leaks: dict[str, str] = {}
    text_calls: dict[str, dict[str, Any]] = {}
    defaults: dict[str, Any] = {"replies": None, "leak": None}

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/control")
    def control(body: _Control) -> dict[str, str]:
        # `replies`/`leak` steer the text path. Without a call_id they apply
        # to every text call from now on: the runner mints the call_id, so a
        # caller that did not start the call cannot name it.
        if body.replies is not None:
            if body.call_id is None:
                defaults["replies"] = body.replies
            else:
                scripts[body.call_id] = body.replies
        if body.leak is not None:
            if body.call_id is None:
                defaults["leak"] = body.leak
            else:
                leaks[body.call_id] = body.leak
        # `actions` is only queued when it was actually sent: a control call
        # that only configures the text side must not enqueue a silent call.
        if "actions" not in body.model_fields_set:
            return {"state": "configured", "call_id": body.call_id or ""}
        if body.call_id is not None:
            per_call[body.call_id] = body.actions
            return {"state": "queued", "call_id": body.call_id}
        pending_fifo.append(body.actions)
        return {"state": "queued", "depth": str(len(pending_fifo))}

    @app.get("/usage/calls/{call_id}")
    def get_usage(call_id: str) -> dict[str, Any]:
        """Deterministic fabricated usage - enough to exercise cost plumbing."""
        u = usage.get(call_id)
        if u is None:
            return {"call_id": call_id, "cost": None, "usage": {}}
        # Fake but deterministic pricing: $0.005/min audio + $0.001/submission.
        minutes = u["media_frames_out"] * 0.02 / 60
        cost = round(minutes * 0.005 + u["submitted"] * 0.001, 6)
        return {
            "call_id": call_id,
            "cost": cost,
            "usage": {
                "audio_seconds": round(u["media_frames_out"] * 0.02, 1),
                "submissions": u["submitted"],
                "provider": "double",
            },
        }

    async def _submit(call_id: str, actions: list[dict[str, Any]] | None) -> int:
        if not actions:
            return 0
        sent = 0
        async with httpx.AsyncClient(base_url=submit_base.rstrip("/"), timeout=10) as client:
            for item in actions:
                payload = {"call_id": call_id, **item.get("fields", {})}
                resp = await client.post(
                    f"/api/v1/submit/{item['route']}",
                    json=payload,
                    headers={"X-Api-Key": api_key},
                )
                if resp.status_code < 400:
                    sent += 1
        return sent

    @app.post("/turns")
    async def turns(body: _TurnBody) -> dict[str, Any]:
        """Text adapter: one caller utterance in, one agent utterance out.

        Mirrors the contract the real agent must implement: the first POST
        for a call_id opens it, `event: "hangup"` closes it, and the double
        submits its canned actions exactly once, on close - the same moment
        the real agent flushes when the socket drops.
        """
        state = text_calls.setdefault(body.call_id, {"turns": 0, "submitted": None})

        async def _flush() -> None:
            if state["submitted"] is None:
                state["submitted"] = await _submit(body.call_id, per_call.get(body.call_id))
                usage[body.call_id] = {
                    "media_frames_out": state["turns"] * 50,  # ≈1 s of audio per turn
                    "submitted": state["submitted"],
                    "duration_s": 0.0,
                }

        if body.event == "hangup":
            await _flush()
            return {"reply": None, "ended": True}

        script = scripts.get(body.call_id) or defaults["replies"] or list(DEFAULT_REPLIES)
        reply = script[min(state["turns"], len(script) - 1)] if script else ""
        leak = leaks.get(body.call_id) or defaults["leak"]
        if leak and state["turns"] == 0:
            reply = f"{reply} Confirmo su DNI {leak}."
        state["turns"] += 1
        ended = state["turns"] >= len(script)
        if ended:
            await _flush()
        return {"reply": reply, "ended": ended}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        call_id: str | None = None
        seq = 0
        # Resolve actions lazily at `start`, once call_id is known; fall
        # back to the FIFO queue for back-compat with sequential runs.
        actions: list[dict[str, Any]] | None = None
        started_at = time.monotonic()
        frames_out = 0

        async def _talkback() -> None:
            nonlocal seq, frames_out
            while True:
                seq += 1
                frames_out += 1
                await websocket.send_text(
                    json.dumps(
                        {
                            "event": "media",
                            "streamSid": "double",
                            "sequenceNumber": str(seq),
                            "media": {
                                "track": "outbound",
                                "chunk": str(seq),
                                "timestamp": str(seq * 20),
                                "payload": base64.b64encode(TONE_FRAME).decode(),
                            },
                        }
                    )
                )
                await asyncio.sleep(0.02)

        talk = asyncio.create_task(_talkback())
        try:
            async for raw in websocket.iter_text():
                msg = json.loads(raw)
                if msg.get("event") == "start":
                    call_id = msg["start"]["callSid"]
                    if call_id in per_call:
                        actions = per_call.pop(call_id)
                    elif pending_fifo:
                        actions = pending_fifo.popleft()
                elif msg.get("event") == "stop":
                    break
        except WebSocketDisconnect:
            pass
        finally:
            talk.cancel()
            if call_id:
                submitted = await _submit(call_id, actions)
                usage[call_id] = {
                    "media_frames_out": frames_out,
                    "submitted": submitted,
                    "duration_s": round(time.monotonic() - started_at, 2),
                }

    return app


def serve(submit_base: str, host: str = "127.0.0.1", port: int = 18770, api_key: str = "pk-local-eval") -> None:
    uvicorn.run(create_app(submit_base, api_key), host=host, port=port, log_level="warning")
