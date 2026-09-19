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

# 3. Run the voice WebSocket server (binds to 0.0.0.0:7860).
uv run --project backend python -m agent.voice.server

# 4. Run the jury-facing ops console (http://localhost:7861/ops).
uv run --project backend uvicorn agent.ops.console:app --port 7861
```

The server is reachable from this machine at `http://localhost:7860` and from
other devices on the same network at `http://<server-lan-ip>:7860`. Set
`VOICE_WS_HOST=0.0.0.0` in `backend/.env` to retain this all-interface bind.

The same targets are wrapped by the backend Makefile:

```sh
make -C backend sync
make -C backend run
make -C backend ops
make -C backend public        # voice server + ngrok; phone UI at https://<host>/call
```

### Browser phone (WebSocket call)

`make -C backend public` is the one-command way to talk to the agent from a
browser. It starts the voice server if needed, then opens ngrok so the
microphone page is served over HTTPS. Open `https://<ngrok-host>/call`, press
**Call**, allow the mic. Hang up with the same button.

The page connects to same-origin `wss://<host>/ws/demo`: same pipeline as a
scored call, no submissions to Prosper. On this machine only,
`make -C backend run` and [http://localhost:7860/call](http://localhost:7860/call)
also work (`localhost` counts as a secure origin). From a phone or another
device you need the ngrok URL. See [`backend/README.md`](backend/README.md).

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

## Frontend

The `frontend/` directory is reserved for a future operator UI and is not
implemented here. No empty scaffold is committed.
