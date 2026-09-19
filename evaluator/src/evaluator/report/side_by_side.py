"""Side-by-side: the same case under every candidate of one run.

An experiment already runs every candidate on every scenario, so the question
the team actually asks - "which alternative did better on THIS call?" - is a
rendering of `cases.jsonl`, not another run. `diff_runs` answers a different
question: what changed for one candidate between two runs.

Rows are (scenario, repetition); columns are candidates. The interesting rows
are the disagreements: where two alternatives produced different verdicts on
the same call, with the same caller and the same fixture.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evaluator.models import CaseResult

MARKS = {"pass": "PASA", "fail": "FALLA", "invalid_evaluation": "inv"}
CELL_WIDTH = 20


def load_cases(run_dir: Path | str) -> list[CaseResult]:
    path = Path(run_dir) / "cases.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found - is {run_dir} a run directory?")
    return [
        CaseResult.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def median_latency(case: CaseResult) -> float | None:
    return statistics.median(case.turn_latencies_ms) if case.turn_latencies_ms else None


@dataclass
class SideBySideRow:
    """One case, seen through every candidate that ran it."""

    scenario_id: str
    problem_id: str
    repetition: int
    cells: dict[str, CaseResult] = field(default_factory=dict)

    @property
    def verdicts(self) -> set[str]:
        return {case.verdict for case in self.cells.values()}

    @property
    def disagrees(self) -> bool:
        return len(self.verdicts) > 1

    def cell_text(self, candidate: str) -> str:
        case = self.cells.get(candidate)
        if case is None:
            return "—"
        text = MARKS.get(case.verdict, case.verdict)
        if case.verdict == "fail" and case.failure_signal:
            text += f":{case.failure_signal}"
        latency = median_latency(case)
        if latency is not None:
            text += f" {latency:.0f}ms"
        return text


@dataclass
class SideBySide:
    run: str
    candidates: list[str] = field(default_factory=list)
    rows: list[SideBySideRow] = field(default_factory=list)

    def disagreements(self) -> list[SideBySideRow]:
        return [row for row in self.rows if row.disagrees]

    def summary(self) -> dict[str, Any]:
        per_candidate: dict[str, dict[str, int]] = {
            name: {"pass": 0, "fail": 0, "invalid_evaluation": 0, "with_errors": 0}
            for name in self.candidates
        }
        for row in self.rows:
            for name, case in row.cells.items():
                bucket = per_candidate.setdefault(
                    name, {"pass": 0, "fail": 0, "invalid_evaluation": 0, "with_errors": 0}
                )
                bucket[case.verdict] = bucket.get(case.verdict, 0) + 1
                if case.errors:
                    bucket["with_errors"] += 1
        return {
            "candidates": self.candidates,
            "rows": len(self.rows),
            "disagreements": len(self.disagreements()),
            "per_candidate": per_candidate,
        }


def side_by_side(run_dir: Path | str) -> SideBySide:
    cases = load_cases(run_dir)
    candidates = sorted({case.candidate for case in cases})
    grouped: dict[tuple[str, int], dict[str, CaseResult]] = {}
    problem_of: dict[str, str] = {}
    for case in cases:
        grouped.setdefault((case.scenario_id, case.repetition), {})[case.candidate] = case
        problem_of[case.scenario_id] = case.problem_id
    rows = [
        SideBySideRow(
            scenario_id=scenario_id, problem_id=problem_of[scenario_id], repetition=rep, cells=cells
        )
        for (scenario_id, rep), cells in sorted(grouped.items())
    ]
    return SideBySide(run=str(run_dir), candidates=candidates, rows=rows)


def format_side_by_side(result: SideBySide) -> str:
    """Plain-text table for the CLI: one row per case, one column per candidate."""
    if not result.rows:
        return f"run: {result.run}\n(sin casos)"
    # Wide enough for the longest cell, so a long signal never glues to the
    # next column. The details below still spell out every disagreement.
    width = max(
        [CELL_WIDTH]
        + [len(row.cell_text(name)) + 2 for row in result.rows for name in result.candidates]
    )
    header = "escenario".ljust(18) + "rep".ljust(5)
    header += "".join(name.ljust(width) for name in result.candidates)
    lines = [f"run: {result.run}", "", header.rstrip()]
    for row in result.rows:
        line = row.scenario_id.ljust(18) + str(row.repetition).ljust(5)
        line += "".join(row.cell_text(name).ljust(width) for name in result.candidates)
        lines.append(line.rstrip() + ("  *" if row.disagrees else ""))
    disagreements = result.disagreements()
    lines.append("")
    lines.append(f"filas: {len(result.rows)}   desacuerdos: {len(disagreements)}  (marcados con *)")
    for row in disagreements:
        detail = "  ".join(f"{name}={row.cell_text(name)}" for name in result.candidates)
        lines.append(f"  {row.scenario_id} r{row.repetition}: {detail}")
    counts = result.summary()["per_candidate"]
    lines.append("")
    for name in result.candidates:
        bucket = counts.get(name, {})
        lines.append(
            f"{name.ljust(width)}"
            f"pasa {bucket.get('pass', 0)}  "
            f"falla {bucket.get('fail', 0)}  "
            f"inválidas {bucket.get('invalid_evaluation', 0)}  "
            f"con errores {bucket.get('with_errors', 0)}"
        )
    return "\n".join(lines)


def side_by_side_json(result: SideBySide) -> str:
    return json.dumps(result.summary(), indent=2)
