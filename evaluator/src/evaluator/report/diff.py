"""Run diff: compare two experiment result directories.

Answers "what did configuration B change relative to A on the same
scenarios?" - the question the team asks after every tweak. Compares
cases keyed by (candidate, scenario_id, repetition): verdict flips,
failure-signal/category changes, latency deltas, and cost deltas when
both runs expose cost.

Reads only `cases.jsonl` (+ `manifest.json` for display), so it works on
any two runs of this evaluator, current or older.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evaluator.models import CaseResult


def _load_cases(run_dir: Path) -> dict[tuple[str, str, int], CaseResult]:
    cases: dict[tuple[str, str, int], CaseResult] = {}
    path = run_dir / "cases.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found - is {run_dir} a run directory?")
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        c = CaseResult.model_validate_json(line)
        cases[(c.candidate, c.scenario_id, c.repetition)] = c
    return cases


def _load_manifest(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "manifest.json"
    return json.loads(path.read_text()) if path.exists() else {}


@dataclass
class CaseDiff:
    key: tuple[str, str, int]
    verdict_a: str
    verdict_b: str
    signal_a: str | None
    signal_b: str | None
    categories_a: list[str] = field(default_factory=list)
    categories_b: list[str] = field(default_factory=list)
    latency_delta_ms: float | None = None
    cost_delta: float | None = None

    @property
    def kind(self) -> str:
        if self.verdict_a == self.verdict_b:
            if self.verdict_a == "fail" and (
                self.signal_a != self.signal_b or self.categories_a != self.categories_b
            ):
                return "changed_failure"
            return "unchanged"
        if self.verdict_b == "pass":
            return "newly_passing"
        if self.verdict_a == "pass":
            return "newly_failing"
        return "verdict_changed"


@dataclass
class RunDiff:
    run_a: str
    run_b: str
    only_in_a: list[tuple[str, str, int]] = field(default_factory=list)
    only_in_b: list[tuple[str, str, int]] = field(default_factory=list)
    diffs: list[CaseDiff] = field(default_factory=list)

    def by_kind(self, kind: str) -> list[CaseDiff]:
        return [d for d in self.diffs if d.kind == kind]

    def summary(self) -> dict[str, Any]:
        passes_a = sum(1 for d in self.diffs if d.verdict_a == "pass")
        passes_b = sum(1 for d in self.diffs if d.verdict_b == "pass")
        return {
            "cases_compared": len(self.diffs),
            "passes_a": passes_a,
            "passes_b": passes_b,
            "newly_passing": len(self.by_kind("newly_passing")),
            "newly_failing": len(self.by_kind("newly_failing")),
            "verdict_changed": len(self.by_kind("verdict_changed")),
            "changed_failure": len(self.by_kind("changed_failure")),
            "unchanged": len(self.by_kind("unchanged")),
            "only_in_a": len(self.only_in_a),
            "only_in_b": len(self.only_in_b),
        }


def _median_latency(case: CaseResult) -> float | None:
    return statistics.median(case.turn_latencies_ms) if case.turn_latencies_ms else None


def diff_runs(dir_a: str | Path, dir_b: str | Path) -> RunDiff:
    dir_a, dir_b = Path(dir_a), Path(dir_b)
    cases_a, cases_b = _load_cases(dir_a), _load_cases(dir_b)
    result = RunDiff(run_a=str(dir_a), run_b=str(dir_b))
    for key in sorted(set(cases_a) | set(cases_b)):
        a, b = cases_a.get(key), cases_b.get(key)
        if a is None:
            result.only_in_b.append(key)
            continue
        if b is None:
            result.only_in_a.append(key)
            continue
        la, lb = _median_latency(a), _median_latency(b)
        latency_delta = round(lb - la, 1) if la is not None and lb is not None else None
        cost_delta = (
            round(b.cost - a.cost, 6) if a.cost is not None and b.cost is not None else None
        )
        result.diffs.append(
            CaseDiff(
                key=key,
                verdict_a=a.verdict,
                verdict_b=b.verdict,
                signal_a=a.failure_signal,
                signal_b=b.failure_signal,
                categories_a=list(a.categories),
                categories_b=list(b.categories),
                latency_delta_ms=latency_delta,
                cost_delta=cost_delta,
            )
        )
    return result


def format_diff(result: RunDiff) -> str:
    """Plain-text report for the CLI."""
    s = result.summary()
    lines = [
        f"A: {result.run_a}",
        f"B: {result.run_b}",
        "",
        (
            f"comparados: {s['cases_compared']}  "
            f"(solo en A: {s['only_in_a']}, solo en B: {s['only_in_b']})"
        ),
        f"aciertos:   A={s['passes_a']}  B={s['passes_b']}",
        f"nuevos aciertos:    {s['newly_passing']}",
        f"nuevos fallos:      {s['newly_failing']}",
        f"cambio de veredicto:{s['verdict_changed']}",
        f"fallo cambiado:     {s['changed_failure']}",
        f"sin cambio:         {s['unchanged']}",
    ]
    # Two identical runs of the same agent moved 6 of 21 scenarios, in both
    # directions. Without this line the numbers above read as a verdict on
    # the change, and they are not one.
    moved = s["newly_passing"] + s["newly_failing"] + s["verdict_changed"]
    if moved:
        lines += [
            "",
            f"AVISO: {moved} caso(s) cambiaron de veredicto. El agente no es",
            "determinista: dos ejecuciones del MISMO código mueven casos en las",
            "dos direcciones. Antes de leer esto como una mejora, mira la tabla",
            "de estabilidad del informe (necesita repetitions > 1) y quédate con",
            "los escenarios que salen siempre incorrectos.",
        ]
    for kind, label in (
        ("newly_passing", "NUEVOS ACIERTOS"),
        ("newly_failing", "NUEVOS FALLOS"),
        ("verdict_changed", "CAMBIO DE VEREDICTO"),
        ("changed_failure", "FALLO CAMBIADO"),
    ):
        diffs = result.by_kind(kind)
        if not diffs:
            continue
        lines.append(f"\n{label}:")
        for d in diffs:
            cand, sid, rep = d.key
            extra = []
            if d.latency_delta_ms is not None:
                extra.append(f"lat {d.latency_delta_ms:+.0f}ms")
            if d.cost_delta is not None:
                extra.append(f"coste {d.cost_delta:+.4f}")
            tail = f"  ({', '.join(extra)})" if extra else ""
            lines.append(f"  {cand}/{sid}/r{rep}: {d.verdict_a} -> {d.verdict_b}{tail}")
            if d.signal_a != d.signal_b:
                lines.append(f"      señal: {d.signal_a} -> {d.signal_b}")
            if d.categories_a != d.categories_b:
                lines.append(f"      categorías: {d.categories_a} -> {d.categories_b}")
    return "\n".join(lines)
