"""Full-duplex microphone bridge using the harness's Twilio wire contract."""
from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from evaluator.harness.agent_audit import agent_audit_dir_for
from evaluator.harness.audio import ulaw_to_wav
from evaluator.harness.wsclient import FRAME_BYTES, CallSession
from evaluator.observer.backend_calls import load_backend_call
from evaluator.profiles import ProfileCatalog, assert_laboratory_profile
from evaluator.profiles.guard import inspect_profile
from evaluator.tester import ChatOptions, close_call_window, open_call_window, wait_for_actions

# The browser paces 20 ms mu-law packets, so the frame budget and the wall-clock
# budget describe the same three minutes. Both are named so a test can shrink
# the window instead of waiting for it.
MAX_CALL_SECONDS = 180.0
MAX_FRAMES = int(MAX_CALL_SECONDS / 0.02)
TIME_LIMIT_ERROR = "Límite de duración de la llamada alcanzado"
PROTOCOL_ERROR = "Se esperaba un paquete de audio de 20 ms"
TRANSPORT_ERROR = (
    "No se pudo completar la llamada. Revisa que el agente y la clínica del perfil "
    "estén disponibles."
)


def create_live_router(catalog: ProfileCatalog, root: Path) -> APIRouter:
    router = APIRouter()

    @router.websocket("/api/live/{profile_id}")
    async def live(socket: WebSocket, profile_id: str):
        origin = socket.headers.get("origin")
        if origin and urlparse(origin).netloc != socket.headers.get("host"):
            await socket.close(code=1008)
            return
        await socket.accept()
        session = None
        options = None
        opened = False
        tasks = []
        started = datetime.now(UTC)
        call_id = f"mic-{uuid.uuid4().hex}"
        error = None
        timeline = []
        identity = {}

        def read_audit():
            if not options or not options.agent_audit_dir:
                return None
            try:
                directory = agent_audit_dir_for(call_id, options.agent_audit_dir)
                path = directory / f"{call_id}.jsonl" if directory else None
                return load_backend_call(path) if path and not path.is_symlink() else None
            except OSError:
                return None

        try:
            profile = catalog.get(profile_id)
            assert_laboratory_profile(profile)
            if not profile.endpoints.ws_url:
                raise ValueError("Este perfil no declara un WebSocket de voz")
            identity = await inspect_profile(profile)
            if not identity["ready"]:
                error = identity["reason"]
                return
            options = ChatOptions.from_profile(profile, call_id=call_id)
            await open_call_window(options)
            opened = True

            async def forward(message):
                if message.get("event") == "clear":
                    timeline.append({"event": "playback_cleared", "timestamp": datetime.now(UTC).isoformat(), "data": {}})
                await socket.send_json(message)

            session = CallSession(options.ws_url, call_id, event_sink=forward)
            await session.open()
            await socket.send_json({"event": "ready", "call_id": call_id, "profile_id": profile_id, "identity": identity})

            async def telemetry():
                while True:
                    await asyncio.sleep(1)
                    audit = await asyncio.to_thread(read_audit)
                    await socket.send_json({"event": "telemetry",
                        "frames_sent": session.evidence.frames_sent,
                        "frames_received": session.evidence.frames_received,
                        "transcript_available": audit is not None,
                        "caller_text": audit.caller_text if audit else "",
                        "agent_text": audit.assistant_text if audit else ""})

            async def receive():
                nonlocal error
                while True:
                    message = await socket.receive()
                    if message["type"] == "websocket.disconnect":
                        return
                    if message.get("bytes") is not None:
                        # The client owns these limits: report them as such instead
                        # of blaming the agent for a browser-side protocol error.
                        if session.evidence.frames_sent >= MAX_FRAMES:
                            error = TIME_LIMIT_ERROR
                            return
                        if len(message["bytes"]) != FRAME_BYTES:
                            error = PROTOCOL_ERROR
                            return
                        await session.send_live_frame(message["bytes"])
                    elif message.get("text") == "stop":
                        return
                    else:
                        error = PROTOCOL_ERROR
                        return

            tasks = [asyncio.create_task(receive()), asyncio.create_task(session.wait_remote()),
                     asyncio.create_task(telemetry())]
            done, _ = await asyncio.wait(
                tasks, timeout=MAX_CALL_SECONDS, return_when=asyncio.FIRST_COMPLETED
            )
            if not done:
                error = TIME_LIMIT_ERROR
            for task in done:
                task.result()
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001 - transport errors must not expose credentials
            error = TRANSPORT_ERROR
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if session is not None:
                with contextlib.suppress(Exception):
                    await session.close()
            if opened and options is not None:
                record = {}
                with contextlib.suppress(Exception):
                    await close_call_window(options)
                    record = await wait_for_actions(options, timeout_s=3)
                ended = datetime.now(UTC)
                audio_files = {}
                if session is not None:
                    for stream, audio in (("caller", session.evidence.caller_audio), ("agent", session.evidence.agent_audio)):
                        if audio:
                            path = root / "_live-audio" / call_id / f"{stream}.wav"
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_bytes(ulaw_to_wav(audio))
                            audio_files[stream] = str(path.relative_to(root))
                turns = []
                if options.agent_audit_dir:
                    with contextlib.suppress(OSError):
                        audit = await asyncio.to_thread(read_audit)
                        if audit:
                            turns = audit.transcript_events
                            timeline.extend(audit.timeline)
                payload = {"call_id": call_id, "profile_id": profile_id, "started_at": started.isoformat(),
                           "ended_at": ended.isoformat(), "duration_s": (ended - started).total_seconds(),
                           "turns": turns, "timeline": timeline, "audio_files": audio_files,
                           "submissions": record.get("actions", []),
                           "submit_attempts": record.get("attempts", []), "transport_error": error,
                           "identity": identity, "candidate_version": identity.get("version"),
                           "frames_sent": session.evidence.frames_sent if session else 0,
                           "frames_received": session.evidence.frames_received if session else 0,
                           "first_audio_ms": session.evidence.first_audio_ms if session else None,
                           "evidence": {"audio": "present" if audio_files else "absent",
                                        "transcript": "present" if turns else "absent",
                                        "cost": "unknown", "outcome": "unknown"}}
                archive = root / "_manual-calls"
                archive.mkdir(parents=True, exist_ok=True)
                (archive / f"{call_id}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with contextlib.suppress(Exception):
                await socket.send_json({"event": "finished", "call_id": call_id, "error": error})
                await socket.close()

    return router
