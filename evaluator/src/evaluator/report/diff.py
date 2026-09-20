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
from evaluator.report.metrics import NA, candidate_metrics

# Aggregates worth comparing between two runs, with their Spanish label.
# Rates and counts use their numerator so a delta is an exact number; a
# percentile uses its own value. When either side has no data the delta is
# None (rendered `n/d`), never 0.
DELTA_KEYS: tuple[tuple[str, str], ...] = (
    ("without_errors", "casos sin errores"),
    ("pass_rate", "aciertos"),
    ("invalid", "no evaluables"),
    ("model_failures", "fallos del modelo"),
    ("first_audio_p50", "primera respuesta p50"),
    ("first_audio_p95", "primera respuesta p95"),
    ("turn_latency_p50", "latencia por turno p50"),
    ("turn_latency_p95", "latencia por turno p95"),
    ("turns_median", "turnos (mediana)"),
    ("submissions_accepted", "submissions aceptadas"),
    ("cost_total", "coste total"),
    ("duration_p50", "duracion p50"),
    ("stability", "estabilidad"),
    ("audio_caller_s", "audio del caller"),
    ("audio_agent_s", "audio del agente"),
    ("audio_ratio", "caller/agente"),
    ("interrupts_total", "barge-ins"),
)


def _delta_value(metric: dict[str, Any] | None) -> float | None:
    if not metric:
        return None
    value = metric.get("numerator")
    return value if isinstance(value, (int, float)) else None


def metric_deltas(
    cases_a: dict[tuple[str, str, int], CaseResult],
    cases_b: dict[tuple[str, str, int], CaseResult],
) -> dict[str, dict[str, Any]]:
    """Per-aggregate A/B comparison, `n/d` when either side has no data."""
    metrics_a = candidate_metrics(list(cases_a.values()))
    metrics_b = candidate_metrics(list(cases_b.values()))
    out: dict[str, dict[str, Any]] = {}
    for key, label in DELTA_KEYS:
        metric_a, metric_b = metrics_a.get(key), metrics_b.get(key)
        value_a, value_b = _delta_value(metric_a), _delta_value(metric_b)
        delta = (
            round(value_b - value_a, 2)
            if value_a is not None and value_b is not None
            else None
        )
        out[key] = {
            "label": label,
            "a": value_a,
            "b": value_b,
            "delta": delta,
            "a_text": (metric_a or {}).get("value", NA),
            "b_text": (metric_b or {}).get("value", NA),
        }
    return out


def _load_cases(run_dir: Path) -> dict[tuple[str, str, int], CaseResult]:
    cases: dict[tuple[str, str, int], CaseResult] = {}
    path = run_dir / "cases.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found - is {run_dir} a run directory?")
    from evaluator.report.side_by_side import load_cases

    for c in load_cases(run_dir):
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
    # Per-aggregate A/B comparison; empty when the run has no cases.
    metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Set when the diff pairs two *different* candidates (optionally from two
    # different runs): "did B's new configuration beat A's old one?"
    candidate_a: str | None = None
    candidate_b: str | None = None
    warnings: list[dict[str, str]] = field(default_factory=list)

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
            "candidate_a": self.candidate_a,
            "candidate_b": self.candidate_b,
            "warnings": self.warnings,
            "comparable": bool(self.diffs) and not self.warnings,
        }


def _median_latency(case: CaseResult) -> float | None:
    return statistics.median(case.turn_latencies_ms) if case.turn_latencies_ms else None


def _candidates_in(cases: dict[tuple[str, str, int], CaseResult]) -> list[str]:
    return sorted({key[0] for key in cases})


def _pick_candidate(
    cases: dict[tuple[str, str, int], CaseResult], wanted: str | None, side: str
) -> str:
    """Resolve which candidate to pair, refusing to guess between several.

    With more than one candidate and no explicit choice, pairing silently
    would compare the wrong configuration - exactly the mistake this feature
    exists to remove.
    """
    available = _candidates_in(cases)
    if wanted:
        if wanted not in available:
            raise ValueError(f"el candidato {wanted!r} no está en los casos de {side}: {available}")
        return wanted
    if len(available) == 1:
        return available[0]
    raise ValueError(f"hay varios candidatos en {side} ({available}): elegí uno con --candidate-{side.lower()}")


def _pair_by_scenario(
    cases: dict[tuple[str, str, int], CaseResult], candidate: str, label: str
) -> dict[tuple[str, str, int], CaseResult]:
    """Re-key one candidate's cases to (label, scenario, repetition).

    The label replaces the candidate, so a case from A and its counterpart in
    B land in the same slot even when the candidates have different names.
    """
    paired: dict[tuple[str, str, int], CaseResult] = {}
    for (_, scenario_id, repetition), case in cases.items():
        if case.candidate != candidate:
            continue
        paired[(label, scenario_id, repetition)] = case
    return paired


def diff_runs(
    dir_a: str | Path,
    dir_b: str | Path,
    candidate_a: str | None = None,
    candidate_b: str | None = None,
) -> RunDiff:
    """Compare two runs, optionally pairing two different candidates.

    Without candidates this is the classic "same candidate, two runs" diff.
    With them it answers "candidate B of run Y against candidate A of run X",
    keyed by scenario and repetition instead of by candidate name.
    """
    dir_a, dir_b = Path(dir_a), Path(dir_b)
    cases_a, cases_b = _load_cases(dir_a), _load_cases(dir_b)
    if candidate_a or candidate_b:
        picked_a = _pick_candidate(cases_a, candidate_a, "a")
        picked_b = _pick_candidate(cases_b, candidate_b, "b")
        label = f"{picked_a}→{picked_b}"
        cases_a = _pair_by_scenario(cases_a, picked_a, label)
        cases_b = _pair_by_scenario(cases_b, picked_b, label)
    shared = set(cases_a) & set(cases_b)
    warnings = []
    ma, mb = _load_manifest(dir_a), _load_manifest(dir_b)
    for key, code, label in (("dataset_fingerprint", "dataset_changed", "dataset"),
                              ("rules_version", "rules_changed", "reglas")):
        va, vb = ma.get(key), mb.get(key)
        if key == "dataset_fingerprint" and (not va or not vb):
            va, vb = ma.get("dataset_hash"), mb.get("dataset_hash")
        if not va or not vb:
            warnings.append({"code": "provenance_missing", "message": f"No se puede verificar que coincidan las {label}."})
        elif va != vb:
            warnings.append({"code": code, "message": f"Han cambiado las {label}; no atribuyas el delta solo al agente."})
    if ma.get("reference_now") != mb.get("reference_now"):
        warnings.append({"code": "clock_changed", "message": "Cambió el reloj de referencia; las fechas relativas no son comparables."})
    sa = {item["id"]: item.get("sha256") for item in ma.get("scenarios", [])}
    sb = {item["id"]: item.get("sha256") for item in mb.get("scenarios", [])}
    for sid in sorted({key[1] for key in shared}):
        if not sa.get(sid) or not sb.get(sid):
            warnings.append({"code": "scenario_unverified", "message": f"Escenario sin hash verificable: {sid}."})
        elif sa[sid] != sb[sid]:
            warnings.append({"code": "scenario_changed", "message": f"Cambió el contenido del escenario {sid}."})
    modes_a = {"text" if c.get("text_url") else "voice" for c in ma.get("candidates", []) if not candidate_a or c.get("name") == candidate_a}
    modes_b = {"text" if c.get("text_url") else "voice" for c in mb.get("candidates", []) if not candidate_b or c.get("name") == candidate_b}
    if modes_a and modes_b and modes_a != modes_b:
        warnings.append({"code": "mode_changed", "message": "Las ejecuciones usan modalidades distintas: texto y voz no miden lo mismo."})
    result = RunDiff(
        run_a=str(dir_a),
        run_b=str(dir_b),
        metrics=metric_deltas({k: cases_a[k] for k in shared}, {k: cases_b[k] for k in shared}),
        warnings=warnings,
        candidate_a=candidate_a,
        candidate_b=candidate_b,
    )
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
    for warning in result.warnings:
        lines.append(f"AVISO: {warning['message']}")
    if result.metrics:
        lines.append("\nmétricas:")
        for row in result.metrics.values():
            delta = row["delta"]
            delta_text = f"{delta:+g}" if delta is not None else "n/d"
            lines.append(
                f"  {row['label']:<26} A={row['a_text']}  B={row['b_text']}  delta={delta_text}"
            )
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
