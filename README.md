# hackspain-kermit-prosper — Prosper ClinicReflow

HackSpain 2026, Prosper track. A voice agent answers inbound clinic calls over
a Twilio Media Streams WebSocket, negotiates scheduling with the caller, and
submits exact booking actions to the Prosper platform.

## Repository boundaries

| Path | Purpose |
|---|---|
| `backend/` | The complete Python runtime: voice pipeline, clinic + scheduling core, LLM brain, ops console, ops scripts, tests and runtime data. Owns `pyproject.toml`, `uv.lock`, `Makefile` and `.env.example`. |
| `docs/` | Shared team context: Prosper challenge notes, call contract, clinic and scoring docs, reflow interface. |
| `openspec/` | OpenSpec changes and specs for this repository. |
| `frontend/` | **Reserved** for the operator/frontend app. Not implemented in this change. |
| `LICENSE`, `README.md`, `pytest.ini`, `.gitignore` | Repository-level context and root tooling. |

There is no Python project at the repository root. Every runtime command is
executed against `backend/`, either with `--project backend` from the root or
after `cd backend`.

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

## Frontend

The `frontend/` directory is reserved for a future operator UI and is not
implemented here. No empty scaffold is committed.
