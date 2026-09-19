"""Manual tester: talk to a live agent from the terminal.

The automated runner plays a scenario nobody wrote by hand; this is for a
person. You type, the caller side is synthesized locally and the agent's audio
comes back as text when an STT provider is configured. The same `CallSession`
the experiments use carries the wire, so what you hear is what a run would
measure - the tester is a window into the rig, not a second implementation of
it.

Evidence is never thrown away: every agent utterance is saved as WAV under the
results directory (gitignored), the call's submissions are read back from the
local clinic, and with `--scenario` the record is scored with the same
`compare()` an experiment uses.
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from evaluator.compare import compare
from evaluator.harness.agent_audit import (
    AgentAudit,
    agent_audit_dir_for,
    diagnose_caller_audio,
    read_agent_audit,
)
from evaluator.harness.audio import ulaw_to_wav
from evaluator.harness.stt import NullTranscriber, Transcriber, transcriber_from_env
from evaluator.harness.tts import provider_available, synthesize
from evaluator.harness.wsclient import CallSession, silence
from evaluator.models import Scenario

DEFAULT_SAVE_ROOT = Path("evaluator/experiments/results")
SUBMISSION_WAIT_S = 12.0


@dataclass
class ChatOptions:
    ws_url: str = "ws://127.0.0.1:17860/ws"
    clinic_url: str = "http://127.0.0.1:18090"
    api_key: str = "pk-local-eval"
    call_id: str = field(default_factory=lambda: f"tester-{uuid.uuid4().hex[:8]}")
    from_number: str | None = None
    tts: str = "espeak-ng"
    lang: str = "es"
    stt_provider: str | None = None
    scenario: str | None = None
    save_dir: Path | None = None
    agent_audit_dir: Path | None = None
    reply_idle_ms: float = 900.0
    reply_max_ms: float = 20000.0
    reply_start_ms: float = 6000.0
    submission_wait_s: float = SUBMISSION_WAIT_S
    turn_tail_ms: float = 600.0
    greeting_wait_ms: float = 20000.0
    greet_first: bool = True


def _out(message: str = "") -> None:
    print(message, flush=True)


async def open_call_window(options: ChatOptions) -> str:
    async with httpx.AsyncClient(base_url=options.clinic_url, timeout=10) as http:
        response = await http.post("/eval/calls", json={"call_id": options.call_id})
        response.raise_for_status()
    return options.call_id


async def close_call_window(options: ChatOptions) -> None:
    async with httpx.AsyncClient(base_url=options.clinic_url, timeout=10) as http:
        await http.post(f"/eval/calls/{options.call_id}/close")


def _audit_for(options: ChatOptions) -> AgentAudit:
    """Read the agent's own trail when a path was given; never guess silently."""
    if not options.agent_audit_dir:
        return AgentAudit(available=False)
    directory = agent_audit_dir_for(options.call_id, Path(options.agent_audit_dir))
    if directory is None:
        return AgentAudit(available=False)
    return read_agent_audit(options.call_id, directory)


async def wait_for_actions(options: ChatOptions, timeout_s: float | None = None) -> dict:
    """Submissions land after the socket closes; wait bounded, then report."""
    deadline = time.monotonic() + (options.submission_wait_s if timeout_s is None else timeout_s)
    record: dict = {"actions": [], "attempts": []}
    async with httpx.AsyncClient(base_url=options.clinic_url, timeout=10) as http:
        while True:
            response = await http.get(f"/eval/calls/{options.call_id}/record")
            if response.status_code == 200:
                record = response.json()
                if record.get("actions"):
                    return record
            if time.monotonic() >= deadline:
                return record
            await asyncio.sleep(0.25)


async def _speak_agent(
    session: CallSession,
    transcriber: Transcriber,
    options: ChatOptions,
    save_dir: Path,
    turn: int,
    label: str,
    first_wait_ms: float,
) -> bytes:
    """Collect the agent's utterance, keep the WAV and print what was said."""
    audio = await session.drain_audio(
        idle_ms=options.reply_idle_ms,
        max_ms=options.reply_max_ms,
        first_wait_ms=first_wait_ms,
    )
    if not audio:
        _out(f"agente ({label}): [sin audio en {first_wait_ms / 1000:.0f}s]")
        return audio
    wav_path = save_dir / f"{turn:02d}-agent-{label}.wav"
    wav_path.write_bytes(ulaw_to_wav(audio))
    seconds = len(audio) / 8000  # µ-law: 1 byte per sample at 8 kHz
    if isinstance(transcriber, NullTranscriber):
        _out(f"agente ({label}): [audio-only {seconds:.1f}s → {wav_path}] {transcriber.reason}")
    else:
        try:
            text = await transcriber.transcribe(audio)
        except Exception as exc:  # noqa: BLE001 - a failed transcript is not a failed call
            _out(f"agente ({label}): [STT falló: {exc}] audio en {wav_path}")
            return audio
        _out(f"agente ({label}): {text or '[silencio]'}")
    return audio


async def run_chat(options: ChatOptions) -> int:
    """One manual session against a live agent. Returns a process exit code."""
    save_dir = (
        Path(options.save_dir)
        if options.save_dir
        else DEFAULT_SAVE_ROOT / f"chat-{options.call_id}"
    )
    save_dir.mkdir(parents=True, exist_ok=True)

    if not provider_available(options.tts):
        _out(f"TTS '{options.tts}' no está instalado: el caller no podrá hablar.")
        return 2

    env = dict(os.environ)
    if options.stt_provider:
        env["EVALUATOR_STT_PROVIDER"] = options.stt_provider
    transcriber = transcriber_from_env(env)

    await open_call_window(options)
    session = CallSession(
        options.ws_url, options.call_id, from_number=options.from_number
    )
    _out(f"llamada  {options.call_id}")
    _out(f"agente   {options.ws_url}")
    _out(f"clínica  {options.clinic_url}")
    _out(f"voz      {options.tts} ({options.lang})   STT: {transcriber.name}")
    _out(f"evidencia {save_dir}")
    _out(
        "Escribí y Enter para hablar. ':salir' o Ctrl-D para terminar. "
        f"El saludo se espera hasta {options.greeting_wait_ms / 1000:.0f}s; "
        "no hables encima de él."
    )
    _out()
    turn = 0
    try:
        await session.open()
        if options.greet_first:
            await _speak_agent(
                session,
                transcriber,
                options,
                save_dir,
                turn,
                "saludo",
                options.greeting_wait_ms,
            )
            turn += 1
        while True:
            try:
                line = await asyncio.to_thread(input, "tú> ")
            except EOFError:
                _out()
                break
            line = line.strip()
            if line in (":salir", ":quit", ":exit"):
                break
            if not line:
                continue
            try:
                frames = synthesize(line, options.tts, options.lang)
            except Exception as exc:  # noqa: BLE001 - rig limitation, keep the session
                _out(f"[TTS falló: {exc}]")
                continue
            # A real caller pauses at the end of a sentence, and turn detection
            # reads that pause: without the tail the agent may never close the turn.
            if options.turn_tail_ms > 0:
                frames = frames + silence(int(options.turn_tail_ms))
            await session.send_frames(frames)
            await _speak_agent(
                session,
                transcriber,
                options,
                save_dir,
                turn,
                "respuesta",
                options.reply_start_ms,
            )
            turn += 1
    except Exception as exc:  # noqa: BLE001 - report the transport failure, do not hide it
        _out(f"[conexión interrumpida: {type(exc).__name__}: {exc}]")
    finally:
        evidence = await session.close()
        await transcriber.aclose()

    await close_call_window(options)
    record = await wait_for_actions(options)

    _out()
    _out(f"frames  caller={evidence.frames_sent} agente={evidence.frames_received}")
    caller_seconds = len(evidence.caller_audio) / 8000
    _out(f"voz del caller enviada: {caller_seconds:.1f}s")
    if evidence.turn_latencies_ms:
        answered = [ms for ms in evidence.turn_latencies_ms if ms is not None]
        if answered:
            _out(f"latencia primer audio: {answered} ms")
    if evidence.error:
        _out(f"error de transporte: {evidence.error}")

    audit = _audit_for(options)
    if audit.available:
        _out(
            f"auditoría del agente: caller {audit.caller_chars} car., "
            f"agente {len(audit.assistant_text.strip())} car., "
            f"acciones {audit.actions_queued}"
        )
    diagnosis = diagnose_caller_audio(caller_seconds, audit)
    if diagnosis:
        _out()
        _out(f"DIAGNÓSTICO ({diagnosis.kind}): {diagnosis.message}")

    actions = record.get("actions", [])
    _out(f"submissions aceptadas: {len(actions)}")
    for action in actions:
        _out(f"  - {action}")
    for attempt in record.get("attempts", []):
        if attempt.get("status") != 200:
            _out(f"  ! intento {attempt.get('route')} → {attempt.get('status')} {attempt.get('detail')}")

    if options.scenario:
        scenario = Scenario.load(options.scenario)
        result = compare(actions, scenario.accepted_outcomes)
        _out()
        attribution = ""
        if diagnosis and diagnosis.blocks_model_scoring:
            attribution = "  ← NO atribuible al modelo: falla la entrada del agente"
        _out(
            f"veredicto {scenario.id}: "
            f"{'PASA' if result.passed else 'FALLA'} ({result.failure_signal or 'ok'})"
            f"{attribution}"
        )
        for diff in result.field_diffs:
            _out(f"  - {diff}")
    return 0
