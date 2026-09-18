"""Ops console: what the jury sees. Live calls, transcripts, reflow plan.

Mounts read-only views over data/calls/*.jsonl and data/reflow/*.json.
Run: uv run uvicorn agent.ops.console:app --port 7861
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from agent.config import settings

app = FastAPI(title="ClinicReflow ops", docs_url=None, redoc_url=None)

_INDEX = """<!doctype html><html><head><title>ClinicReflow — ops</title>
<meta charset="utf-8">
<style>
body{font-family:-apple-system,Inter,sans-serif;margin:0;background:#0e1116;color:#e6e8ee}
header{padding:18px 24px;border-bottom:1px solid #232a35;display:flex;justify-content:space-between;align-items:center}
h1{font-size:17px;margin:0} .pill{background:#1d2634;border-radius:99px;padding:4px 12px;font-size:12px;color:#9fb0c3}
main{padding:24px;display:grid;gap:20px;grid-template-columns:1fr 1fr}
.card{background:#151b24;border:1px solid #232a35;border-radius:12px;padding:16px}
.card h2{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:#9fb0c3;margin:0 0 10px}
.row{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid #1d2530;font-size:14px}
.row:last-child{border:0} .ok{color:#7ad48a}.bad{color:#f08a8a}.warn{color:#e8c468}
#timeline{font-family:ui-monospace,monospace;font-size:12px;max-height:340px;overflow:auto;line-height:1.7}
metrics span{margin-right:14px}
</style></head><body>
<header><h1>🏠 Clínica Arenal — ClinicReflow</h1><span class="pill" id="clock"></span></header>
<main>
<div class="card"><h2>Reflow plan — médico no disponible</h2><div id="reflow">—</div>
<div style="margin-top:12px"><b style="font-size:22px" id="recovered">—</b> <span style="color:#9fb0c3">citas recuperadas</span></div></div>
<div class="card"><h2>Live calls</h2><div id="calls">—</div></div>
<div class="card" style="grid-column:1/3"><h2>Call timeline</h2><div id="timeline">select a call</div></div>
</main>
<script>
async function j(u){return (await fetch(u)).json()}
async function refresh(){
  const calls=await j('/ops/api/calls'); const reflow=await j('/ops/api/reflow');
  document.getElementById('calls').innerHTML = calls.map(c=>
    `<div class="row" style="cursor:pointer" onclick="openCall('${c.call_id}')"><span>${c.call_id}</span><span>${c.actions} acciones</span></div>`).join('')||'—';
  let html=''; let recovered=0, total=0;
  for(const b of reflow){for(const a of b.appointments){
    total++;
    const st=a.decision?a.decision.outcome:'pending';
    if(st==='accepted')recovered++;
    html+=`<div class="row"><span>${a.patient_display_name||a.appointment_id}</span><span class="${st==='accepted'?'ok':st==='pending'?'warn':'bad'}">${st}</span></div>`;}}
  document.getElementById('reflow').innerHTML=html||'no batch yet';
  document.getElementById('recovered').textContent=`${recovered}/${total}`;
  document.getElementById('clock').textContent=new Date().toLocaleTimeString('es-ES');
}
async function openCall(id){
  const events=await j('/ops/api/calls/'+id);
  document.getElementById('timeline').innerHTML=events.map(e=>
    `<div><span style="color:#5b6b7f">${(e.ts||'').slice(11,19)}</span> <b>${e.event}</b> ${e.data?JSON.stringify(e.data).slice(0,220):''}</div>`).join('');
}
refresh(); setInterval(refresh,3000);
</script></body></html>"""


@app.get("/ops", response_class=HTMLResponse)
async def index() -> str:
    return _INDEX


@app.get("/ops/api/calls")
async def calls() -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for path in sorted(Path(settings.calls_dir).glob("*.jsonl"), reverse=True)[:30]:
        actions = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                if json.loads(line).get("event") == "action_queued":
                    actions += 1
            except json.JSONDecodeError:
                continue
        out.append({"call_id": path.stem, "actions": actions})
    return out


@app.get("/ops/api/calls/{call_id}")
async def call_detail(call_id: str) -> list[dict[str, object]]:
    path = Path(settings.calls_dir) / f"{call_id}.jsonl"
    if not path.exists():
        raise HTTPException(404, "call not found")
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


@app.get("/ops/api/reflow")
async def reflow() -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    rdir = Path(settings.data_dir) / "reflow"
    if not rdir.exists():
        return out
    for batch_path in sorted(rdir.glob("*.json")):
        batch = json.loads(batch_path.read_text(encoding="utf-8"))
        for appt in batch.get("appointments", []):
            decision = None
            dpath = rdir / batch_path.stem / f"{appt['appointment_id']}.json"
            if dpath.exists():
                decision = json.loads(dpath.read_text(encoding="utf-8"))
            appt = {**appt, "decision": decision}
        out.append(batch)
    return out
