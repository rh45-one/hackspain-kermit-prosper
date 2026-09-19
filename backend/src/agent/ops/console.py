"""Ops console: what the jury sees. Live calls, transcripts, reflow plan.

Mounts read-only views over data/<org_id>/calls/*.jsonl and data/reflow/*.json.

Which organisation a view reads is no longer a constant. A signed-in person
reads the clinic their session is pointed at, and everything else — a service
token, a loopback caller — reads the one clinic this process serves, which is
what it read before sessions existed. The resolution lives in one function,
`auth.request_org_id`, and never in a route.

Run: uv run uvicorn agent.ops.console:app --port 7861
"""
from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from agent.accounts.store import ensure_database
from agent.config import settings
from agent.ops import auth

_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})

# Any of these means somebody else forwarded the request, so the address on it
# was written by that somebody and is not evidence of anything.
_FORWARDED_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip")


def require_ops_access(request: Request) -> None:
    """Gate every ops view. Fails closed off-host.

    These views serve whole call transcripts, and a caller dictates their
    national id and telephone number out loud during a registration — those
    words are in the JSONL verbatim. There was no check here at all, and the
    deployment publishes this app: `Dockerfile` runs `agent.serve`, which
    mounts these routes, and `fly.toml` puts port 8080 on the public internet.
    Anyone holding the URL could have read every patient's id.

    Three ways in, in this order, and they are not three doors for the same
    caller:

    1. **A session cookie.** A person who signed in at `/ops/login`. This is
       how a person gets in once anybody has an account, and it is the only
       one of the three that knows who you are and which clinics you may see.
    2. **`OPS_TOKEN` in the `X-Ops-Token` header.** A service, which here
       means the Next panel's server-side proxy. It has one job and no
       identity to have. The `?token=` form of it is the *person's* version —
       the one you use by pasting a URL — and it closes the moment the first
       person is provisioned, which is the whole of "the login replaces the
       token for people".
    3. **Loopback with no `OPS_TOKEN` set.** Untouched. A laptop keeps working
       with no configuration, and the evaluator bench drives `POST /turns`
       through this same gate from 127.0.0.1.

    Unset plus public remains the one combination that must never quietly
    work.
    """
    # A person, with a session. Checked first: a signed-in person never falls
    # through to a shared secret.
    #
    # A *principal*, not merely a session row: the row outlives an account
    # being disabled and a membership being revoked, and a session that no
    # longer resolves to a person in an organisation must be a refusal rather
    # than a caller who silently reads the default clinic.
    if auth.principal_of(request) is not None:
        return

    token = settings().ops_token
    if token:
        offered = request.headers.get("x-ops-token")
        if offered is None and not auth.people_are_provisioned():
            offered = request.query_params.get("token")
        if offered == token:
            return
        raise HTTPException(401, "ops token required")
    # `request.client.host` is not the peer when a proxy is in front: uvicorn
    # rewrites it from X-Forwarded-For for peers it trusts, and everyone sets
    # FORWARDED_ALLOW_IPS=* in a container the first time they want to see a
    # real client address. The day somebody does, `X-Forwarded-For: 127.0.0.1`
    # from the open internet would read as loopback and open this with no
    # token at all. So a forwarded request is never loopback, whatever the
    # address says — if something is proxying for you, you are not local.
    if any(h in request.headers for h in _FORWARDED_HEADERS):
        raise HTTPException(403, "ops console is loopback-only until OPS_TOKEN is set")
    host = (request.client.host if request.client else "") or ""
    if host in _LOOPBACK:
        return
    raise HTTPException(
        403,
        "ops console is loopback-only until OPS_TOKEN is set",
    )

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Migrate the platform database when this console runs on its own.

    Inside `agent.serve` only this app's *router* is mounted, so this never
    runs there and the voice server's lifespan does the same job once. Both
    paths call the same idempotent function.
    """
    ensure_database()
    yield


app = FastAPI(title="Pronto ops", docs_url=None, redoc_url=None, lifespan=_lifespan)

_INDEX = """<!doctype html><html><head><title>Pronto — ops</title>
<meta charset="utf-8">
<style>
body{font-family:-apple-system,Inter,sans-serif;margin:0;background:#0e1116;color:#e6e8ee}
header{padding:18px 24px;border-bottom:1px solid #232a35;display:flex;justify-content:space-between;align-items:center;gap:16px}
h1{font-size:17px;margin:0;display:flex;align-items:center;gap:10px;letter-spacing:-.03em}
h1 svg{width:20px;height:20px;flex-shrink:0}
h1 .clinic{font-weight:500;color:#9fb0c3;letter-spacing:0;font-size:13px}
.pill{background:#1d2634;border-radius:99px;padding:4px 12px;font-size:12px;color:#9fb0c3;
border:0;font-family:inherit;cursor:inherit}
#out button{cursor:pointer}
select{background:#1d2634;color:#e6e8ee;border:1px solid #232a35;border-radius:99px;
padding:4px 10px;font-size:12px;font-family:inherit}
main{padding:24px;display:grid;gap:20px;grid-template-columns:1fr 1fr}
.card{background:#151b24;border:1px solid #232a35;border-radius:12px;padding:16px}
.card h2{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:#9fb0c3;margin:0 0 10px}
.row{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid #1d2530;font-size:14px}
.row:last-child{border:0} .ok{color:#7ad48a}.bad{color:#f08a8a}.warn{color:#e8c468}
#timeline{font-family:ui-monospace,monospace;font-size:12px;max-height:340px;overflow:auto;line-height:1.7}
metrics span{margin-right:14px}
</style></head><body>
<header><h1><svg viewBox="0 0 64 64" aria-hidden="true"><g transform="translate(0.31 0)"><path fill="currentColor" d="M14 56V26A18 18 0 0 1 49.386665 21.341257L41.659258 23.41181A10 10 0 1 0 41.659258 28.58819L49.386665 30.658743A18 18 0 0 1 24.8 42.497273A2 2 0 0 0 22 44.330303V56Z"/></g></svg>Pronto <span class="clinic" id="clinic">Clínica Arenal</span></h1>
<div style="display:flex;align-items:center;gap:10px">
<select id="org" hidden onchange="switchOrg(this.value)"></select>
<span class="pill" id="who" hidden></span>
<span class="pill" id="clock"></span>
<form method="post" action="/ops/logout" id="out" hidden style="margin:0"><button class="pill" type="submit">Salir</button></form>
</div></header>
<main>
<div class="card"><h2>Reflow plan — médico no disponible</h2><div id="reflow">—</div>
<div style="margin-top:12px"><b style="font-size:22px" id="recovered">—</b> <span style="color:#9fb0c3">citas recuperadas</span></div></div>
<div class="card"><h2>Live calls</h2><div id="calls">—</div></div>
<div class="card" style="grid-column:1/3"><h2>Call timeline</h2><div id="timeline">select a call</div></div>
</main>
<script>
async function j(u){return (await fetch(u)).json()}
// Who is looking, and at which clinic. A 401 here means nobody is signed in —
// a service token or a loopback caller — and the console then shows exactly
// what it always showed: the one clinic this process serves.
let session=null;
async function loadSession(){
  const r=await fetch('/ops/api/session');
  if(!r.ok){return}
  session=await r.json();
  const here=session.organizations.find(o=>o.id===session.org_id);
  document.getElementById('clinic').textContent=(here&&here.name)||session.org_id;
  const who=document.getElementById('who');
  who.textContent=session.email; who.hidden=false;
  document.getElementById('out').hidden=false;
  const sel=document.getElementById('org');
  if(session.organizations.length>1){
    // Built with the DOM and not with a template string: an organisation name
    // is somebody else's text and must never become somebody else's markup.
    sel.replaceChildren(...session.organizations.map(o=>{
      const opt=new Option(o.name,o.id); opt.selected=o.id===session.org_id; return opt;}));
    sel.hidden=false;
  }
}
async function switchOrg(id){
  const r=await fetch('/ops/api/session/org',{method:'POST',
    headers:{'content-type':'application/json'},body:JSON.stringify({org_id:id})});
  if(r.ok){await loadSession(); refresh();}
}
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
loadSession().then(refresh); setInterval(refresh,3000);
</script></body></html>"""


@app.get("/ops", response_class=HTMLResponse)
async def index(request: Request) -> Response:
    """The console. A person with no session is sent to the login page.

    Only this route redirects. Every API route below keeps answering 401 and
    403, because a poll that follows a redirect and gets an HTML login page
    back is a failure that arrives looking like data.
    """
    try:
        require_ops_access(request)
    except HTTPException:
        if auth.people_are_provisioned():
            return RedirectResponse("/ops/login", status_code=303)
        raise
    return HTMLResponse(_INDEX)


@app.get("/ops/api/calls")
async def calls(
    request: Request, _: None = Depends(require_ops_access)
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    org_id = auth.request_org_id(request)
    # Sorted by call id, not by full path: the traces of one organisation now
    # come from two directories (the current layout and the pre-organisation
    # one), and sorting by path would group them by directory instead of
    # listing the newest ids first the way this console always has.
    paths = sorted(settings().call_trace_paths(org_id), key=lambda p: p.name, reverse=True)
    for path in paths[:30]:
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
async def call_detail(
    call_id: str, request: Request, _: None = Depends(require_ops_access)
) -> list[dict[str, object]]:
    # The id lands in a filesystem path, so it may only ever be a bare name.
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", call_id) or call_id.startswith("."):
        raise HTTPException(400, "invalid call id")
    path = settings().call_trace_path(call_id, auth.request_org_id(request))
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
async def reflow(_: None = Depends(require_ops_access)) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    rdir = Path(settings().data_dir) / "reflow"
    if not rdir.exists():
        return out
    for batch_path in sorted(rdir.glob("*.json")):
        batch = json.loads(batch_path.read_text(encoding="utf-8"))
        appointments = []
        for appt in batch.get("appointments", []):
            decision = None
            dpath = rdir / batch_path.stem / f"{appt['appointment_id']}.json"
            if dpath.exists():
                decision = json.loads(dpath.read_text(encoding="utf-8"))
            appointments.append({**appt, "decision": decision})
        out.append({**batch, "appointments": appointments})
    return out


# The product view lives in its own module: same data, different audience, and
# it must not grow inside this debugging console. `live` reaches back for
# `require_ops_access` lazily, so this import is one-way and order-independent.
from agent.ops.agent_config import router as agent_config_router
from agent.ops.auth import router as auth_router
from agent.ops.cover import router as cover_router
from agent.ops.incidents import router as incidents_router
from agent.ops.directory import router as directory_router
from agent.ops.frontdesk import router as frontdesk_router
from agent.ops.graph import router as graph_router
from agent.ops.live import router as live_router

app.include_router(live_router)
# The operator panel a teammate built in frontend/ has been calling these
# since it landed, and they did not exist: /calls, /patients, /calendar and
# /directory have all been answering 404. The router comes from PR #2; the
# access gate on it does not, and without one it would have served whole
# transcripts to anyone with the URL.
app.include_router(frontdesk_router)
# The clinic as a drawing: who exists, who covers what, and who hears about
# each of the eighteen ways a call can end. No patient data passes through it.
app.include_router(graph_router)
# What the agent is actually running. The settings screen used to be a
# paragraph telling you to edit a file, and it named an engine that cannot
# start, so it was documentation that was also wrong.
app.include_router(agent_config_router)
# Who should cover this, asked of Jev when somebody refreshes the panel. It is
# a suggestion beside the configured route, never instead of it, and it is
# deliberately not on the call path: see the module docstring.
app.include_router(cover_router)
# Lo que va mal, mientras va mal. Una llamada que escala abre una fila aquí y
# se la asigna a quien dicen las rutas — la misma persona a la que llamaría el
# agente. Antes eso sólo existía como línea de auditoría en un volumen.
app.include_router(incidents_router)
# Sign in, sign out, switch clinic, and write a clinic's Prosper key. The only
# routes here that are NOT behind `require_ops_access`: /ops/login cannot be,
# or nobody could ever reach it. Every route on it that does anything checks
# a session for itself.
app.include_router(auth_router)
# The clinic's own people and routes: the four hand-written roles in
# `clinic/graph.py` and the eighteen escalations, as data the panel can edit.
# Members read, admins write; staff contact details are behind that membership
# check and not merely behind the ops door.
app.include_router(directory_router)
