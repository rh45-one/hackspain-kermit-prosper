# hackspain-kermit-prosper — Prosper ClinicReflow

Para retomar la integración y repartir trabajo en otras sesiones, empieza por
[`integration/HANDOFF.md`](integration/HANDOFF.md). Incluye el runtime activo,
las pruebas reales, las incidencias pendientes y cuatro tareas independientes.

HackSpain 2026, Prosper track. A voice agent answers inbound clinic calls over
a Twilio Media Streams WebSocket, negotiates scheduling with the caller, and
submits exact booking actions to the Prosper platform.

## Repository boundaries

| Path | Purpose |
|---|---|
| `backend/` | The complete Python runtime: voice pipeline, clinic + scheduling core, LLM brain, ops console, ops scripts, tests and runtime data. Owns `pyproject.toml`, `uv.lock`, `Makefile` and `.env.example`. |
| `docs/` | Shared team context: Prosper challenge notes, call contract, clinic and scoring docs, reflow interface. |
| `evaluator/` | Standalone local evaluator/tester/benchmark: scenario corpus, local clinic + submission receiver, deterministic comparator, harness caller, test double and HTML reports. Owns `pyproject.toml` and `uv.lock`. |
| `openspec/` | OpenSpec changes and specs for this repository. |
| `frontend/` | Staff FrontDesk (Next.js): calls, patients and calendar from the backend; explicit offline demo mode. |
| `integration/` | Cross-package contract tests and the local stack runbook. |
| `LICENSE`, `README.md`, `pytest.ini`, `.gitignore` | Repository-level context and root tooling. |

There is no Python project at the repository root. Use `--project backend`
or `--project evaluator` for the corresponding runtime.

## Integrated stack

See [the integration runbook](integration/README.md) for running the local clinic,
the combined voice/ops backend and FrontDesk together. `make check` runs both
Python suites, cross-package contracts, lint, frontend type generation/typecheck
and the production frontend build. It needs no provider credentials.

## Backend quickstart

```sh
# 1. Install dependencies (creates backend/.venv).
uv sync --project backend

# 2. Configure credentials — never commit this file.
cp backend/.env.example backend/.env
$EDITOR backend/.env

# 3. Run the voice WebSocket server (ws://localhost:7860/ws).
uv run --project backend python -m agent.voice.server

# 4. Run the jury-facing ops console (http://localhost:7861/ops).
uv run --project backend uvicorn agent.ops.console:app --port 7861
```

The same targets are wrapped by the backend Makefile:

```sh
make -C backend sync
make -C backend run
make -C backend ops
```

## Deploying

One public host serves everything: `wss://<host>/ws` for the harness and
`https://<host>/ops` for the jury, from a single process
(`agent.serve`) on a single port. See [`docs/deployment.md`](docs/deployment.md)
for the Fly.io (region `mad`) setup, cost and rollback.

```sh
make -C backend serve          # same single-port shape, locally
make -C backend docker-build   # the deployed image
make -C backend deploy         # fly deploy
```

## Tests, lint and smoke checks

All commands below are written to run from the repository root:

```sh
uv run --project backend pytest -q
uv run --project backend ruff check backend/src backend/tests

# Health smoke test (no network, no credentials).
uv run --project backend python -c "from fastapi.testclient import TestClient; \
from agent.voice.server import app; print(TestClient(app).get('/healthz').json())"
```

`pytest.ini` at the root exists only so the root-relative commands above
discover the backend suite and its async settings; `backend/pyproject.toml`
carries the equivalent backend-relative configuration for runs inside
`backend/`.

See [`backend/README.md`](backend/README.md) for environment variables, the
ngrok tunnel, endpoints and credentials.

## Local evaluator

`evaluator/` grades the agent without the remote harness: a versioned
scenario corpus, a local clinic + submission receiver that mirrors the
official contract, and a deterministic binary comparator. Results are
labelled "resultado local" — they estimate, not certify, the official
verdict.

```sh
cd evaluator
uv sync
uv run pytest -q
uv run python -m evaluator.cli run --config experiments/smoke.yaml
```

See [`evaluator/README.md`](evaluator/README.md) for scenarios, candidates
and report output.

## Frontend

Staff FrontDesk reads calls, diagnostics, patients and appointments through
the combined `agent.serve` backend. FastAPI `/ops` remains the HTML fallback.

```sh
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Open http://localhost:3000 — it redirects to `/calls`. Set
`FRONTDESK_DEMO=true` for the original mock UI without a backend. Live mode
is read-only; settings and manual takeover are available only in the demo.
