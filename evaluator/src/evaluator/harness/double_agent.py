"""Test double: a minimal agent that speaks the wire contract and submits
canned actions. Exists to prove the evaluator works end-to-end before the
real agent is plugged in - it verifies call setup, the submission window,
and scoring, not the agent.

Control channel (evaluator side, not part of the wire contract):

    POST /control {"call_id": "C-1", "actions": [{"route": "book", "fields": {...}}]}
    POST /control {"actions": [...]}          # legacy FIFO, applies to next socket
    POST /control {"actions": null}           # next call submits nothing

    GET  /usage/calls/{call_id}               # deterministic usage + cost

Per-call control is required for concurrent runs: global FIFO queues let
one socket consume another call's canned actions and contaminate results.
Usage/cost is fabricated deterministically from what the double observed,
so the runner's cost plumbing can be tested end-to-end.
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


def create_app(submit_base: str, api_key: str = "pk-local-eval") -> FastAPI:
    app = FastAPI(title="Prosper evaluator - test double")
    pending_fifo: deque[list[dict[str, Any]] | None] = deque()
    per_call: dict[str, list[dict[str, Any]] | None] = {}
    usage: dict[str, dict[str, Any]] = {}

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/control")
    def control(body: _Control) -> dict[str, str]:
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


def serve(submit_base: str, host: str = "127.0.0.1", port: int = 7870, api_key: str = "pk-local-eval") -> None:
    uvicorn.run(create_app(submit_base, api_key), host=host, port=port, log_level="warning")
