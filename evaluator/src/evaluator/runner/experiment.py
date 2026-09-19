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
import socket
import subprocess
import threading
import time
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import uvicorn

from evaluator.clinic.dataset import Dataset
from evaluator.clinic.server import create_app as create_clinic_app
from evaluator.compare import categorize, compare, transcript_leaks
from evaluator.harness import tts as tts_mod
from evaluator.harness.audio import mix_with_noise, pcm_to_ulaw, synth_noise, ulaw_to_wav
from evaluator.harness.double_agent import create_app as create_double_app
from evaluator.harness.wsclient import PlayTurn, dial, load_audio, silence
from evaluator.models import (
    CandidateConfig,
    CaseResult,
    ExperimentConfig,
    Scenario,
)
from evaluator.runner.readiness import Readiness, wait_for_candidate
from evaluator.simulator.llm_patient import make_patient

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
) -> list[PlayTurn]:
    """Voice path: one PlayTurn per scripted turn (audio, TTS, or silence).

    Noise (`turn.noise`) is mixed in here so what goes on the wire is what
    the agent hears - and what lands in the caller-side evidence file.
    """
    groups: list[PlayTurn] = []
    for turn in scenario.turns:
        if turn.audio:
            frames = load_audio(scenario_path.parent / turn.audio)
        elif turn.tts and turn.text and tts_command:
            try:
                frames = tts_mod.synthesize(
                    turn.text, tts_command, lang=scenario.language,
                    cache_dir=scenario_path.parent / ".tts-cache",
                )
            except Exception:  # noqa: BLE001 - missing TTS is a rig limit
                frames = silence(2000)
        else:
            frames = silence(2000)

        if turn.noise:
            if turn.noise.file:
                noise_frames = load_audio(scenario_path.parent / turn.noise.file)
            else:
                n = sum(len(f) for f in frames)
                noise_frames = [
                    pcm_to_ulaw(synth_noise(n, seed=hash(scenario.id) & 0xFFFF,
                                            kind=turn.noise.synth or "brown"))
                ]
            frames = mix_with_noise(frames, noise_frames, snr_db=turn.noise.snr_db)

        frames.extend(silence(turn.hold_ms))
        groups.append(
            PlayTurn(frames, interrupt_on_agent_audio=turn.interrupt_on_agent_audio)
        )
    return groups or [PlayTurn(silence(8000))]


async def _run_text_call(
    scenario: Scenario,
    text_url: str,
    call_id: str,
    http: httpx.AsyncClient,
) -> tuple[list[str], list[str]]:
    """Drive a call over the text adapter; returns (agent_turns, errors).

    When the scenario defines a caller, the rules-based patient answers;
    otherwise the scripted turn texts are replayed verbatim.
    """
    transcript: list[str] = []
    errors: list[str] = []

    async def send(text: str) -> str | None:
        try:
            resp = await http.post(f"{text_url}/turns", json={"call_id": call_id, "text": text})
        except httpx.HTTPError as exc:
            errors.append(f"text adapter: {type(exc).__name__}: {exc}")
            return None
        if resp.status_code != 200:
            errors.append(f"text adapter HTTP {resp.status_code}")
            return None
        reply = resp.json().get("reply")
        if reply:
            transcript.append(reply)
        return reply

    patient = (
        make_patient(scenario.caller, scenario.limits, language=scenario.language)
        if scenario.caller.opening
        else None
    )
    if patient is not None:
        reply = await send(patient.opening() or "")
        while reply is not None:
            nxt = patient.respond(reply)
            if nxt is None:
                break
            reply = await send(nxt)
        return transcript, errors

    for turn in scenario.turns:
        if turn.text:
            await send(turn.text)
    return transcript, errors


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
) -> CaseResult:
    call_id = uuid.uuid4().hex
    http = httpx.AsyncClient(base_url=clinic_url, timeout=10)
    open_resp = await http.post("/eval/calls", json={"call_id": call_id})
    transcript: list[str] = []
    errors: list[str] = []
    latencies: list[float] = []
    first_audio_ms: float | None = None
    interrupts: list[dict[str, Any]] = []
    audio: dict[str, str] = {}
    ev = None  # set on the WS paths (double + external)
    started = time.monotonic()
    harness_failed = open_resp.status_code != 200

    try:
        if harness_failed:
            errors.append(f"clinic refused call open: HTTP {open_resp.status_code}")
        elif candidate.kind == "double":
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
        elif candidate.text_url:
            transcript, errors = await _run_text_call(scenario, candidate.text_url, call_id, http)
        else:
            turns = _scenario_turns(scenario, scenario_path, tts_command=tts_command)
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
            latencies = [x for x in ev.turn_latencies_ms if x is not None]
            first_audio_ms = ev.first_audio_ms
            interrupts = ev.interrupts
    finally:
        await http.post(f"/eval/calls/{call_id}/close")
        record_resp = await http.get(f"/eval/calls/{call_id}/record")
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
    if oracle.leak_check and transcript:
        leaks = transcript_leaks(
            transcript, oracle.leak_check.national_id, oracle.leak_check.phone
        )

    signal = cmp.failure_signal
    if leaks:
        signal = "transcript_leak"

    # Harness defects invalidate the case - they are not agent failures.
    transport_error = next((e for e in errors if "max_call_s" not in e), None)
    if harness_failed or (transport_error and not submitted):
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
        interrupts=interrupts,
        duration_s=round(time.monotonic() - started, 2),
        errors=errors,
    )


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
    readiness: Readiness,
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
        errors=[f"candidate never answered: {readiness.describe()}"],
    )


def run_experiment(config_path: str, out_root: str | None = None) -> Path:
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

    clinic = serve_in_thread(
        create_clinic_app(dataset, api_key=config.submit_key), "127.0.0.1", config.clinic_port
    )
    clinic_url = f"http://127.0.0.1:{config.clinic_port}"

    doubles: list[_ServerHandle] = []
    procs: list[subprocess.Popen] = []
    try:
        for cand in config.candidates:
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
                    subprocess.Popen(cand.start_command, shell=True, env=env, cwd=config_dir)
                )

        startup: dict[str, Readiness] = {
            cand.name: wait_for_candidate(cand)
            for cand in config.candidates
            if cand.start_command
        }
        not_ready = {name for name, readiness in startup.items() if not readiness.ready}

        results: list[CaseResult] = []
        for rep, scenario, path, cand in case_plan(config, scenarios):
            case_id = f"{cand.name}/{scenario.id}/r{rep}"
            if cand.name in not_ready:
                results.append(_not_ready_case(cand, scenario, rep, case_id, startup[cand.name]))
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
                )
            )
            results.append(result)

        # Switchboard diagnostic (problem 2): N simultaneous calls, one
        # scenario each, to expose state contamination between sessions.
        if config.switchboard is not None:
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
                    )
                    for i, (scenario, path) in enumerate(pool)
                ]
                results.extend(asyncio.run(_gather_cases(calls)))

        manifest = {
            "run_id": run_id,
            "experiment": config.name,
            "rules_version": config.rules_version,
            "dataset_hash": dataset_hash,
            "dataset": config.clinic_dataset,
            "reference_now": config.reference_now,
            "repetitions": config.repetitions,
            "budget": config.budget,
            "started_at": datetime.now(UTC).isoformat(),
            "candidates": [c.model_dump(exclude={"start_command"}) for c in config.candidates],
            "startup": {name: readiness.as_manifest() for name, readiness in startup.items()},
            "scenarios": [
                {"id": s.id, "problem_id": s.problem_id, "version": s.version, "split": s.split}
                for s, _ in scenarios
            ],
            "note": "resultado local - no es el veredicto oficial del reto",
        }
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        with open(out_dir / "cases.jsonl", "w", encoding="utf-8") as fh:
            fh.writelines(r.model_dump_json() + "\n" for r in results)
    finally:
        for p in procs:
            p.terminate()
        for d in doubles:
            d.stop()
        clinic.stop()

    from evaluator.report.render import render_report

    render_report(out_dir)
    return out_dir
