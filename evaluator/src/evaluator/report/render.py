"""Self-contained HTML report for a finished run.

Reads `manifest.json` + `cases.jsonl` from a results directory and writes
`report.html` next to them. Every figure is labelled "resultado local" -
the local judge is an estimator until validated against the official one.
"""
from __future__ import annotations

import html
import json
from collections import defaultdict
from pathlib import Path


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

    def esc(x: object) -> str:
        return html.escape(str(x))

    rows = []
    for prob in problems:
        cells = [f"<td><b>{esc(prob)}</b></td>"]
        for cand in candidates:
            group = by_candidate.get(cand, {}).get(prob, [])
            if not group:
                cells.append("<td>-</td>")
                continue
            passed = sum(1 for c in group if c["passed"])
            rate = passed / len(group)
            cls = "pass" if rate == 1 else ("warn" if rate > 0 else "fail")
            cells.append(f'<td class="{cls}">{passed}/{len(group)}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")

    detail_rows = []
    for c in cases:
        diffs = "; ".join(
            f"{d['verb']}.{d['field']}: esperaba {d['expected']!r}, recibió {d['got']!r}"
            for d in c.get("field_diffs", [])
        )
        detail_rows.append(
            "<tr>"
            f"<td>{esc(c['candidate'])}</td>"
            f"<td>{esc(c['scenario_id'])}</td>"
            f"<td>{c['repetition']}</td>"
            f"<td class=\"{'pass' if c['passed'] else 'fail'}\">"
            f"{'PASS' if c['passed'] else esc(c.get('failure_signal') or 'FAIL')}</td>"
            f"<td>{esc(diffs)}</td>"
            f"<td>{c['duration_s']}s</td>"
            "</tr>"
        )

    page = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<title>Evaluador local - {esc(manifest['experiment'])}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #222; }}
table {{ border-collapse: collapse; margin: 1rem 0; }}
th, td {{ border: 1px solid #ccc; padding: .35rem .7rem; text-align: left; }}
th {{ background: #f3f3f3; }}
.pass {{ background: #e2f6e3; }} .warn {{ background: #fff4d6; }}
.fail {{ background: #fbe0e0; }}
.meta {{ color: #666; font-size: .9rem; }}
</style></head><body>
<h1>Resultado local — {esc(manifest['experiment'])}</h1>
<p class="meta">
run_id <code>{esc(manifest['run_id'])}</code> ·
rules {esc(manifest['rules_version'])} ·
dataset <code>{esc(manifest['dataset'])}#{esc(manifest['dataset_hash'])}</code> ·
{esc(manifest.get('note', 'resultado local'))}
</p>
<h2>Pass rate por problema</h2>
<table><tr><th>problema</th>{"".join(f"<th>{esc(c)}</th>" for c in candidates)}</tr>
{"".join(rows)}
</table>
<h2>Detalle por caso</h2>
<table><tr><th>candidato</th><th>escenario</th><th>rep</th><th>resultado</th>
<th>diferencias de campos</th><th>duración</th></tr>
{"".join(detail_rows)}
</table>
</body></html>"""
    out = run_dir / "report.html"
    out.write_text(page, encoding="utf-8")
    return out
