"""The harness side of a call: a Twilio Media Streams WebSocket client.

Speaks the wire format from docs/prosper/call-contract.md §1 - camelCase
keys, string `sequenceNumber`/`chunk`/`timestamp`, 20 ms µ-law frames
base64-encoded in `media.payload`, `connected` → `start` → `media*` →
`stop`. The evaluator plays the carrier's part, exactly like the official
harness.

Latency is measured per caller turn: end of the caller's last outbound
frame → the agent's first inbound media frame after it (plan §13,
"fin del habla del paciente → primer audio audible de respuesta").

Turns flagged `interrupt_on_agent_audio` barge in: the caller stops its
own utterance the moment the agent starts speaking, like a real
interruption (plan §15).
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
class PlayTurn:
    """One caller utterance to play on the wire."""

    frames: list[bytes]
    interrupt_on_agent_audio: bool = False


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
    # Per-turn response latency in ms (plan §13); None where the agent
    # never answered that turn before the next one started or the call ended.
    turn_latencies_ms: list[float | None] = field(default_factory=list)
    first_audio_ms: float | None = None  # connect → first inbound media frame
    # Raw audio evidence: µ-law bytes both directions.
    agent_audio: bytes = b""
    caller_audio: bytes = b""
    # Barge-in events: {"turn": i, "at_ms": x, "agent_tail_ms": y}.
    interrupts: list[dict] = field(default_factory=list)


async def dial(
    ws_url: str,
    call_id: str,
    turns: list[PlayTurn | list[bytes]],
    from_number: str | None = None,
    frame_interval_s: float = 0.02,
    open_timeout_s: float = 10.0,
    after_send_idle_s: float = 5.0,
    max_call_s: float = 180.0,
) -> CallEvidence:
    """Play one call: handshake, stream `turns` in real time, then stop.

    `turns` is a list of `PlayTurn` (or bare frame lists, for back-compat).
    Waits up to `after_send_idle_s` for the agent's tail-end audio before
    sending `stop` - submissions during the open call are valid, so the
    caller does not need to linger beyond the caller-side content.
    """
    play_turns = [t if isinstance(t, PlayTurn) else PlayTurn(list(t)) for t in turns]
    ev = CallEvidence(call_id=call_id, connected_at=time.monotonic())
    last_inbound_at = [ev.connected_at]
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

            awaiting_reply_at: list[float | None] = [None]

            async def _recv() -> None:
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    event = msg.get("event")
                    if event == "media":
                        now = time.monotonic()
                        last_inbound_at[0] = now
                        if ev.first_audio_ms is None:
                            ev.first_audio_ms = round((now - ev.connected_at) * 1000, 1)
                        ev.frames_received += 1
                        payload = msg.get("media", {}).get("payload", "")
                        ev.agent_bytes += len(payload)
                        try:
                            ev.agent_audio += base64.b64decode(payload)
                        except ValueError:
                            ev.agent_audio += b""  # malformed payload: count kept, bytes skipped
                        if awaiting_reply_at[0] is not None:
                            ev.turn_latencies_ms.append(
                                round((now - awaiting_reply_at[0]) * 1000, 1)
                            )
                            awaiting_reply_at[0] = None
                    elif event == "mark":
                        ev.marks.append(str(msg.get("mark", {}).get("name", "")))

            recv_task = asyncio.create_task(_recv())
            try:
                seq = 1
                for turn_idx, turn in enumerate(play_turns):
                    if time.monotonic() - ev.connected_at > max_call_s:
                        ev.error = "caller-side max_call_s reached"
                        break
                    received_at_turn_start = ev.frames_received
                    barged = False
                    for frame_bytes in turn.frames:
                        if (
                            turn.interrupt_on_agent_audio
                            and ev.frames_received > received_at_turn_start
                        ):
                            # Agent started talking and the caller barges in:
                            # drop the rest of this utterance.
                            ev.interrupts.append(
                                {
                                    "turn": turn_idx,
                                    "at_ms": round(
                                        (time.monotonic() - ev.connected_at) * 1000, 1
                                    ),
                                }
                            )
                            barged = True
                            break
                        seq += 1
                        await ws.send(
                            json.dumps(
                                {
                                    "event": "media",
                                    "sequenceNumber": str(seq),
                                    "media": {
                                        "track": "inbound",
                                        "chunk": str(seq - 1),
                                        "timestamp": str(seq * 20),
                                        "payload": base64.b64encode(frame_bytes).decode(),
                                    },
                                    "streamSid": stream_sid,
                                }
                            )
                        )
                        ev.frames_sent += 1
                        ev.caller_audio += frame_bytes
                        await asyncio.sleep(frame_interval_s)
                    # Caller finished (or interrupted) this utterance: the
                    # clock for the agent's response latency starts now. If
                    # the previous turn was never answered, mark it.
                    if not barged:
                        if awaiting_reply_at[0] is not None:
                            ev.turn_latencies_ms.append(None)
                        awaiting_reply_at[0] = time.monotonic()
                # Let the agent finish speaking before hanging up.
                await asyncio.sleep(after_send_idle_s)
            finally:
                await ws.send(json.dumps({"event": "stop", "sequenceNumber": str(seq + 1), "streamSid": stream_sid}))
                ev.stopped_at = time.monotonic()
                recv_task.cancel()
                try:
                    await recv_task
                except asyncio.CancelledError:
                    pass
            # How long the agent kept talking after the last barge-in
            # (plan §15: dejar de hablar rápido no basta si reservó mal).
            for intr in ev.interrupts:
                intr["agent_tail_ms"] = round(
                    (last_inbound_at[0] - ev.connected_at) * 1000 - intr["at_ms"], 1
                )
    except Exception as exc:  # noqa: BLE001 - transport failure is evidence
        ev.error = f"{type(exc).__name__}: {exc}"
    return ev
