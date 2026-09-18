"""Test double: a minimal agent that speaks the wire contract and submits
canned actions. Exists to prove the evaluator works end-to-end before the
real agent is plugged in - it verifies call setup, the submission window,
and scoring, not the agent.

Control channel (evaluator side, not part of the wire contract):

    POST /control {"actions": [{"route": "book", "fields": {...}}]}
    POST /control {"actions": null}          # next call submits nothing

The queued action list applies to the next accepted socket, FIFO.
"""
from __future__ import annotations

import asyncio
import base64
import json
from collections import deque
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

TONE_FRAME = bytes((i % 40) + 100 for i in range(160))  # quiet non-silence pattern


class _Control(BaseModel):
    actions: list[dict[str, Any]] | None = None  # [{"route": ..., "fields": {...}}]


def create_app(submit_base: str, api_key: str = "pk-local-eval") -> FastAPI:
    app = FastAPI(title="Prosper evaluator - test double")
    pending: deque[list[dict[str, Any]] | None] = deque()

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/control")
    def control(body: _Control) -> dict[str, str]:
        pending.append(body.actions)
        return {"state": "queued", "depth": str(len(pending))}

    async def _submit(call_id: str, actions: list[dict[str, Any]] | None) -> None:
        if not actions:
            return
        async with httpx.AsyncClient(base_url=submit_base.rstrip("/"), timeout=10) as client:
            for item in actions:
                payload = {"call_id": call_id, **item.get("fields", {})}
                await client.post(
                    f"/api/v1/submit/{item['route']}",
                    json=payload,
                    headers={"X-Api-Key": api_key},
                )

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        call_id: str | None = None
        seq = 0
        actions = pending.popleft() if pending else []

        async def _talkback() -> None:
            # Emit low-level "audio" so the caller sees outbound media flowing.
            nonlocal seq
            while True:
                seq += 1
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
                elif msg.get("event") == "stop":
                    break
        except WebSocketDisconnect:
            pass
        finally:
            talk.cancel()
            if call_id:
                await _submit(call_id, actions)

    return app


def serve(submit_base: str, host: str = "127.0.0.1", port: int = 7870, api_key: str = "pk-local-eval") -> None:
    uvicorn.run(create_app(submit_base, api_key), host=host, port=port, log_level="warning")
