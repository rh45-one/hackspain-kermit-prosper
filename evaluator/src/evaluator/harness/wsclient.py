"""The harness side of a call: a Twilio Media Streams WebSocket client.

Speaks the wire format from docs/prosper/call-contract.md §1 - camelCase
keys, string `sequenceNumber`/`chunk`/`timestamp`, 20 ms µ-law frames
base64-encoded in `media.payload`, `connected` → `start` → `media*` →
`stop`. The evaluator plays the carrier's part, exactly like the official
harness.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import websockets

FRAME_BYTES = 160  # 20 ms of 8 kHz µ-law
SILENCE_FRAME = b"\xff" * FRAME_BYTES  # µ-law silence


def load_audio(path: str | Path) -> list[bytes]:
    """Load a raw 8 kHz µ-law file and chunk it into 20 ms frames."""
    data = Path(path).read_bytes()
    frames = [data[i : i + FRAME_BYTES] for i in range(0, len(data), FRAME_BYTES)]
    if frames and len(frames[-1]) < FRAME_BYTES:
        frames[-1] = frames[-1].ljust(FRAME_BYTES, b"\xff")
    return frames


def silence(ms: int) -> list[bytes]:
    return [SILENCE_FRAME] * max(1, ms // 20)


@dataclass
class CallEvidence:
    """What the harness observed on the wire, for the evidence trail."""

    call_id: str
    stream_sid: str = field(default_factory=lambda: uuid.uuid4().hex)
    frames_sent: int = 0
    frames_received: int = 0
    agent_bytes: int = 0
    marks: list[str] = field(default_factory=list)
    connected_at: float = 0.0
    stopped_at: float = 0.0
    error: str | None = None


async def dial(
    ws_url: str,
    call_id: str,
    frames: list[bytes],
    from_number: str | None = None,
    frame_interval_s: float = 0.02,
    open_timeout_s: float = 10.0,
    after_send_idle_s: float = 5.0,
    max_call_s: float = 180.0,
) -> CallEvidence:
    """Play one call: handshake, stream `frames` in real time, then stop.

    Waits up to `after_send_idle_s` for the agent's tail-end audio before
    sending `stop` - submissions during the open call are valid, so the
    caller does not need to linger beyond the caller-side content.
    """
    ev = CallEvidence(call_id=call_id, connected_at=time.monotonic())
    try:
        async with websockets.connect(ws_url, open_timeout=open_timeout_s) as ws:
            stream_sid = ev.stream_sid
            await ws.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
            start = {
                "event": "start",
                "sequenceNumber": "1",
                "start": {
                    "streamSid": stream_sid,
                    "accountSid": "AC-local-eval",
                    "callSid": call_id,
                    "tracks": ["inbound"],
                    "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
                    "customParameters": (
                        {"call_id": call_id, "from_number": from_number}
                        if from_number
                        else {"call_id": call_id}
                    ),
                },
                "streamSid": stream_sid,
            }
            await ws.send(json.dumps(start))

            async def _recv() -> None:
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    event = msg.get("event")
                    if event == "media":
                        ev.frames_received += 1
                        payload = msg.get("media", {}).get("payload", "")
                        ev.agent_bytes += len(payload)
                    elif event == "mark":
                        ev.marks.append(str(msg.get("mark", {}).get("name", "")))

            recv_task = asyncio.create_task(_recv())
            try:
                for i, frame_bytes in enumerate(frames):
                    if time.monotonic() - ev.connected_at > max_call_s:
                        ev.error = "caller-side max_call_s reached"
                        break
                    await ws.send(
                        json.dumps(
                            {
                                "event": "media",
                                "sequenceNumber": str(i + 2),
                                "media": {
                                    "track": "inbound",
                                    "chunk": str(i + 1),
                                    "timestamp": str(i * 20),
                                    "payload": base64.b64encode(frame_bytes).decode(),
                                },
                                "streamSid": stream_sid,
                            }
                        )
                    )
                    await asyncio.sleep(frame_interval_s)
                # Let the agent finish speaking before hanging up.
                await asyncio.sleep(after_send_idle_s)
            finally:
                await ws.send(json.dumps({"event": "stop", "sequenceNumber": str(len(frames) + 2), "streamSid": stream_sid}))
                ev.stopped_at = time.monotonic()
                recv_task.cancel()
                try:
                    await recv_task
                except asyncio.CancelledError:
                    pass
    except Exception as exc:  # noqa: BLE001 - transport failure is evidence
        ev.error = f"{type(exc).__name__}: {exc}"
    return ev
