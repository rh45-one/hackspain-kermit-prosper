"""Experiment runner: scenarios × candidates × repetitions.

Owns the whole local rig: starts the clinic server (read API + submission
receiver) and the test double when a candidate asks for it, plays the
harness side of each call, collects the record and scores it.

The real agent is an external system: the runner reaches it over `ws_url`
and never shares the scenario's accepted outcomes. `start_command` is a
convenience to boot it; env overlays (e.g. AGENT_MODEL) make candidates
distinct configurations of the same agent.
"""
from __future__ import annotations

import asyncio
import glob
import hashlib
import json
import os
import subprocess
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import uvicorn

from evaluator.clinic.dataset import Dataset
from evaluator.clinic.server import create_app as create_clinic_app
from evaluator.compare import compare, transcript_leaks
from evaluator.harness.double_agent import create_app as create_double_app
from evaluator.harness.wsclient import dial, load_audio, silence
from evaluator.models import (
    CandidateConfig,
    CaseResult,
    ExperimentConfig,
    Scenario,
)

VERB_TO_ROUTE = {
    "REGISTER": "register",
    "BOOK": "book",
    "RESCHEDULE": "reschedule",
    "CANCEL": "cancel",
    "NO_ACTION": "no-action",
    "ESCALATE": "escalate",
}


class _ServerHandle:
    def __init__(self, server: uvicorn.Server, thread: threading.Thread) -> None:
        self.server = server
        self.thread = thread

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


def serve_in_thread(app: Any, host: str, port: int) -> _ServerHandle:
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return _ServerHandle(server, thread)


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


def _scenario_frames(scenario: Scenario, scenario_path: Path) -> list[bytes]:
    frames: list[bytes] = []
    for turn in scenario.turns:
        if turn.audio:
            frames.extend(load_audio(scenario_path.parent / turn.audio))
        else:
            frames.extend(silence(2000))
        frames.extend(silence(turn.hold_ms))
    return frames or silence(8000)


async def _run_case(
    scenario: Scenario,
    scenario_path: Path,
    candidate: CandidateConfig,
    repetition: int,
    clinic_url: str,
    submit_key: str,
    double_port: int | None,
    case_id: str,
) -> CaseResult:
    call_id = uuid.uuid4().hex
    http = httpx.AsyncClient(base_url=clinic_url, timeout=10)
    await http.post("/eval/calls", json={"call_id": call_id})
    transcript: list[str] = []
    error: str | None = None
    started = time.monotonic()

    try:
        if candidate.kind == "double":
            # Tell the double what this call should submit.
            mode = candidate.mode
            if mode == "silent":
                actions = None
            else:
                outcome = scenario.accepted_outcomes[0]
                actions = _to_submit_bodies(outcome, mutate=mode == "mutate")
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{double_port}", timeout=10
            ) as double_http:
                await double_http.post("/control", json={"actions": actions})
            ev = await dial(
                f"ws://127.0.0.1:{double_port}/ws",
                call_id,
                silence(400),  # the double ignores audio content
                from_number=scenario.from_number,
                after_send_idle_s=0.5,
                max_call_s=30.0,
            )
            error = ev.error
        elif candidate.text_url:
            # Text adapter: POST {text_url}/turns {call_id, text} → {reply}.
            for turn in scenario.turns:
                if not turn.text:
                    continue
                resp = await http.post(
                    f"{candidate.text_url}/turns",
                    json={"call_id": call_id, "text": turn.text},
                )
                if resp.status_code == 200:
                    reply = resp.json().get("reply")
                    if reply:
                        transcript.append(reply)
        else:
            frames = _scenario_frames(scenario, scenario_path)
            ev = await dial(
                candidate.ws_url or "",
                call_id,
                frames,
                from_number=scenario.from_number,
                after_send_idle_s=8.0,
            )
            error = ev.error
    finally:
        await http.post(f"/eval/calls/{call_id}/close")
        record_resp = await http.get(f"/eval/calls/{call_id}/record")
        await http.aclose()

    submitted = record_resp.json().get("actions", []) if record_resp.status_code == 200 else []
    cmp = compare(submitted, scenario.accepted_outcomes)

    leaks: list[str] = []
    if scenario.leak_check and transcript:
        leaks = transcript_leaks(
            transcript, scenario.leak_check.national_id, scenario.leak_check.phone
        )

    signal = cmp.failure_signal
    if leaks:
        signal = "transcript_leak"

    return CaseResult(
        case_id=case_id,
        call_id=call_id,
        scenario_id=scenario.scenario_id,
        problem_id=scenario.problem_id,
        candidate=candidate.name,
        repetition=repetition,
        passed=cmp.passed and not leaks,
        failure_signal=signal,  # type: ignore[arg-type]
        matched_outcome=cmp.matched_outcome,
        field_diffs=cmp.field_diffs,
        extra_actions=cmp.extra_actions,
        missing_actions=cmp.missing_actions,
        submitted=submitted,
        transcript=transcript,
        duration_s=round(time.monotonic() - started, 2),
        errors=[error] if error else [],
    )


def _load_scenarios(config: ExperimentConfig, config_dir: Path) -> list[tuple[Scenario, Path]]:
    pairs: list[tuple[Scenario, Path]] = []
    for pattern in config.scenarios:
        for path in sorted(glob.glob(str(config_dir / pattern), recursive=True)):
            pairs.append((Scenario.load(path), Path(path)))
    return pairs


def run_experiment(config_path: str, out_root: str | None = None) -> Path:
    """Run one experiment end to end; returns the results directory."""
    config_path_obj = Path(config_path).resolve()
    config = ExperimentConfig.load(str(config_path_obj))
    config_dir = config_path_obj.parent
    dataset = Dataset.load(str(config_dir / config.clinic_dataset))
    dataset_hash = hashlib.sha256(
        (config_dir / config.clinic_dataset).read_bytes()
    ).hexdigest()[:12]

    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    out_dir = Path(out_root or config_dir / "results") / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

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
                        cand.port or 7870,
                    )
                )
            elif cand.start_command:
                env = {**os.environ, **cand.env}
                procs.append(
                    subprocess.Popen(cand.start_command, shell=True, env=env, cwd=config_dir)
                )

        scenarios = _load_scenarios(config, config_dir)
        results: list[CaseResult] = []
        for cand in config.candidates:
            for rep in range(config.repetitions):
                for scenario, path in scenarios:
                    case_id = f"{cand.name}/{scenario.scenario_id}/r{rep}"
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
                        )
                    )
                    results.append(result)

        manifest = {
            "run_id": run_id,
            "experiment": config.name,
            "rules_version": config.rules_version,
            "dataset_hash": dataset_hash,
            "dataset": config.clinic_dataset,
            "reference_now": config.reference_now,
            "repetitions": config.repetitions,
            "started_at": datetime.now(UTC).isoformat(),
            "candidates": [c.model_dump(exclude={"start_command"}) for c in config.candidates],
            "scenarios": [
                {"scenario_id": s.scenario_id, "problem_id": s.problem_id, "version": s.version}
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
