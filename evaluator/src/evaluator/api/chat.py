"""The one live surface: a chat session with a real agent.

Everything else in this API reads files a run already wrote. This opens a real
call instead - the same `CallSession`, the same clinic window and the same
submit receiver the experiments use - so a person poking at the agent from a
browser is exercising the rig, not a simulation of it.

The session is opened by **profile id**. The destination, the clinic, the key,
the scored scenario and the audit directory come from the server's declared
profile; the request body may tune timing and providers and nothing else (see
`evaluator.profiles.requests`). A browser used to be able to name a WebSocket
URL, a clinic URL, a scenario path and an audit directory; that door is closed.

What the session shows is what a run would measure: the caller's audio the rig
actually sent, the agent's audio it actually got, the latency to its first
reply, the submissions the receiver accepted, and the audit cross-check that
says whether the agent heard the caller at all. On close it reports the same
evidence availability the call schema uses: present / absent / unknown, never a
silent zero.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from evaluator.compare import compare
from evaluator.harness.agent_audit import (
    AgentAudit,
    agent_audit_dir_for,
    diagnose_caller_audio,
    read_agent_audit,
)
from evaluator.harness.audio import ulaw_to_wav
from evaluator.harness.stt import Transcriber, transcriber_from_env
from evaluator.harness.tts import provider_available, synthesize
from evaluator.harness.wsclient import CallSession, silence
from evaluator.models import EvidenceState, Scenario
from evaluator.profiles import (
    LaboratoryRefusal,
    ProfileCatalog,
    ProfileNotFound,
    assert_laboratory_profile,
    request_refusals,
)
from evaluator.tester import ChatOptions as TesterOptions
from evaluator.tester import close_call_window, open_call_window, wait_for_actions

# A push-to-talk upload is bounded: a browser that streams a stuck microphone
# must not fill memory, and 60 s is far more than any single turn.
MAX_MIC_SECONDS = 60.0
FRAME_BYTES = 160  # 20 ms of 8 kHz µ-law, the contract's frame size


def _present(value: Any) -> EvidenceState:
    """Availability of one evidence item, from what the session really has."""
    return "present" if value else "absent"


@dataclass
class ChatTurn:
    role: str  # "caller" | "agent"
    text: str
    seconds: float
    wav: str | None = None
    latency_ms: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "text": self.text,
            "seconds": round(self.seconds, 2),
            "wav": self.wav,
            "latency_ms": self.latency_ms,
        }


@dataclass
class ChatSession:
    """One open conversation: a call window, a websocket and its audio."""

    id: str
    options: TesterOptions
    directory: Path
    session: CallSession
    transcriber: Transcriber
    turns: list[ChatTurn] = field(default_factory=list)
    closed: bool = False
    started_at: str = ""
    on_close: Callable[[dict[str, Any]], None] | None = None

    async def _transcribe(self, audio: bytes) -> str:
        if not audio:
            return ""
        try:
            return await self.transcriber.transcribe(audio)
        except Exception as exc:  # noqa: BLE001 - the console must show the reason
            return f"[STT falló: {exc}]"

    async def _agent_turn(self, label: str, first_wait_ms: float) -> ChatTurn:
        audio = await self.session.drain_audio(
            idle_ms=self.options.reply_idle_ms,
            max_ms=self.options.reply_max_ms,
            first_wait_ms=first_wait_ms,
        )
        name = f"{len(self.turns):02d}-agent-{label}.wav"
        path = self.directory / name
        if audio:
            path.write_bytes(ulaw_to_wav(audio))
        turn = ChatTurn(
            role="agent",
            text=await self._transcribe(audio),
            seconds=len(audio) / 8000,  # µ-law: 1 byte per sample at 8 kHz
            wav=name if audio else None,
        )
        self.turns.append(turn)
        return turn

    async def greet(self) -> ChatTurn | None:
        if not self.options.greet_first:
            return None
        turn = await self._agent_turn("saludo", self.options.greeting_wait_ms)
        return turn if turn.wav else None

    async def _deliver(self, caller: ChatTurn, frames: list[bytes]) -> dict[str, Any]:
        """Send one caller turn and return the pair (caller, agent) turns."""
        caller_wav = f"{len(self.turns):02d}-caller.wav"
        (self.directory / caller_wav).write_bytes(ulaw_to_wav(b"".join(frames)))
        caller.wav = caller_wav
        self.turns.append(caller)
        await self.session.send_frames(frames)
        agent = await self._agent_turn("respuesta", self.options.reply_start_ms)
        latencies = [ms for ms in self.session.evidence.turn_latencies_ms if ms is not None]
        if latencies:
            agent.latency_ms = latencies[-1]
        return {"caller": caller.as_dict(), "agent": agent.as_dict()}

    async def say(self, text: str) -> dict[str, Any]:
        """One caller turn spoken by the server's TTS."""
        if self.closed:
            raise HTTPException(409, "la sesión ya está cerrada")
        frames = synthesize(text, self.options.tts, self.options.lang)
        if self.options.turn_tail_ms > 0:
            frames = frames + silence(int(self.options.turn_tail_ms))
        caller = ChatTurn(
            role="caller", text=text, seconds=len(frames) * 0.02, wav=None
        )
        return await self._deliver(caller, frames)

    async def say_audio(self, mulaw: bytes) -> dict[str, Any]:
        """One caller turn spoken by the person at the browser's microphone.

        The browser captures 8 kHz µ-law (AudioWorklet, same pattern as the
        backend's own demo page) and uploads it as bytes; nothing is decoded
        server side beyond framing, so what the agent hears is exactly what
        the microphone produced.
        """
        if self.closed:
            raise HTTPException(409, "la sesión ya está cerrada")
        if not mulaw:
            raise HTTPException(422, "no llegó audio del micrófono")
        if len(mulaw) > int(MAX_MIC_SECONDS * 8000):
            raise HTTPException(413, f"audio demasiado largo (máximo {MAX_MIC_SECONDS:.0f}s)")
        frames = [
            mulaw[offset : offset + FRAME_BYTES]
            for offset in range(0, len(mulaw), FRAME_BYTES)
        ]
        last = frames[-1]
        if len(last) < FRAME_BYTES:
            # µ-law 0xff is silence: pad the tail so the frame stays 20 ms.
            frames[-1] = last + b"\xff" * (FRAME_BYTES - len(last))
        if self.options.turn_tail_ms > 0:
            frames = frames + silence(int(self.options.turn_tail_ms))
        # Transcribe what the caller actually said, so the log shows the words
        # the agent had a chance to hear (empty when STT is off).
        text = await self._transcribe(mulaw)
        caller = ChatTurn(
            role="caller",
            text=text or "(audio del micrófono)",
            seconds=len(mulaw) / 8000,
            wav=None,
        )
        return await self._deliver(caller, frames)

    async def close(self) -> dict[str, Any]:
        if self.closed:
            raise HTTPException(409, "la sesión ya está cerrada")
        self.closed = True
        evidence = await self.session.close()
        await self.transcriber.aclose()
        await close_call_window(self.options)
        record = await wait_for_actions(self.options)
        caller_seconds = len(evidence.caller_audio) / 8000
        audit = _audit_for(self.options)
        diagnosis = diagnose_caller_audio(caller_seconds, audit)
        payload: dict[str, Any] = {
            "call_id": self.options.call_id,
            # A console session is a manual call: the same call/evidence schema
            # the runner and the observer write, with the manual origin so the
            # historical view can tell the three apart.
            "origin": "manual",
            "profile_id": self.options.profile_id,
            "started_at": self.started_at,
            "ended_at": datetime.now(UTC).isoformat(),
            "evidence": {
                "audio": _present(any(turn.wav for turn in self.turns)),
                "transcript": _present(
                    any(turn.text.strip() for turn in self.turns)
                    or (audit.available and bool(audit.caller_chars))
                ),
                # The chat path never calls a usage endpoint: unknown, not zero.
                "cost": "unknown",
                "outcome": _present(bool(self.options.scenario)),
            },
            "frames_sent": evidence.frames_sent,
            "frames_received": evidence.frames_received,
            "caller_seconds": round(caller_seconds, 2),
            "first_audio_ms": evidence.first_audio_ms,
            "transport_error": evidence.error,
            "transcript_chars": audit.caller_chars if audit.available else None,
            "submissions": record.get("actions", []),
            "turns": [turn.as_dict() for turn in self.turns],
            "rejected": [
                attempt
                for attempt in record.get("attempts", [])
                if attempt.get("status") != 200
            ],
            "diagnosis": None
            if diagnosis is None
            else {
                "kind": diagnosis.kind,
                "message": diagnosis.message,
                "blocks_model_scoring": diagnosis.blocks_model_scoring,
            },
            "scenario": None,
        }
        if self.options.scenario:
            scenario = Scenario.load(self.options.scenario)
            result = compare(record.get("actions", []), scenario.accepted_outcomes)
            payload["scenario"] = {
                "id": scenario.id,
                "passed": result.passed,
                "failure_signal": result.failure_signal,
            }
        if self.on_close:
            self.on_close(payload)
        return payload


def _audit_for(options: TesterOptions) -> AgentAudit:
    if not options.agent_audit_dir:
        return AgentAudit(available=False)
    directory = agent_audit_dir_for(options.call_id, Path(options.agent_audit_dir))
    return read_agent_audit(options.call_id, directory) if directory else AgentAudit(available=False)


class ChatSessionManager:
    """In-memory sessions, one per browser tab; audio outlives them on disk.

    Holds the profile catalog the server declared. A session is opened by
    profile id: the manager resolves the destination, the clinic, the key and
    the paths itself, so nothing a browser sends can select them.
    """

    def __init__(
        self,
        session_root: Path | str,
        catalog: ProfileCatalog | None = None,
        archive_root: Path | str | None = None,
    ) -> None:
        self.root = Path(session_root)
        self.catalog = catalog or ProfileCatalog.builtin()
        self.archive_root = Path(archive_root) if archive_root else None
        self._sessions: dict[str, ChatSession] = {}

    async def create(self, options: TesterOptions) -> ChatSession:
        if not provider_available(options.tts):
            raise HTTPException(503, f"TTS '{options.tts}' no está instalado en el servidor")
        session_id = uuid.uuid4().hex[:12]
        options.call_id = options.call_id or f"dev-{session_id}"
        directory = self.root / session_id
        directory.mkdir(parents=True, exist_ok=True)
        await open_call_window(options)
        session = CallSession(options.ws_url, options.call_id, from_number=options.from_number)
        try:
            await session.open()
        except Exception as exc:  # report it to the console verbatim
            await close_call_window(options)
            raise HTTPException(502, f"no se pudo abrir el websocket del agente: {exc}") from exc
        manager_session = ChatSession(
            id=session_id,
            options=options,
            directory=directory,
            session=session,
            transcriber=transcriber_from_env(_stt_env(options.stt_provider)),
            started_at=datetime.now(UTC).isoformat(),
            on_close=self._archive,
        )
        self._sessions[session_id] = manager_session
        return manager_session

    def _archive(self, payload: dict[str, Any]) -> None:
        """Persist a closed manual session for the same rebuildable history.

        The file remains evaluator evidence under the results root. It contains
        only what the manual endpoint already returned to its local caller.
        """
        if self.archive_root is None:
            return
        directory = self.archive_root / "_manual-calls"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{payload['call_id']}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def get(self, session_id: str) -> ChatSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise HTTPException(404, f"sesión desconocida: {session_id}")
        return session

    def audio(self, session_id: str, name: str) -> FileResponse:
        session = self.get(session_id)
        if "/" in name or "\\" in name or name.startswith("."):
            raise HTTPException(400, "nombre de audio inválido")
        path = (session.directory / name).resolve()
        if not path.is_file() or session.directory.resolve() not in path.parents:
            raise HTTPException(404, f"audio no disponible: {name}")
        return FileResponse(path, media_type="audio/wav")

    async def drop(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        if not session.closed:
            await session.close()
        shutil.rmtree(session.directory, ignore_errors=True)


def _stt_env(provider: str | None) -> dict[str, str]:
    env = dict(os.environ)
    if provider:
        env["EVALUATOR_STT_PROVIDER"] = provider
    return env


def create_chat_router(manager: ChatSessionManager) -> APIRouter:
    router = APIRouter(prefix="/api/chat")

    @router.post("")
    async def open_session(body: dict[str, Any]) -> dict[str, Any]:
        """Open a live session against a profile the *server* declared.

        The body names a `profile_id` and may tune timing and providers; it can
        never carry a destination, a path, a command or an environment. The
        profile is resolved here, checked against the laboratory guard, and only
        then turned into session options.
        """
        refusals = request_refusals(body)
        if refusals:
            raise HTTPException(400, "; ".join(refusals))
        profile_id = str(body.get("profile_id") or "").strip()
        if not profile_id:
            raise HTTPException(
                400, "falta profile_id: la sesión se pide con un perfil del catálogo del servidor"
            )
        try:
            profile = manager.catalog.get(profile_id)
        except ProfileNotFound as exc:
            raise HTTPException(404, str(exc)) from None
        try:
            # Destination guard only: a live session talks to a process that
            # must already be listening, so this path never probes port
            # occupancy (and never touches 7860).
            assert_laboratory_profile(profile)
        except LaboratoryRefusal as exc:
            raise HTTPException(400, str(exc)) from None
        options = TesterOptions.from_profile(
            profile,
            call_id=body.get("call_id"),
            from_number=body.get("from_number"),
            tts=body.get("tts"),
            lang=body.get("lang"),
            stt_provider=body.get("stt") or None,
            greet_first=body.get("greet_first"),
            reply_idle_ms=body.get("reply_idle_ms"),
            reply_max_ms=body.get("reply_max_ms"),
            reply_start_ms=body.get("reply_start_ms"),
            greeting_wait_ms=body.get("greeting_wait_ms"),
            turn_tail_ms=body.get("turn_tail_ms"),
            submission_wait_s=body.get("submission_wait_s"),
        )
        session = await manager.create(options)
        greeting = await session.greet()
        return {
            "session_id": session.id,
            "call_id": session.options.call_id,
            "profile_id": profile.id,
            "engine": profile.engine,
            "stt": session.transcriber.name,
            "greeting": greeting.as_dict() if greeting else None,
        }

    @router.post("/{session_id}/say")
    async def say(session_id: str, body: dict[str, Any]) -> dict[str, Any]:
        text = (body.get("text") or "").strip()
        if not text:
            raise HTTPException(422, "falta el texto")
        return await manager.get(session_id).say(text)

    @router.post("/{session_id}/say-audio")
    async def say_audio(session_id: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = body.get("mulaw_base64")
        if not isinstance(payload, str) or not payload:
            raise HTTPException(422, "falta mulaw_base64")
        try:
            raw = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, "mulaw_base64 no es base64 válido") from None
        return await manager.get(session_id).say_audio(raw)

    @router.post("/{session_id}/close")
    async def close(session_id: str) -> dict[str, Any]:
        return await manager.get(session_id).close()

    @router.delete("/{session_id}")
    async def drop(session_id: str) -> dict[str, str]:
        await manager.drop(session_id)
        return {"status": "dropped"}

    @router.get("/{session_id}/audio/{name}")
    def audio(session_id: str, name: str) -> FileResponse:
        return manager.audio(session_id, name)

    return router
