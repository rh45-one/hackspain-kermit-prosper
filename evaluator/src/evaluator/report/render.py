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
# --- Plain Spanish for everything the report prints -------------------------
#
# `record_mismatch`, `field_diffs` and `policy_id` are the challenge's
# vocabulary, not Spanish. The bench is now the gate every backend change
# goes through, and people who did not write it read this page: whoever
# opens it has to see which field was lost and why, without translating.

VERDICT_LABELS = {
    "pass": ("CORRECTA", "el agente envió exactamente lo que se esperaba"),
    "fail": ("INCORRECTA", "el agente envió algo distinto de lo esperado"),
    "invalid_evaluation": (
        "NO EVALUABLE",
        "falló el banco de pruebas, no el agente: el caso no cuenta",
    ),
}

SIGNAL_LABELS = {
    "missing_record": "no envió ninguna acción",
    "record_mismatch": "envió una acción distinta de la esperada",
    "transcript_leak": "dijo en voz alta un dato protegido del paciente",
}

CATEGORY_LABELS = {
    "stt_error": "no entendió lo que se le dijo",
    "identity_error": "identificó mal al paciente o sus datos",
    "reasoning_error": "eligió mal: acción, hueco, médico o sede",
    "tool_error": "falló al usar una herramienta",
    "state_error": "mezcló información entre llamadas",
    "submission_error": "el envío fue rechazado por la API",
    "privacy_error": "fuga de un dato protegido",
    "transport_error": "se cayó la conexión",
    "provider_error": "falló el proveedor (modelo, voz)",
    "harness_error": "falló el banco de pruebas",
    "unknown": "sin clasificar",
}

FIELD_LABELS = {
    "patient_id": "paciente",
    "provider_id": "médico",
    "location_id": "sede",
    "appointment_type_id": "tipo de cita",
    "appointment_id": "cita",
    "slot": "fecha y hora",
    "policy_id": "plan / póliza",
    "reason": "motivo",
    "given_name": "nombre",
    "first_surname": "primer apellido",
    "second_surname": "segundo apellido",
    "national_id": "DNI / NIE",
    "date_of_birth": "fecha de nacimiento",
    "phone": "teléfono",
    "email": "correo",
    "insurer": "aseguradora",
    "action": "tipo de acción",
}

VERB_LABELS = {
    "BOOK": "reservar",
    "REGISTER": "dar de alta",
    "RESCHEDULE": "cambiar",
    "CANCEL": "anular",
    "NO_ACTION": "no hacer nada",
    "ESCALATE": "pasar a una persona",
}

PROBLEM_LABELS = {
    "simple_booking": "cita simple",
    "switchboard": "llamadas simultáneas",
    "doctor_and_site": "médico y sede",
    "new_patient": "paciente nuevo",
    "when_exactly": "cuándo exactamente",
    "rules": "las reglas",
    "no_slot_free": "sin hueco libre",
    "change_and_cancel": "cambiar y anular",
    "third_party": "llama un tercero",
    "triage": "triaje",
    "languages": "idiomas",
    "noise": "ruido de fondo",
    "difficult_caller": "llamante difícil",
    "adversarial": "intento de engaño",
    "nearest_site": "sede más cercana",
    "questions": "preguntas",
    "second_policy": "segunda póliza",
    "real_call": "llamada real",
}

CHECK_LABELS = {
    "leak_check": "comprobación de privacidad (problema 14)",
}


def _field_name(field: str) -> str:
    return FIELD_LABELS.get(field, field)


def _submitted_field_count(submitted: list) -> int:
    """How many fields the agent actually sent, across all its actions."""
    total = 0
    for action in submitted:
        nested = action.get("new_patient")
        total += len(nested) if isinstance(nested, dict) else len(action) - 1
    return total


def _describe_diff(diff: dict) -> str:
    """One field difference, readable without knowing the schema."""
    verb = VERB_LABELS.get(diff.get("verb", ""), diff.get("verb", ""))
    got = diff.get("got")
    expected = diff.get("expected")
    got_text = "no lo envió" if got in (None, "") else f"envió «{got}»"
    return f"al {verb}, {_field_name(diff['field'])}: se esperaba «{expected}», {got_text}"


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


def _stability(cases: list, candidates: list[str]) -> tuple[str, str]:
    """Per-scenario pass rate, and how wide the noise band is.

    Two identical runs of the same agent moved six of 21 scenarios, in both
    directions. A single verdict per scenario hides that: 1/3 and 3/3 are
    not the same result and must not be printed the same. Returns
    (headline, table); both empty when there is only one repetition.
    """
    by_case: dict[tuple[str, str], list] = defaultdict(list)
    for c in cases:
        if c["verdict"] != "invalid_evaluation":
            by_case[(c["candidate"], c["scenario_id"])].append(c)
    if not by_case or max(len(g) for g in by_case.values()) < 2:
        return "", ""

    scenarios = sorted({sid for _, sid in by_case})
    rows = []
    unstable_total = 0
    for sid in scenarios:
        cells = [f"<td><b>{_esc(sid)}</b></td>"]
        for cand in candidates:
            group = by_case.get((cand, sid), [])
            if not group:
                cells.append("<td>-</td>")
                continue
            passed = sum(1 for c in group if c["verdict"] == "pass")
            n = len(group)
            if passed == n:
                cls, verdict = "pass", "siempre correcta"
            elif passed == 0:
                cls, verdict = "fail", "siempre incorrecta"
            else:
                cls, verdict = "warn", "<b>INESTABLE</b>"
                unstable_total += 1
            cells.append(
                f'<td class="{cls}">{passed}/{n}<br>'
                f"<span class='meta'>{verdict}</span></td>"
            )
        rows.append("<tr>" + "".join(cells) + "</tr>")

    total = len(scenarios) * max(1, len(candidates))
    pct = round(100 * unstable_total / total) if total else 0
    headline = (
        f'<div class="banner"><b>Banda de ruido: {unstable_total} de {total} '
        f"escenarios dan resultados distintos entre repeticiones ({pct}%).</b> "
        "El agente no es determinista, así que <b>una sola ejecución no "
        "compara dos versiones</b>: una diferencia menor que esa banda no es "
        "una mejora ni un empeoramiento, es ruido. Lo que sí se puede leer "
        "es la tasa por escenario, y sobre todo los que salen "
        "<b>siempre incorrectos</b>: ésos son fallos de verdad."
        "</div>"
        if unstable_total
        else '<p class="meta">Ningún escenario cambió de veredicto entre '
        "repeticiones en esta ejecución.</p>"
    )
    header = "".join(f"<th>{_esc(c)}</th>" for c in candidates)
    table = (
        "<h2>Estabilidad por escenario</h2>"
        f"{headline}"
        f"<table><tr><th>escenario</th>{header}</tr>{''.join(rows)}</table>"
    )
    return headline, table


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
        header = (
            f"<td><b>{_esc(PROBLEM_LABELS.get(prob, prob))}</b> "
            f"<span class='meta'>{_esc(prob)} · peso {weight}</span></td>"
        )
        cells = [header]
        for cand in candidates:
            group = [c for c in by_candidate.get(cand, {}).get(prob, []) if c["verdict"] != "invalid_evaluation"]
            invalid = len(by_candidate.get(cand, {}).get(prob, [])) - len(group)
            if not group and not invalid:
                cells.append("<td>-</td>")
                continue
            passed = sum(1 for c in group if c["verdict"] == "pass")
            rate = passed / len(group) if group else 0
            cls = "pass" if rate == 1 else ("warn" if rate > 0 else "fail")
            suffix = f" +{invalid} no eval." if invalid else ""
            cells.append(f'<td class="{cls}">{passed}/{len(group)}{suffix}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")

    # --- per-case detail ----------------------------------------------------
    detail_rows = []
    for c in cases:
        verdict = c.get("verdict", "fail")
        field_diffs = c.get("field_diffs", [])
        diffs = "<br>".join(_esc(_describe_diff(d)) for d in field_diffs)
        # "6 de 7 correctos y suspendido" is the shape of most real losses:
        # say it out loud so the reader sees the scale of the miss at once.
        total_fields = _submitted_field_count(c.get("submitted") or [])
        if field_diffs and total_fields:
            noun = "campo" if total_fields == 1 else "campos"
            diffs = (
                f"<b>{len(field_diffs)} de {total_fields} {noun} mal</b><br>{diffs}"
            )
        if not diffs and c.get("missing_actions"):
            diffs = "<br>".join(
                f"faltó: {_esc(VERB_LABELS.get(a.get('action', ''), a.get('action', '')))}"
                for a in c["missing_actions"]
            )
        if c.get("extra_actions"):
            extra = "<br>".join(
                f"sobró: {_esc(VERB_LABELS.get(a.get('action', ''), a.get('action', '')))}"
                for a in c["extra_actions"]
            )
            diffs = f"{diffs}<br>{extra}" if diffs else extra
        cats = ", ".join(
            CATEGORY_LABELS.get(cat, cat) for cat in c.get("categories", [])
        )
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
            evidence.append(
                f'<span class="warn">{_esc(CHECK_LABELS.get(check, check))} '
                "sin hacer</span>"
            )
        for note in c.get("notes") or []:
            evidence.append(f"<span class='meta'>{_esc(note)}</span>")
        label, _ = VERDICT_LABELS.get(verdict, (verdict.upper(), ""))
        signal = c.get("failure_signal")
        signal_text = (
            f"<br><span class='meta'>{_esc(SIGNAL_LABELS.get(signal, signal))}</span>"
            if signal
            else ""
        )
        # The first error explains an unusable case; the rest is in cases.jsonl.
        if verdict == "invalid_evaluation" and c.get("errors"):
            signal_text = f"<br><span class='meta'>{_esc(c['errors'][0])}</span>"
        problem = c.get("problem_id", "")
        detail_rows.append(
            "<tr>"
            f"<td>{_esc(c['candidate'])}</td>"
            f"<td>{_esc(PROBLEM_LABELS.get(problem, problem))}"
            f"<br><span class='meta'>{_esc(c['scenario_id'])} · rep {c['repetition']}</span></td>"
            f"<td class=\"{'pass' if verdict == 'pass' else ('warn' if verdict == 'invalid_evaluation' else 'fail')}\">"
            f"{_esc(label)}{signal_text}</td>"
            f"<td>{_esc(cats)}</td>"
            f"<td>{diffs}</td>"
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
        '<p class="banner"><b>Comprobaciones que no se han llegado a hacer:</b> '
        + "; ".join(
            f"{_esc(CHECK_LABELS.get(k, k))} en {v} caso(s)"
            for k, v in sorted(not_run.items())
        )
        + ". Esos casos pueden aparecer como CORRECTA sin que se haya comprobado "
        "que el agente no dijo el DNI o el teléfono del paciente en voz alta: "
        "hace falta la transcripción y solo la vía de texto la produce. Por "
        "WebSocket el evaluador no transcribe, así que no lo puede mirar.</p>"
        if not_run
        else ""
    )

    _, stability_table = _stability(cases, candidates)

    page = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<title>Pronto · evaluador local — {_esc(manifest['experiment'])}</title>
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
<h1>Pronto · resultado local — {_esc(manifest['experiment'])}</h1>
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
<h2>Cómo se lee esto</h2>
<ul>
<li><b>CORRECTA</b>: el agente envió exactamente la acción esperada, campo por
campo. Un solo campo distinto y el caso es incorrecto: así puntúa la
plataforma, no hay puntos parciales.</li>
<li><b>INCORRECTA</b>: el agente envió algo distinto, o no envió nada.</li>
<li><b>NO EVALUABLE</b>: falló el banco de pruebas (no le llegó voz al agente,
se cortó la conexión, no arrancó la llamada). <b>No es un fallo del agente</b> y
no cuenta ni a favor ni en contra.</li>
<li><b>Puntos locales</b>: cada familia de problema pesa distinto. Es una
estimación calculada aquí, con estos datos de mentira; no es la puntuación
oficial.</li>
<li><b>El agente no es determinista.</b> Dos ejecuciones idénticas del mismo
código pueden dar veredictos distintos en el mismo escenario. Con
<code>repetitions</code> mayor que 1 hay abajo una tabla de estabilidad: mira
ésa antes de concluir que algo ha mejorado.</li>
</ul>
<h2>Resumen por configuración</h2>
<table><tr><th>candidato</th><th>correctas / evaluables</th>
<th>puntos locales / máximo cubierto</th>
<th>no evaluables</th><th>tiempo de respuesta p50/p95</th><th>coste</th></tr>
{"".join(summary_rows)}
</table>
{stability_table}
<h2>Pass rate por problema</h2>
<table><tr><th>problema</th>{"".join(f"<th>{_esc(c)}</th>" for c in candidates)}</tr>
{"".join(rows)}
</table>
<h2>Detalle por caso</h2>
<table><tr><th>candidato</th><th>caso</th><th>veredicto</th>
<th>qué salió mal</th><th>qué campo se perdió</th><th>evidencia</th><th>duración</th></tr>
{"".join(detail_rows)}
</table>
{unevaluated_note}
</body></html>"""
    out = run_dir / "report.html"
    out.write_text(page, encoding="utf-8")
    return out
