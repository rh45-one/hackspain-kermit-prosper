"""Latency evidence must survive every path of the runner, doubles included.

The doubles are the only candidates that run without provider keys, so they are
the runs a developer actually looks at. They measured their own latency and the
runner dropped it on the floor: `first_audio_ms` and `turn_latencies_ms` were
copied only in the external-candidate branch, so every smoke run reported
`n/d` on the console for the two headline latency numbers.

This runs one real case through `run_experiment` and asserts the numbers reach
the case, and from there the metric.
"""
from __future__ import annotations

import json
from pathlib import Path

from evaluator.report.metrics import candidate_metrics

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "data" / "clinic_dataset.json"
SCENARIO = ROOT / "scenarios" / "simple_booking" / "sb-001.yaml"


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_a_double_run_records_the_latency_it_measured(tmp_path):
    from evaluator.runner.experiment import run_experiment

    config = tmp_path / "latency.yaml"
    config.write_text(
        "\n".join(
            [
                "name: latency-wiring",
                f"clinic_dataset: {DATASET}",
                f"clinic_port: {_free_port()}",
                "repetitions: 1",
                "candidates:",
                "  - name: double-correct",
                "    kind: double",
                f"    port: {_free_port()}",
                "    mode: correct",
                "scenarios:",
                f"  - {SCENARIO}",
            ]
        ),
        encoding="utf-8",
    )

    out = run_experiment(str(config), str(tmp_path / "results"))
    cases = [
        json.loads(line)
        for line in (out / "cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(cases) == 1
    case = cases[0]

    assert case["errors"] == [], case["errors"]
    assert case["first_audio_ms"] is not None, "el doble saluda: su latencia es medible"
    assert case["turn_latencies_ms"], "el turno del caller fue respondido"
    assert case["duration_s"] > 0

    from evaluator.models import CaseResult

    metrics = candidate_metrics([CaseResult.model_validate(case)])
    assert metrics["first_audio_p50"]["value"] != "n/d"
    assert metrics["turn_latency_p50"]["value"] != "n/d"
