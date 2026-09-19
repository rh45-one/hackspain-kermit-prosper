"""The harness side of a call: a Twilio Media Streams WebSocket client.

Speaks the wire format from docs/prosper/call-contract.md §1 - camelCase
keys, string `sequenceNumber`/`chunk`/`timestamp`, 20 ms µ-law frames
base64-encoded in `media.payload`, `connected` → `start` → `media*` →
`stop`. The evaluator plays the carrier's part, exactly like the official
harness.

Two ways in, one wire implementation:

- `dial()` plays a whole precomputed script - the experiment runner's path.
- `CallSession` is the same call without a script: send caller audio when
  you have it, stream the agent's audio while it arrives, stop when you are
  done. The manual tester needs this; a chat has no turns to enumerate in
  advance.

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
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

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


class CallSession:
    """A live, duplex call: send caller audio, stream agent audio, stop.

    The handshake, the frame envelope, the evidence bookkeeping and the
    teardown live here exactly once, so `dial()` and the manual tester cannot
    drift apart on the wire. A transport failure is recorded in
    `evidence.error` and re-raised from `open()`/`send_frames()`: a person
    driving the tester needs to see it, while a scripted run keeps its
    evidence trail either way.
    """

    def __init__(
        self,
        ws_url: str,
        call_id: str,
        from_number: str | None = None,
        frame_interval_s: float = 0.02,
        open_timeout_s: float = 10.0,
        max_call_s: float = 180.0,
    ) -> None:
        self.ws_url = ws_url
        self.from_number = from_number
        self.frame_interval_s = frame_interval_s
        self.open_timeout_s = open_timeout_s
        self.max_call_s = max_call_s
        self.evidence = CallEvidence(call_id=call_id, connected_at=time.monotonic())
        self._ws: Any = None
        self._recv_task: asyncio.Task[None] | None = None
        self._inbound: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._seq = 1
        self._awaiting_reply_at: float | None = None
        self._last_inbound_at = self.evidence.connected_at

    # ---- lifecycle -------------------------------------------------------
    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.evidence.connected_at

    async def open(self) -> CallEvidence:
        """Connect and complete the `connected` → `start` handshake."""
        stream_sid = self.evidence.stream_sid
        start = {
            "event": "start",
            "sequenceNumber": "1",
            "start": {
                "streamSid": stream_sid,
                "accountSid": "AC-local-eval",
                "callSid": self.evidence.call_id,
                "tracks": ["inbound"],
                "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
                "customParameters": (
                    {"call_id": self.evidence.call_id, "from_number": self.from_number}
                    if self.from_number
                    else {"call_id": self.evidence.call_id}
                ),
            },
            "streamSid": stream_sid,
        }
        try:
            self._ws = await websockets.connect(self.ws_url, open_timeout=self.open_timeout_s)
            await self._ws.send(
                json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"})
            )
            await self._ws.send(json.dumps(start))
        except Exception as exc:  # transport failure is evidence
            self.evidence.error = f"{type(exc).__name__}: {exc}"
            raise
        self._recv_task = asyncio.create_task(self._recv())
        return self.evidence

    async def close(self) -> CallEvidence:
        """Send `stop`, cancel the reader and settle the interrupt evidence."""
        ws = self._ws
        if ws is not None:
            try:
                await ws.send(
                    json.dumps(
                        {
                            "event": "stop",
                            "sequenceNumber": str(self._seq + 1),
                            "streamSid": self.evidence.stream_sid,
                        }
                    )
                )
            except Exception as exc:  # noqa: BLE001 - keep evidence, never hide it
                self.evidence.error = self.evidence.error or f"{type(exc).__name__}: {exc}"
            self.evidence.stopped_at = time.monotonic()
        if self._recv_task is not None:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            self._recv_task = None
        if ws is not None:
            await ws.close()
            self._ws = None
        await self._inbound.put(None)
        return self.finalize()

    def finalize(self) -> CallEvidence:
        """How long the agent kept talking after each barge-in (plan §15)."""
        for intr in self.evidence.interrupts:
            intr["agent_tail_ms"] = round(
                (self._last_inbound_at - self.evidence.connected_at) * 1000 - intr["at_ms"], 1
            )
        return self.evidence

    async def __aenter__(self) -> Self:
        await self.open()
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()

    # ---- caller side -----------------------------------------------------
    async def send_frames(
        self,
        frames: list[bytes],
        *,
        interrupt_on_agent_audio: bool = False,
        turn: int = 0,
    ) -> bool:
        """Play one caller utterance. True when the caller barged out of it."""
        received_at_start = self.evidence.frames_received
        for frame in frames:
            if interrupt_on_agent_audio and self.evidence.frames_received > received_at_start:
                # Agent started talking and the caller barges in: drop the
                # rest of this utterance.
                self.evidence.interrupts.append({"turn": turn, "at_ms": self._ms()})
                return True
            await self._send_media(frame)
            await asyncio.sleep(self.frame_interval_s)
        # Caller finished this utterance: the clock for the agent's response
        # latency starts now. If the previous turn was never answered, mark it.
        if self._awaiting_reply_at is not None:
            self.evidence.turn_latencies_ms.append(None)
        self._awaiting_reply_at = time.monotonic()
        return False

    async def _send_media(self, frame: bytes) -> None:
        self._seq += 1
        await self._ws.send(
            json.dumps(
                {
                    "event": "media",
                    "sequenceNumber": str(self._seq),
                    "media": {
                        "track": "inbound",
                        "chunk": str(self._seq - 1),
                        "timestamp": str(self._seq * 20),
                        "payload": base64.b64encode(frame).decode(),
                    },
                    "streamSid": self.evidence.stream_sid,
                }
            )
        )
        self.evidence.frames_sent += 1
        self.evidence.caller_audio += frame

    # ---- agent side ------------------------------------------------------
    async def inbound(self) -> AsyncIterator[bytes]:
        """Agent µ-law bytes as they arrive; ends when the session closes."""
        while True:
            chunk = await self._inbound.get()
            if chunk is None:
                return
            yield chunk

    async def drain_audio(
        self,
        *,
        idle_ms: float = 800.0,
        max_ms: float = 15000.0,
        first_wait_ms: float | None = None,
    ) -> bytes:
        """Collect agent audio until it has been quiet for `idle_ms`.

        A chat has no frame count to wait for, so the end of the agent's reply
        is inferred from silence. `first_wait_ms` (default `idle_ms`) is how
        long the reply may take to *start*: a greeting arrives seconds after
        connect, while a gap inside one reply is short. Waiting `idle_ms` for
        the first frame makes the caller talk over the greeting, which the
        agent reads as an interruption. Returns less than a full reply when
        `max_ms` cuts the wait short.
        """
        collected = b""
        deadline = time.monotonic() + max_ms / 1000
        timeout = (idle_ms if first_wait_ms is None else first_wait_ms) / 1000
        while time.monotonic() < deadline:
            try:
                chunk = await asyncio.wait_for(self._inbound.get(), timeout=timeout)
            except TimeoutError:
                break
            if chunk is None:
                break
            collected += chunk
            timeout = idle_ms / 1000
        return collected

    async def _recv(self) -> None:
        async for raw in self._ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            event = msg.get("event")
            if event == "media":
                now = time.monotonic()
                self._last_inbound_at = now
                if self.evidence.first_audio_ms is None:
                    self.evidence.first_audio_ms = round(
                        (now - self.evidence.connected_at) * 1000, 1
                    )
                self.evidence.frames_received += 1
                payload = msg.get("media", {}).get("payload", "")
                self.evidence.agent_bytes += len(payload)
                try:
                    chunk = base64.b64decode(payload)
                except ValueError:
                    chunk = b""  # malformed payload: count kept, bytes skipped
                if chunk:
                    self.evidence.agent_audio += chunk
                    await self._inbound.put(chunk)
                if self._awaiting_reply_at is not None:
                    self.evidence.turn_latencies_ms.append(
                        round((now - self._awaiting_reply_at) * 1000, 1)
                    )
                    self._awaiting_reply_at = None
            elif event == "mark":
                self.evidence.marks.append(str(msg.get("mark", {}).get("name", "")))

    def _ms(self) -> float:
        return round(self.elapsed_s * 1000, 1)


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
    session = CallSession(
        ws_url,
        call_id,
        from_number=from_number,
        frame_interval_s=frame_interval_s,
        open_timeout_s=open_timeout_s,
        max_call_s=max_call_s,
    )
    ev = session.evidence
    try:
        await session.open()
        try:
            for turn_idx, turn in enumerate(play_turns):
                if session.elapsed_s > max_call_s:
                    ev.error = "caller-side max_call_s reached"
                    break
                await session.send_frames(
                    turn.frames,
                    interrupt_on_agent_audio=turn.interrupt_on_agent_audio,
                    turn=turn_idx,
                )
            # Let the agent finish speaking before hanging up.
            await asyncio.sleep(after_send_idle_s)
        finally:
            await session.close()
    except Exception as exc:  # noqa: BLE001 - transport failure is evidence
        ev.error = f"{type(exc).__name__}: {exc}"
    finally:
        session.finalize()
    return ev
