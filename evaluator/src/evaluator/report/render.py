"""Self-contained HTML report for a finished run.

Reads `manifest.json` + `cases.jsonl` from a results directory and writes
`report.html` next to them. Every figure is labelled "resultado local" -
the local judge is an estimator until validated against the official one
(plan §2, §20).
"""
from __future__ import annotations

import html
import json
from collections import defaultdict
from pathlib import Path

from evaluator.models import MAX_LOCAL_POINTS, PROBLEM_WEIGHTS

# Size of the real Clínica Arenal, for contrast with the local fixture
# (PROJECT_CONTEXT.md §10). The local dataset is a hand-written miniature:
# passing against it validates the agent's logic, not that the answer is the
# one the official platform expects.
REAL_CLINIC = {
    "patients": "~3.000",
    "providers": "12",
    "locations": "n/d",
    "plans": "10",
    "specialties": "n/d",
    "appointment_types": "11",
}
_COUNT_LABELS = {
    "patients": "pacientes",
    "providers": "médicos",
    "locations": "sedes",
    "plans": "planes",
    "specialties": "especialidades",
    "appointment_types": "tipos de cita",
}


def _fixture_banner(manifest: dict) -> str:
    """The loudest thing on the page: this is a local fixture, not the board.

    Printed in the report itself rather than the README because the report
    is what gets shown around, and a green cell here is not a point.
    """
    profile = manifest.get("dataset_profile") or {}
    counts = profile.get("counts") or {}
    rows = "".join(
        f"<tr><td>{_esc(_COUNT_LABELS.get(k, k))}</td><td>{_esc(v)}</td>"
        f"<td>{_esc(REAL_CLINIC.get(k, 'n/d'))}</td></tr>"
        for k, v in counts.items()
    )
    table = (
        "<table><tr><th>elemento</th><th>fixture local</th><th>clínica real</th></tr>"
        f"{rows}</table>"
        if rows
        else ""
    )
    note = profile.get("note") or ""
    return f"""<div class="banner">
<b>Esto no es el veredicto oficial.</b> Los casos corren contra un fixture local
en miniatura (<code>{_esc(manifest.get('dataset', '?'))}</code>, <code>{_esc(profile.get('name') or manifest.get('dataset_hash', '?'))}</code>),
inventado para este evaluador. Pasar aquí valida la <b>lógica</b> del agente
(prompt, herramientas, agenda, envío), <b>no</b> que la respuesta coincida con
los datos reales de la clínica. Un verde en esta página no es un punto en el
tablero de Prosper.
{table}
{f'<p class="meta">meta.note del dataset: {_esc(note)}</p>' if note else ''}
</div>"""


def _esc(x: object) -> str:
    return html.escape(str(x))


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _local_points(cases: list) -> tuple[float, float]:
    """puntos_locales = Σ peso × fracción correcta del problema (plan §13).

    Invalid evaluations are excluded from a problem's denominator - they
    are rig failures, not agent failures. Returns (points, covered_max).
    """
    by_problem: dict[str, list] = defaultdict(list)
    for c in cases:
        by_problem[c["problem_id"]].append(c)
    points = 0.0
    covered_max = 0.0
    for problem, group in by_problem.items():
        weight = PROBLEM_WEIGHTS.get(problem, 0)
        valid = [c for c in group if c["verdict"] != "invalid_evaluation"]
        if not valid:
            continue
        covered_max += weight
        points += weight * sum(1 for c in valid if c["verdict"] == "pass") / len(valid)
    return round(points, 2), covered_max


def render_report(run_dir: str | Path) -> Path:
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    cases = [
        json.loads(line)
        for line in (run_dir / "cases.jsonl").read_text().splitlines()
        if line.strip()
    ]

    by_candidate: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for c in cases:
        by_candidate[c["candidate"]][c["problem_id"]].append(c)

    problems = sorted({c["problem_id"] for c in cases})
    candidates = [c["name"] for c in manifest.get("candidates", [])] or sorted(by_candidate)

    # --- summary table (plan §20): per candidate ---------------------------
    summary_rows = []
    for cand in candidates:
        group = [c for c in cases if c["candidate"] == cand]
        valid = [c for c in group if c["verdict"] != "invalid_evaluation"]
        invalid = len(group) - len(valid)
        passed = sum(1 for c in valid if c["verdict"] == "pass")
        points, covered_max = _local_points(group)
        lats = [x for c in group for x in c.get("turn_latencies_ms", [])]
        p50 = _percentile(lats, 0.5)
        p95 = _percentile(lats, 0.95)
        lat = f"{p50:.0f}/{p95:.0f} ms" if p50 is not None else "n/d"
        cost = (
            "desconocido"
            if all(c.get("cost") is None for c in group)
            else f"{sum(c.get('cost') or 0 for c in group):.2f}"
        )
        summary_rows.append(
            "<tr>"
            f"<td><b>{_esc(cand)}</b></td>"
            f"<td>{passed}/{len(valid)}</td>"
            f"<td>{points} / {covered_max}</td>"
            f"<td>{invalid}</td>"
            f"<td>{lat}</td>"
            f"<td>{cost}</td>"
            "</tr>"
        )

    covered = sorted({c["problem_id"] for c in cases})
    covered_weight = sum(PROBLEM_WEIGHTS.get(p, 0) for p in covered)

    # --- per-problem pass matrix -------------------------------------------
    rows = []
    for prob in problems:
        weight = PROBLEM_WEIGHTS.get(prob, 0)
        cells = [f"<td><b>{_esc(prob)}</b> <span class='meta'>({weight}p)</span></td>"]
        for cand in candidates:
            group = [c for c in by_candidate.get(cand, {}).get(prob, []) if c["verdict"] != "invalid_evaluation"]
            invalid = len(by_candidate.get(cand, {}).get(prob, [])) - len(group)
            if not group and not invalid:
                cells.append("<td>-</td>")
                continue
            passed = sum(1 for c in group if c["verdict"] == "pass")
            rate = passed / len(group) if group else 0
            cls = "pass" if rate == 1 else ("warn" if rate > 0 else "fail")
            suffix = f" +{invalid} inv" if invalid else ""
            cells.append(f'<td class="{cls}">{passed}/{len(group)}{suffix}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")

    # --- per-case detail ----------------------------------------------------
    detail_rows = []
    for c in cases:
        verdict = c.get("verdict", "fail")
        diffs = "; ".join(
            f"{d['verb']}.{d['field']}: esperaba {d['expected']!r}, recibió {d['got']!r}"
            for d in c.get("field_diffs", [])
        )
        cats = ", ".join(c.get("categories", []))
        # Evidence links: caller/agent audio + barge-in markers (plan §20).
        evidence = []
        audio = c.get("audio") or {}
        if audio.get("caller"):
            evidence.append(f'<a href="{_esc(audio["caller"])}">caller</a>')
        if audio.get("agent"):
            evidence.append(f'<a href="{_esc(audio["agent"])}">agente</a>')
        n_interrupts = len(c.get("interrupts") or [])
        if n_interrupts:
            evidence.append(f"{n_interrupts} barge-in")
        for check in c.get("checks_not_run") or []:
            evidence.append(f'<span class="warn">{_esc(check)} sin evaluar</span>')
        detail_rows.append(
            "<tr>"
            f"<td>{_esc(c['candidate'])}</td>"
            f"<td>{_esc(c['scenario_id'])}</td>"
            f"<td>{c['repetition']}</td>"
            f"<td class=\"{'pass' if verdict == 'pass' else ('warn' if verdict == 'invalid_evaluation' else 'fail')}\">"
            f"{_esc(verdict.upper())}{' / ' + _esc(c.get('failure_signal')) if c.get('failure_signal') else ''}</td>"
            f"<td>{_esc(cats)}</td>"
            f"<td>{_esc(diffs)}</td>"
            f"<td>{' · '.join(evidence) if evidence else '-'}</td>"
            f"<td>{c['duration_s']}s</td>"
            "</tr>"
        )

    # Checks the rig could not run (e.g. leak_check needs a transcript, and
    # the voice path has no STT): never silently reported as a clean result.
    not_run: dict[str, int] = defaultdict(int)
    for c in cases:
        for check in c.get("checks_not_run") or []:
            not_run[check] += 1
    unevaluated_note = (
        '<p class="meta"><b>Comprobaciones no evaluadas:</b> '
        + "; ".join(f"{_esc(k)} en {v} caso(s)" for k, v in sorted(not_run.items()))
        + ". El check de fuga (problema 14) necesita transcripción y solo la vía "
        "de texto la produce: por WebSocket queda inerte.</p>"
        if not_run
        else ""
    )

    page = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<title>Evaluador local - {_esc(manifest['experiment'])}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #222; }}
table {{ border-collapse: collapse; margin: 1rem 0; }}
th, td {{ border: 1px solid #ccc; padding: .35rem .7rem; text-align: left; }}
th {{ background: #f3f3f3; }}
.pass {{ background: #e2f6e3; }} .warn {{ background: #fff4d6; }}
.fail {{ background: #fbe0e0; }}
.meta {{ color: #666; font-size: .9rem; }}
.banner {{ border: 2px solid #c47f00; background: #fff8e6; padding: .8rem 1rem;
           margin: 1rem 0; border-radius: 6px; }}
.banner table {{ margin: .6rem 0 .2rem; }}
</style></head><body>
<h1>Resultado local — {_esc(manifest['experiment'])}</h1>
{_fixture_banner(manifest)}
<p class="meta">
run_id <code>{_esc(manifest['run_id'])}</code> ·
rules {_esc(manifest['rules_version'])} ·
dataset <code>{_esc(manifest['dataset'])}#{_esc(manifest['dataset_hash'])}</code> ·
{_esc(manifest.get('note', 'resultado local'))}
</p>
<p class="meta">
Cobertura: {len(covered)} familias de problema · peso cubierto {covered_weight}/{MAX_LOCAL_POINTS} puntos.
Los puntos locales estiman el veredicto oficial; no lo certifican.
</p>
<h2>Resumen por configuración</h2>
<table><tr><th>candidato</th><th>correctas/total</th><th>puntos locales / cobertura</th>
<th>inválidas</th><th>latencia p50/p95</th><th>coste/llamada</th></tr>
{"".join(summary_rows)}
</table>
<h2>Pass rate por problema</h2>
<table><tr><th>problema</th>{"".join(f"<th>{_esc(c)}</th>" for c in candidates)}</tr>
{"".join(rows)}
</table>
<h2>Detalle por caso</h2>
<table><tr><th>candidato</th><th>escenario</th><th>rep</th><th>veredicto</th>
<th>categorías</th><th>diferencias de campos</th><th>evidencia</th><th>duración</th></tr>
{"".join(detail_rows)}
</table>
{unevaluated_note}
</body></html>"""
    out = run_dir / "report.html"
    out.write_text(page, encoding="utf-8")
    return out
