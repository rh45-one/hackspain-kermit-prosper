"""Experiment runner: scenarios × candidates × repetitions.

Owns the whole local rig: starts the clinic server (read API + submission
receiver) and the test double when a candidate asks for it, plays the
harness side of each call, collects the record and scores it.

The real agent is an external system: the runner reaches it over `ws_url`
or `text_url` and never shares the scenario's oracle. `start_command` is a
convenience to boot it; env overlays (e.g. AGENT_MODEL) make candidates
distinct configurations of the same agent.
"""
from __future__ import annotations

import asyncio
import glob
import hashlib
import json
import os
import signal
import socket
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import uvicorn

from evaluator.api.redact import redact_secrets
from evaluator.clinic.dataset import Dataset
from evaluator.clinic.server import create_app as create_clinic_app
from evaluator.compare import categorize, compare, transcript_leaks
from evaluator.harness import tts as tts_mod
from evaluator.harness.audio import (
    mix_with_noise,
    pcm_to_ulaw,
    synth_noise,
    ulaw_seconds,
    ulaw_to_wav,
)
from evaluator.harness.double_agent import create_app as create_double_app
from evaluator.harness.wsclient import PlayTurn, dial, load_audio, silence
from evaluator.models import (
    CandidateConfig,
    CaseResult,
    ExperimentConfig,
    Scenario,
)
from evaluator.profiles import AgentProfile, assert_laboratory_profile
from evaluator.profiles.guard import inspect_profile
from evaluator.simulator.llm_patient import make_patient

# Voice path: how long the caller will wait, after its own `hold_ms`, for the
# agent to stop talking before speaking the next scripted line. A fixed pause
# makes every turn after the first overlap the agent's reply.
VOICE_MAX_HOLD_MS = 15000
VOICE_QUIET_MS = 800

VERB_TO_ROUTE = {
    "REGISTER": "register",
    "BOOK": "book",
    "RESCHEDULE": "reschedule",
    "CANCEL": "cancel",
    "NO_ACTION": "no-action",
    "ESCALATE": "escalate",
}


class _ServerHandle:
    def __init__(
        self, server: uvicorn.Server, thread: threading.Thread, listener: socket.socket
    ) -> None:
        self.server = server
        self.thread = thread
        self.listener = listener

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)
        self.listener.close()


def serve_in_thread(app: Any, host: str, port: int) -> _ServerHandle:
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    listener = socket.create_server(
        (host, port), family=socket.AF_INET6 if ":" in host else socket.AF_INET
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    handle = _ServerHandle(server, thread, listener)
    thread.start()
    for _ in range(100):
        if server.started:
            return handle
        if not thread.is_alive():
            break
        time.sleep(0.05)
    handle.stop()
    raise RuntimeError(f"evaluator server did not start on {host}:{port}")


def _to_submit_bodies(outcome: list[dict[str, Any]], mutate: bool = False) -> list[dict[str, Any]]:
    """Canonical accepted outcome → double's control actions."""
    out = []
    for action in outcome:
        verb = action["action"]
        fields = {k: v for k, v in action.items() if k != "action"}
        if mutate:
            # Flip exactly one field so the case must fail on purpose.
            key = "policy_id" if "policy_id" in fields else next(iter(fields))
            fields[key] = f"{fields[key]}-MUTATED"
        out.append({"route": VERB_TO_ROUTE[verb], "fields": fields})
    return out


def _scenario_turns(
    scenario: Scenario,
    scenario_path: Path,
    tts_command: str | None = None,
) -> tuple[list[PlayTurn], list[str]]:
    """Voice path: one PlayTurn per scripted turn, plus any rig defects.

    Returns `(turns, rig_errors)`. A turn asking for `tts: true` with no
    working provider is a *rig* defect, not an agent failure: it is reported
    so the case can be invalidated instead of scoring an agent that was
    played two seconds of silence and had nothing to answer.

    Noise (`turn.noise`) is mixed in here so what goes on the wire is what
    the agent hears - and what lands in the caller-side evidence file.
    """
    groups: list[PlayTurn] = []
    rig_errors: list[str] = []
    for i, turn in enumerate(scenario.turns):
        if turn.audio:
            frames = load_audio(scenario_path.parent / turn.audio)
        elif turn.tts and turn.text:
            if not tts_command:
                rig_errors.append(
                    f"turn {i}: tts: true but the experiment sets no tts_command"
                )
                frames = silence(2000)
            else:
                try:
                    frames = tts_mod.synthesize(
                        turn.text, tts_command, lang=scenario.language,
                        cache_dir=scenario_path.parent / ".tts-cache",
                    )
                except Exception as exc:  # noqa: BLE001 - missing TTS is a rig limit
                    rig_errors.append(f"turn {i}: TTS failed: {type(exc).__name__}: {exc}")
                    frames = silence(2000)
        else:
            if turn.text:
                rig_errors.append(
                    f"turn {i}: no audio and no tts: true - the agent hears silence"
                )
            frames = silence(2000)

        if turn.noise:
            if turn.noise.file:
                noise_frames = load_audio(scenario_path.parent / turn.noise.file)
            else:
                n = sum(len(f) for f in frames)
                noise_frames = [
                    pcm_to_ulaw(synth_noise(n, seed=int.from_bytes(hashlib.sha256(scenario.id.encode()).digest()[:4]),
                                            kind=turn.noise.synth or "brown"))
                ]
            frames = mix_with_noise(frames, noise_frames, snr_db=turn.noise.snr_db)

        groups.append(
            PlayTurn(
                frames,
                interrupt_on_agent_audio=turn.interrupt_on_agent_audio,
                hold_ms=turn.hold_ms,
                quiet_ms=VOICE_QUIET_MS,
                max_hold_ms=VOICE_MAX_HOLD_MS,
            )
        )
    return (groups or [PlayTurn(silence(8000))]), rig_errors


@dataclass
class TextCall:
    """What driving one call over the text adapter produced."""

    transcript: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # count against the rig
    latencies: list[float] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # visible, never scored


async def _run_text_call(
    scenario: Scenario,
    text_url: str,
    call_id: str,
    timeout_s: float = 120.0,
) -> TextCall:
    """Drive a call over the text adapter; returns (agent_turns, errors, latencies).

    The contract is documented in README, "Adaptador de texto `/turns`":
    the first POST for a call_id opens the call, each POST carries one
    caller utterance and returns one agent utterance, and a final
    `event: "hangup"` closes it so the agent flushes its submissions while
    the receiver window is still open. The hangup is best effort - an agent
    that does not implement it is not penalised for it.

    The adapter gets its own client: one `/turns` POST is a whole agent turn
    (several LLM round-trips and their tool calls), which has nothing to do
    with the millisecond timeout the local clinic deserves. Sharing one
    client invalidated cases for a rig limit - the agent was answering.

    `scenario.limits.max_call_seconds` bounds the whole conversation, like
    the 3-minute cap on the real platform, and is recorded the way the voice
    path records it: a truncated call is still scored on what it submitted.

    When the scenario defines a caller, the rules-based patient answers;
    otherwise the scripted turn texts are replayed verbatim.
    """
    out = TextCall()
    transcript, errors, latencies = out.transcript, out.errors, out.latencies
    ended = False
    call_started = time.monotonic()
    http = httpx.AsyncClient(timeout=timeout_s)

    def out_of_time() -> bool:
        if time.monotonic() - call_started < scenario.limits.max_call_seconds:
            return False
        if not any("max_call_s" in e for e in errors):
            errors.append(
                f"caller-side max_call_s reached ({scenario.limits.max_call_seconds:.0f}s)"
            )
        return True

    async def send(text: str) -> str | None:
        """Returns the agent's utterance, "" if it said nothing, None on error."""
        nonlocal ended
        started = time.monotonic()
        try:
            resp = await http.post(
                f"{text_url}/turns", json={"call_id": call_id, "text": text}
            )
        except httpx.HTTPError as exc:
            errors.append(f"text adapter: {type(exc).__name__}: {exc}")
            return None
        latencies.append(round((time.monotonic() - started) * 1000, 1))
        if resp.status_code != 200:
            errors.append(f"text adapter HTTP {resp.status_code}")
            return None
        try:
            body = resp.json()
        except ValueError:
            errors.append("text adapter: reply is not JSON")
            return None
        if not isinstance(body, dict):
            errors.append("text adapter: reply is not a JSON object")
            return None
        reply = body.get("reply")
        if body.get("ended"):
            ended = True  # the agent hung up; stop talking to a closed call
        if reply:
            transcript.append(str(reply))
        # An empty reply is "I said nothing", not a broken call: the patient
        # asks again and gives up on its own after `behavior.max_repeats`.
        return str(reply) if reply else ""

    async def hangup() -> None:
        """Best-effort end-of-call signal; never scored against the agent.

        Best effort is not the same as invisible. The outcome goes to `notes`,
        which no verdict reads: an agent whose model rejects `text: null`
        answers 422 here, keeps every point it earned, and can still see in
        the report that the evaluator tried to close the call and could not.
        """
        try:
            resp = await http.post(
                f"{text_url}/turns", json={"call_id": call_id, "text": None, "event": "hangup"}
            )
        except httpx.HTTPError as exc:
            out.notes.append(f"hangup no entregado: {type(exc).__name__}")
            return
        if resp.status_code != 200:
            out.notes.append(
                f"hangup rechazado con HTTP {resp.status_code}: el agente no "
                "implementa el cierre opcional (no penaliza)"
            )

    patient = (
        make_patient(scenario.caller, scenario.limits, language=scenario.language)
        if scenario.caller.opening
        else None
    )
    try:
        if patient is not None:
            reply = await send(patient.opening() or "")
            while reply is not None and not ended and not out_of_time():
                nxt = patient.respond(reply)
                if nxt is None:
                    break
                reply = await send(nxt)
        else:
            for turn in scenario.turns[: scenario.limits.max_turns]:
                if ended or out_of_time():
                    break
                if turn.text:
                    await send(turn.text)
        await hangup()
    finally:
        await http.aclose()
    return out


async def _drain_record(
    http: httpx.AsyncClient, call_id: str, drain_s: float
) -> httpx.Response:
    """Read the call record, giving a late flush time to land.

    The receiver keeps the window open 30 s after the call closes, so an
    agent that submits on hangup can still be in flight when the case ends.
    Polling stops at the first recorded action - a silent candidate only
    ever pays the full `drain_s`.
    """
    resp = await http.get(f"/eval/calls/{call_id}/record")
    deadline = time.monotonic() + max(0.0, drain_s)
    while time.monotonic() < deadline:
        if resp.status_code == 200 and resp.json().get("actions"):
            break
        await asyncio.sleep(0.1)
        resp = await http.get(f"/eval/calls/{call_id}/record")
    return resp


async def _gather_cases(calls: list[Any]) -> list[CaseResult]:
    """Run concurrent calls; a crashed task becomes an invalid case, not a
    dead experiment (harness failure ≠ agent failure)."""
    outcomes = await asyncio.gather(*calls, return_exceptions=True)
    results: list[CaseResult] = []
    for outcome in outcomes:
        if isinstance(outcome, CaseResult):
            results.append(outcome)
        else:
            results.append(
                CaseResult(
                    case_id="switchboard/task-error",
                    call_id="",
                    scenario_id="",
                    problem_id="switchboard",
                    candidate="",
                    repetition=0,
                    verdict="invalid_evaluation",
                    errors=[f"{type(outcome).__name__}: {outcome}"],
                )
            )
    return results


async def _fetch_usage(
    usage_url: str | None, call_id: str, http: httpx.AsyncClient
) -> tuple[float | None, dict[str, Any]]:
    """Ask the candidate for this call's cost; unknown stays None (§13)."""
    if not usage_url:
        return None, {}
    try:
        resp = await http.get(f"{usage_url.rstrip('/')}/calls/{call_id}", timeout=5)
        if resp.status_code != 200:
            return None, {}
        data = resp.json()
        return data.get("cost"), data.get("usage", {})
    except httpx.HTTPError:
        return None, {}


async def _run_case(
    scenario: Scenario,
    scenario_path: Path,
    candidate: CandidateConfig,
    repetition: int,
    clinic_url: str,
    submit_key: str,
    double_port: int | None,
    case_id: str,
    evidence_dir: Path | None = None,
    tts_command: str | None = None,
    submit_drain_s: float = 2.0,
) -> CaseResult:
    call_id = uuid.uuid4().hex
    http = httpx.AsyncClient(base_url=clinic_url, timeout=10)
    open_resp = await http.post("/eval/calls", json={"call_id": call_id})
    transcript: list[str] = []
    errors: list[str] = []
    latencies: list[float] = []
    first_audio_ms: float | None = None
    interrupts: list[dict[str, Any]] = []
    notes: list[str] = []
    audio: dict[str, str] = {}
    ev = None  # set on the WS paths (double + external)
    frames_sent: int | None = None
    frames_received: int | None = None
    caller_audio_s: float | None = None
    agent_audio_s: float | None = None
    rig_errors: list[str] = []
    started_at = datetime.now(UTC).isoformat()
    started = time.monotonic()
    harness_failed = open_resp.status_code != 200

    try:
        if harness_failed:
            errors.append(f"clinic refused call open: HTTP {open_resp.status_code}")
        else:
            if candidate.kind == "double":
                # Tell the double what this call should submit - keyed by
                # call_id so concurrent sockets never cross-contaminate.
                mode = candidate.mode
                if mode == "silent":
                    actions = None
                else:
                    outcome = scenario.accepted_outcomes[0]
                    actions = _to_submit_bodies(outcome, mutate=mode == "mutate")
                async with httpx.AsyncClient(
                    base_url=f"http://127.0.0.1:{double_port}", timeout=10
                ) as double_http:
                    await double_http.post(
                        "/control", json={"call_id": call_id, "actions": actions}
                    )
            if candidate.text_url:
                text_call = await _run_text_call(
                    scenario,
                    candidate.text_url,
                    call_id,
                    timeout_s=candidate.text_timeout_seconds,
                )
                transcript = text_call.transcript
                errors = text_call.errors
                latencies = text_call.latencies
                notes = text_call.notes
            elif candidate.kind == "double":
                ev = await dial(
                    f"ws://127.0.0.1:{double_port}/ws",
                    call_id,
                    [PlayTurn(silence(400))],  # the double ignores audio content
                    from_number=scenario.from_number,
                    after_send_idle_s=0.5,
                    max_call_s=30.0,
                )
                if ev.error:
                    errors.append(ev.error)
            else:
                turns, rig_errors = _scenario_turns(
                    scenario, scenario_path, tts_command=tts_command
                )
                errors.extend(rig_errors)
                ev = await dial(
                    candidate.ws_url or "",
                    call_id,
                    turns,
                    from_number=scenario.from_number,
                    after_send_idle_s=8.0,
                    max_call_s=scenario.limits.max_call_seconds,
                )
                if ev.error:
                    errors.append(ev.error)
            if ev is not None:
                # Measured for every websocket path, doubles included: how fast
                # the agent answered is a metric of the rig's runs, not a
                # privilege of candidates that speak with a real voice. Those
                # runs are the only ones that work without provider keys, and
                # they were reporting n/d for latency.
                latencies = [x for x in ev.turn_latencies_ms if x is not None]
                first_audio_ms = ev.first_audio_ms
                interrupts = ev.interrupts
                # Audio volume and frame counters: the evidence trail alone
                # could not answer "how many seconds did each side send?"
                # without opening a WAV, so the harness measures it here.
                # µ-law 8 kHz mono is one byte per sample.
                frames_sent = ev.frames_sent
                frames_received = ev.frames_received
                caller_audio_s = ulaw_seconds(len(ev.caller_audio))
                agent_audio_s = ulaw_seconds(len(ev.agent_audio))
    finally:
        await http.post(f"/eval/calls/{call_id}/close")
        record_resp = await _drain_record(http, call_id, submit_drain_s)
        cost, usage = await _fetch_usage(candidate.usage_url, call_id, http)
        await http.aclose()

    # Wire evidence: whatever went over the socket in each direction,
    # saved once per case (plan §20 - a failure should be auditable).
    if evidence_dir is not None and ev is not None:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        safe = case_id.replace("/", "_")
        if ev.caller_audio:
            p = evidence_dir / f"{safe}.caller.wav"
            p.write_bytes(ulaw_to_wav(ev.caller_audio))
            audio["caller"] = str(p.relative_to(evidence_dir.parent))
        if ev.agent_audio:
            p = evidence_dir / f"{safe}.agent.wav"
            p.write_bytes(ulaw_to_wav(ev.agent_audio))
            audio["agent"] = str(p.relative_to(evidence_dir.parent))

    record = record_resp.json() if record_resp.status_code == 200 else {}
    submitted = record.get("actions", [])
    attempts = record.get("attempts", [])

    oracle = scenario.oracle
    cmp = compare(
        submitted,
        scenario.accepted_outcomes,
        forbidden_actions=oracle.forbidden_actions,
        require_nonempty_submission=oracle.require_nonempty_submission,
    )

    leaks: list[str] = []
    checks_not_run: list[str] = []
    if oracle.leak_check:
        if transcript:
            leaks = transcript_leaks(
                transcript, oracle.leak_check.national_id, oracle.leak_check.phone
            )
        else:
            # No transcript, no privacy check. The voice path has no STT, so
            # this is never silently reported as a clean privacy result.
            checks_not_run.append("leak_check")

    signal = cmp.failure_signal
    if leaks:
        signal = "transcript_leak"

    # Harness defects invalidate the case - they are not agent failures.
    transport_error = next(
        (e for e in errors if "max_call_s" not in e and e not in rig_errors), None
    )
    if harness_failed or rig_errors or (transport_error and not submitted):
        verdict = "invalid_evaluation"
    else:
        verdict = "pass" if (cmp.passed and not leaks) else "fail"

    categories = (
        categorize(cmp, leaks, transport_error, attempts) if verdict != "pass" else []
    )

    return CaseResult(
        case_id=case_id,
        call_id=call_id,
        scenario_id=scenario.id,
        problem_id=scenario.problem_id,
        candidate=candidate.name,
        candidate_version=candidate.runtime_identity.get("version") or candidate.version,
        started_at=started_at,
        ended_at=datetime.now(UTC).isoformat(),
        repetition=repetition,
        verdict=verdict,
        failure_signal=signal,  # type: ignore[arg-type]
        categories=categories,
        matched_outcome=cmp.matched_outcome,
        field_diffs=cmp.field_diffs,
        extra_actions=cmp.extra_actions,
        missing_actions=cmp.missing_actions,
        submitted=submitted,
        submit_attempts=attempts,
        transcript=transcript,
        turn_latencies_ms=latencies,
        first_audio_ms=first_audio_ms,
        cost=cost,
        usage=usage,
        audio=audio,
        frames_sent=frames_sent,
        frames_received=frames_received,
        caller_audio_s=caller_audio_s,
        agent_audio_s=agent_audio_s,
        interrupts=interrupts,
        checks_not_run=checks_not_run,
        notes=notes,
        duration_s=round(time.monotonic() - started, 2),
        errors=errors,
    )


def _endpoint(url: str) -> tuple[str, int] | None:
    """host/port of a ws:// or http:// candidate URL, for a readiness probe."""
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if not parts.hostname:
        return None
    default = 443 if parts.scheme in ("https", "wss") else 80
    return parts.hostname, parts.port or default


def wait_until_listening(candidate: CandidateConfig, timeout_s: float = 60.0) -> str | None:
    """Block until a started candidate accepts TCP, or say why it did not.

    `start_command` launches a process; without this the first case dials a
    socket nobody is listening on yet and is thrown away. A TCP connect is
    protocol-agnostic: it works for the WS port and the text adapter alike,
    and does not assume the agent exposes any particular health route.
    """
    target = _endpoint(candidate.text_url or candidate.ws_url or "")
    if target is None:
        return None
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(target, timeout=1):
                return None
        except OSError:
            time.sleep(0.25)
    return f"candidate {candidate.name!r} never listened on {target[0]}:{target[1]}"


def _dataset_profile(path: Path) -> dict[str, Any]:
    """Size of the fixture actually used, for the report's fixture warning.

    A green run on a six-patient miniature is not a point on the official
    board; the report says so with these numbers next to it (task §4).
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    counts = {
        key: len(raw.get(key) or [])
        for key in (
            "patients",
            "providers",
            "locations",
            "plans",
            "specialties",
            "appointment_types",
            "appointments",
        )
    }
    return {"name": raw.get("meta", {}).get("name"),
            "note": raw.get("meta", {}).get("note", ""),
            "counts": counts}


def _load_scenarios(config: ExperimentConfig, config_dir: Path) -> list[tuple[Scenario, Path]]:
    pairs: list[tuple[Scenario, Path]] = []
    for pattern in config.scenarios:
        for path in sorted(glob.glob(str(config_dir / pattern), recursive=True)):
            pairs.append((Scenario.load(path), Path(path)))
    return pairs


def validate_scenario(scenario: Scenario, dataset: Dataset) -> list[str]:
    """Check a scenario resolves in its fixture (plan §8 loader rule).

    An incoherent scenario is an evaluator bug, not an agent failure - so
    these are reported, never silently scored.
    """
    problems: list[str] = []
    if scenario.clinic_fixture and scenario.clinic_fixture != dataset.meta.get("name"):
        problems.append(
            f"clinic_fixture {scenario.clinic_fixture!r} != dataset {dataset.meta.get('name')!r}"
        )
    for i, outcome in enumerate(scenario.accepted_outcomes):
        for action in outcome:
            verb = action["action"]
            if verb == "BOOK":
                if action.get("patient_id") not in dataset.patients_by_id:
                    problems.append(f"outcome {i}: unknown patient_id {action.get('patient_id')}")
                if action.get("provider_id") not in dataset.providers_by_id:
                    problems.append(f"outcome {i}: unknown provider_id {action.get('provider_id')}")
                if action.get("location_id") not in dataset.locations_by_id:
                    problems.append(f"outcome {i}: unknown location_id {action.get('location_id')}")
                if action.get("appointment_type_id") not in dataset.types_by_id:
                    problems.append(
                        f"outcome {i}: unknown type {action.get('appointment_type_id')}"
                    )
                if action.get("policy_id") not in dataset.plans_by_id:
                    problems.append(f"outcome {i}: unknown policy_id {action.get('policy_id')}")
                slot = action.get("slot")
                if slot:
                    try:
                        day = datetime.fromisoformat(str(slot)).date()
                        if not (
                            date.fromisoformat(dataset.calendar["starts"])
                            <= day
                            <= date.fromisoformat(dataset.calendar["ends"])
                        ):
                            problems.append(f"outcome {i}: slot {slot} outside calendar")
                    except ValueError:
                        problems.append(f"outcome {i}: unparseable slot {slot!r}")
            elif verb in ("CANCEL", "RESCHEDULE"):
                appt = action.get("appointment_id")
                if appt and appt not in {a["appointment_id"] for a in dataset.appointments}:
                    problems.append(f"outcome {i}: unknown appointment_id {appt}")
            elif verb == "REGISTER":
                from evaluator.normalize import national_id_check_ok

                nid = action.get("national_id")
                if nid and not national_id_check_ok(str(nid)):
                    problems.append(f"outcome {i}: bad national_id check letter {nid!r}")
    if not scenario.caller.opening and not scenario.turns:
        problems.append("no caller.opening and no turns - nothing to say")
    return problems


def case_plan(
    config: ExperimentConfig, scenarios: list[tuple[Scenario, Path]]
) -> list[tuple[int, Scenario, Path, CandidateConfig]]:
    """The cases to run, with the candidate varying fastest.

    Interleaved on purpose. Running each candidate's block to completion lets a
    time-varying backend (provider latency, warm caches, a deploy in the
    middle) favour whichever candidate happened to go last, which is exactly
    the difference an A/B is trying to measure. Repetitions stay slowest so
    every repetition still sees every candidate.
    """
    return [
        (rep, scenario, path, cand)
        for rep in range(config.repetitions)
        for scenario, path in scenarios
        for cand in config.candidates
    ]


def _not_ready_case(
    candidate: CandidateConfig,
    scenario: Scenario,
    repetition: int,
    case_id: str,
    detail: str,
) -> CaseResult:
    """A candidate that never listened is a rig failure, not a model result."""
    return CaseResult(
        case_id=case_id,
        call_id=f"not-ready-{case_id}",
        scenario_id=scenario.id,
        problem_id=scenario.problem_id,
        candidate=candidate.name,
        repetition=repetition,
        verdict="invalid_evaluation",
        categories=["candidate_not_ready"],
        errors=[detail],
    )


def verify_clinic(url: str, dataset: Dataset, key: str) -> None:
    from evaluator.profiles import AgentProfile, assert_laboratory_profile

    assert_laboratory_profile(AgentProfile(id="clinic", laboratory={"clinic_url": url}))
    try:
        response = httpx.get(f"{url.rstrip('/')}/eval/identity", headers={"X-Api-Key": key},
                             timeout=3, trust_env=False)
        response.raise_for_status()
        identity = response.json()
        if identity.get("service") != "evaluator-clinic" or identity.get("dataset_fingerprint") != dataset.fingerprint:
            raise ValueError("fixture")
    except (httpx.HTTPError, ValueError, AttributeError):
        raise ValueError("No se pudo verificar la clínica local y su dataset. Arranca o actualiza la clínica del laboratorio; no se reutilizará un proceso desconocido.") from None


def run_experiment(
    config_path: str,
    out_root: str | None = None,
    cancel_requested: Callable[[], bool] | None = None,
    on_progress: Callable[[Path, int, int], None] | None = None,
) -> Path:
    """Run one experiment end to end; returns the results directory."""
    config_path_obj = Path(config_path).resolve()
    config = ExperimentConfig.load(str(config_path_obj))
    config_dir = config_path_obj.parent
    dataset = Dataset.load(str(config_dir / config.clinic_dataset))
    dataset_hash = hashlib.sha256(
        (config_dir / config.clinic_dataset).read_bytes()
    ).hexdigest()[:12]

    scenarios = _load_scenarios(config, config_dir)
    fixture_problems = {
        s.id: p for s, _ in scenarios if (p := validate_scenario(s, dataset))
    }
    if fixture_problems:
        lines = [f"  {sid}: {probs}" for sid, probs in fixture_problems.items()]
        raise ValueError("scenarios do not resolve in the fixture:\n" + "\n".join(lines))

    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    out_dir = Path(out_root or config_dir / "results") / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = out_dir / "evidence"
    results: list[CaseResult] = []
    planned = len(case_plan(config, scenarios))
    if config.switchboard:
        planned += min(config.switchboard.concurrency, len(scenarios)) * len(config.candidates)
    safe_config = redact_secrets(config.model_dump(exclude={"submit_key": True, "candidates": {"__all__": {"start_command", "start_cwd"}}}))
    for declared, candidate in zip(safe_config["candidates"], config.candidates, strict=True):
        declared["settings"] = {key: candidate.env[key] for key in (
            "VOICE_ENGINE", "AGENT_MODEL", "GEMINI_LIVE_MODEL", "TURNS_MODEL",
            "DEEPGRAM_STT_MODEL", "ELEVENLABS_TTS_MODEL"
        ) if key in candidate.env}
    revision = {}
    try:
        repo = Path(__file__).resolve().parents[4]
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo, text=True, timeout=3).strip())
        revision = {"commit": commit, "dirty": dirty}
    except (OSError, subprocess.SubprocessError):
        pass
    manifest = {
        "run_id": run_id, "experiment": config.name, "rules_version": config.rules_version,
        "dataset_hash": dataset_hash, "dataset_fingerprint": dataset.fingerprint,
        "dataset": config.clinic_dataset, "dataset_profile": _dataset_profile(config_dir / config.clinic_dataset),
        "reference_now": config.reference_now, "repetitions": config.repetitions, "budget": config.budget,
        "started_at": datetime.now(UTC).isoformat(), "ended_at": None,
        "candidates": [], "startup": {}, "revision": revision,
        "config_hash": hashlib.sha256(json.dumps({key: value for key, value in safe_config.items() if key != "name"}, sort_keys=True).encode()).hexdigest(),
        "configuration": safe_config,
        "scenarios": [{"id": s.id, "problem_id": s.problem_id, "version": s.version, "split": s.split,
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for s, path in scenarios],
        "note": "resultado local - no es el veredicto oficial del reto",
        "status": "running", "completed_cases": 0, "planned_cases": planned,
    }
    (out_dir / "cases.jsonl").touch()

    def save_manifest():
        manifest["candidates"] = [redact_secrets(c.model_dump(exclude={"start_command"})) for c in config.candidates]
        path = out_dir / "manifest.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        temporary.replace(path)

    def persist_case(result):
        result.run_id = run_id
        with (out_dir / "cases.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(result.model_dump_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        results.append(result)
        manifest["completed_cases"] = len(results)
        save_manifest()
        if on_progress:
            on_progress(out_dir, len(results), planned)

    save_manifest()
    if on_progress:
        on_progress(out_dir, 0, planned)
    clinic = None
    clinic_url = config.clinic_url or f"http://127.0.0.1:{config.clinic_port}"

    doubles: list[_ServerHandle] = []
    procs: list[subprocess.Popen] = []
    # A started candidate that never listens is a rig failure, not a model
    # result: its cases are marked invalid instead of being scored, and the
    # other alternatives in the same run keep their evidence.
    startup: dict[str, str | None] = {}
    try:
        if config.clinic_mode == "existing":
            verify_clinic(clinic_url, dataset, config.submit_key)
        else:
            clinic = serve_in_thread(create_clinic_app(dataset, api_key=config.submit_key), "127.0.0.1", config.clinic_port)
            clinic_url = f"http://127.0.0.1:{clinic.listener.getsockname()[1]}"
        for cand in config.candidates:
            profile = AgentProfile(id=cand.name, engine=cand.engine or "external",
                endpoints={"ws_url": cand.ws_url, "text_url": cand.text_url, "usage_url": cand.usage_url},
                laboratory={"clinic_url": clinic_url})
            if cand.kind != "double":
                assert_laboratory_profile(profile, probe_ports=bool(cand.start_command))
            if cand.kind == "double":
                doubles.append(
                    serve_in_thread(
                        create_double_app(clinic_url, api_key=config.submit_key),
                        "127.0.0.1",
                        cand.port or 18770,
                    )
                )
            elif cand.start_command:
                env = {**os.environ, **cand.env}
                procs.append(
                    subprocess.Popen(cand.start_command, shell=True, env=env, cwd=cand.start_cwd or config_dir, start_new_session=True)
                )
                # The process is not the service: wait for the socket, or the
                # cases are scored against an agent that was still booting.
                startup[cand.name] = wait_until_listening(cand)
            if cand.kind != "double" and not startup.get(cand.name):
                identity = asyncio.run(inspect_profile(profile))
                cand.runtime_identity = identity
                if not identity["ready"]:
                    startup[cand.name] = identity["reason"]

        not_ready = {name for name, problem in startup.items() if problem}

        manifest["startup"] = {name: {"listening": problem is None, "detail": problem or "listening"} for name, problem in startup.items()}
        save_manifest()
        cancelled = False
        for rep, scenario, path, cand in case_plan(config, scenarios):
            # Cancellation is checked between calls. A current call gets to
            # close its clinic window and flush its evidence before the rig
            # tears down its own clinic/double processes in ``finally``.
            if cancel_requested and cancel_requested():
                cancelled = True
                break
            case_id = f"{cand.name}/{scenario.id}/r{rep}"
            if cand.name in not_ready:
                persist_case(
                    _not_ready_case(cand, scenario, rep, case_id, str(startup[cand.name]))
                )
                continue
            result = asyncio.run(
                _run_case(
                    scenario,
                    path,
                    cand,
                    rep,
                    clinic_url,
                    config.submit_key,
                    cand.port,
                    case_id,
                    evidence_dir=evidence_dir,
                    tts_command=config.tts_command,
                    submit_drain_s=config.submit_drain_s,
                )
            )
            persist_case(result)

        # Switchboard diagnostic (problem 2): N simultaneous calls, one
        # scenario each, to expose state contamination between sessions.
        if config.switchboard is not None and not cancelled:
            n = config.switchboard.concurrency
            for cand in config.candidates:
                if cand.name in not_ready:
                    continue
                pool = scenarios[:n] or scenarios
                calls = [
                    _run_case(
                        scenario,
                        path,
                        cand,
                        0,
                        clinic_url,
                        config.submit_key,
                        cand.port,
                        f"{cand.name}/switchboard-{i}-{scenario.id}",
                        evidence_dir=evidence_dir,
                        tts_command=config.tts_command,
                        submit_drain_s=config.submit_drain_s,
                    )
                    for i, (scenario, path) in enumerate(pool)
                ]
                for result in asyncio.run(_gather_cases(calls)):
                    persist_case(result)

        manifest.update(status="cancelled" if cancelled else "completed", ended_at=datetime.now(UTC).isoformat())
        save_manifest()
        # Same aggregates the console and `cli metrics` show, in machine form:
        # an A/B decision should not require re-parsing cases.jsonl.
        from evaluator.report.metrics import write_metrics

        write_metrics(out_dir, results)
    except BaseException as exc:
        manifest.update(status="failed", ended_at=datetime.now(UTC).isoformat(), error=type(exc).__name__)
        save_manifest()
        raise
    finally:
        for p in procs:
            if p.poll() is None:
                if os.name == "posix":
                    os.killpg(p.pid, signal.SIGTERM)
                else:
                    p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        os.killpg(p.pid, signal.SIGKILL)
                    else:
                        p.kill()
                    p.wait()
        for d in doubles:
            d.stop()
        if clinic is not None:
            clinic.stop()

    from evaluator.report.render import render_report

    render_report(out_dir)
    return out_dir
