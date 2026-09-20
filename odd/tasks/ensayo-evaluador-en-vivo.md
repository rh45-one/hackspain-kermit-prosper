# Ensayo: evaluator + agente local en vivo (demo para jueces)

Goal: rehearse the end-to-end judge demo — live mic call through a browser tab
into the local Prosper agent, evidence appearing in the evaluator console.

## Contract (frozen, from evaluator/src/evaluator/profiles/catalog.py)

| Piece | Port / path | Command |
| --- | --- | --- |
| Clinic double (fake Prosper platform) | 127.0.0.1:18090, key `pk-local-eval` | `uv run --project evaluator python -m evaluator.cli clinic --dataset evaluator/data/clinic_dataset.json` |
| Lab agent (same code as production) | 127.0.0.1:17860 (`/ws`, `/healthz`, `/turns`) | `uv run --project backend python -m agent.serve` + LAB_LAUNCH_ENV |
| Ops console (lab) | 127.0.0.1:17861 | started by `agent.serve` |
| Evaluator dev console | 127.0.0.1:8099 | `uv run --project evaluator python -m evaluator.cli dev --audit-data evaluator/experiments/results/agent-data` |

LAB_LAUNCH_ENV for the agent (overrides backend/.env, which points at
production 7860 + real Prosper API — never use those values for the lab):

```
VOICE_WS_HOST=127.0.0.1 VOICE_WS_PORT=17860 PORT=17860 OPS_HTTP_PORT=17861
TURNS_ADAPTER=1 PROSPER_API_BASE_URL=http://127.0.0.1:18090
PROSPER_API_KEY=pk-local-eval VOICE_ENGINE=cascade
DATA_DIR=evaluator/experiments/results/agent-data
```

Rules: port 7860/7861 and fly.dev/ngrok destinations are production; the lab
never binds or targets them (profiles/guard.py).

## Tasks

- [x] Start clinic double on 18090, verify /healthz
- [x] Start lab agent on 17860 with LAB_LAUNCH_ENV, verify /healthz
- [x] Start evaluator console on 8099 reading the lab DATA_DIR
- [x] Open Orca browser tab at the console, live tab, mic call
- [x] Verify the call lands in the console evidence (history/analytics/judge)
- [x] Judge LLM configured (helmcode glm5.3) and scoring calls
- [x] UI polish pass delegated and verified (index.html, app.js, dashboard.js, live.js, lab.css)
- [x] One-command demo script: demo-lab.sh (start/stop/status)

## Findings

- backend/.env ships PROSPER_API_BASE_URL=production and VOICE_WS_PORT=7860; the lab must
  override via env (LAB_LAUNCH_ENV). ELEVENLABS_VOICE_ID was REPLACE_ME (placeholder) —
  lab uses voice EXAVITQu4vr4xnSDxMaL (Sarah).
- HELMCODE_API_KEY in backend/.env returns 401; the fresh team key works for both the
  agent brain and the console judge. Third-party models (gpt/gemini/claude) need prepaid
  credit the org does not have; flat-rate fast model = deepseek-v4-flash (TTFB ~0.4-2s
  vs glm5.3 ~2-5s). Agent interrupted its own TTS with slow brains: voice callers need
  a fast brain (scripted single-turn call: 177 frames in, 75 KB agent audio, latency 4.6s).
- DATA_DIR relative values resolve against backend/, so the lab must pass an absolute path.
- Voice chain verified end to end: scripted call (harness wsclient) and live browser-mic
  call from Orca (profile cascade) both produced audit JSONL, console history entries
  (real + manual views) and judge verdicts. Judge honestly reports unknown/quality with
  evidence indices when a call has no resolvable intent.
- UI defects fixed by polish pass: duplicated "Corridas disponibles" heading; dead space
  in Probar el agente (added Perfil seleccionado + Qué vas a ver al cerrar); small-sample
  KPI badges (n=N) so honest zeros do not read as catastrophic headlines; Comparar prefills
  the two most recent distinct-candidate runs.
- Orca embedded browser grants getUserMedia without a permission prompt; the live mic
  bridge works there out of the box.

## Demo runbook (judges)

1. `export HELMCODE_API_KEY=... && ./demo-lab.sh` (or verify with `./demo-lab.sh status`).
2. Screen 1: http://127.0.0.1:8099/ — Probar el agente → Iniciar llamada, talk to Prosper.
3. Hang up; screen 2: Llamadas → the manual call with transcript, audio, submissions.
4. Screen 3: ask the judge from the call detail; Seguimiento updates on reload.
