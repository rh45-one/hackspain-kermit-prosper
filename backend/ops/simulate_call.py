"""Local simulator: dial our own WS the way the harness does, without the harness.

Usage: uv run python ops/simulate_call.py --audio tests/fixtures/hello.wav

Speaks Twilio Media Streams exactly like the Prosper harness: `connected`,
`start` (callSid/streamSid/customParameters), `media` (20 ms frames of 8 kHz
µ-law, base64), then `stop` before closing. Records the agent's reply audio
to /tmp/agent_reply.raw (8 kHz µ-law; decode with audioop.ulaw2lin if needed).

The fixture wav may be any mono 16-bit PCM wav; it is converted to 8 kHz
µ-law with the stdlib audioop (ratecv + lin2ulaw), so no external tooling is
required.
"""
from __future__ import annotations

import argparse
import asyncio
import audioop
import base64
import json
import time
import wave
from pathlib import Path

import websockets

OUT_PATH = Path("/tmp/agent_reply.raw")
TARGET_RATE = 8000


def wav_to_ulaw(path: Path) -> bytes:
    """Read a 16-bit mono PCM wav and return 8 kHz µ-law bytes."""
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise SystemExit("fixture must be a mono 16-bit wav")
        rate = w.getframerate()
        frames = w.readframes(w.getnframes())
    if rate != TARGET_RATE:
        frames, _ = audioop.ratecv(frames, 2, 1, rate, TARGET_RATE, None)
    return audioop.lin2ulaw(frames, 2)


def ulaw_chunks(payload: bytes, ms_per_chunk: int = 20) -> list[bytes]:
    """Slice µ-law bytes into 20 ms wire frames (160 bytes each at 8 kHz)."""
    size = TARGET_RATE * ms_per_chunk // 1000  # 1 byte per µ-law sample
    return [payload[i : i + size] for i in range(0, len(payload), size)]


async def run(ws_url: str, audio: Path, hold_seconds: float) -> None:
    call_id = f"sim-{int(time.time() * 1000)}"
    OUT_PATH.write_bytes(b"")
    async with websockets.connect(ws_url, max_size=None) as ws:
        await ws.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        await ws.send(
            json.dumps(
                {
                    "event": "start",
                    "start": {
                        "callSid": call_id,
                        "streamSid": "SM-sim",
                        "customParameters": {"call_id": call_id, "from_number": "+34600000000"},
                    },
                    "sequenceNumber": "1",
                }
            )
        )
        print(f"→ start (call_id={call_id})")

        async def send_audio() -> None:
            for i, chunk in enumerate(ulaw_chunks(wav_to_ulaw(audio))):
                await ws.send(
                    json.dumps(
                        {
                            "event": "media",
                            "streamSid": "SM-sim",
                            "media": {"payload": base64.b64encode(chunk).decode()},
                            "sequenceNumber": str(i + 2),
                            "chunk": str(i + 1),
                        }
                    )
                )
                await asyncio.sleep(0.02)

        sender = asyncio.create_task(send_audio())
        reply = bytearray()
        try:
            # Hold the socket open like the harness does while the agent talks.
            await asyncio.wait_for(sender, timeout=60)
            await asyncio.sleep(hold_seconds)
        except (TimeoutError, websockets.ConnectionClosed):
            pass

        await ws.send(json.dumps({"event": "stop", "streamSid": "SM-sim", "stop": {"callSid": call_id}}))
        print("→ stop")

        try:
            async for message in ws:
                data = json.loads(message)
                if data.get("event") == "media":
                    reply.extend(base64.b64decode(data["media"]["payload"]))
                elif data.get("event") in ("mark", "clear", "stop"):
                    print("←", data.get("event"))
        except websockets.ConnectionClosed:
            print("← socket closed")
    OUT_PATH.write_bytes(bytes(reply))
    print(f"agent audio: {OUT_PATH} (8 kHz µ-law)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate a Prosper harness call against our own WS")
    parser.add_argument("--url", default="ws://localhost:7860/ws")
    parser.add_argument("--audio", required=True, type=Path, help="16-bit mono PCM wav fixture")
    parser.add_argument("--hold-seconds", type=float, default=10.0, help="how long to listen after audio ends")
    args = parser.parse_args()
    asyncio.run(run(args.url, args.audio, args.hold_seconds))
