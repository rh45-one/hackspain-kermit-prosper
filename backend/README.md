# Prosper voice agent — backend

The complete Python runtime for the HackSpain 2026 Prosper track: a FastAPI
WebSocket server that answers Prosper harness calls, a pipecat voice pipeline,
a deterministic clinic + scheduling core, an LLM brain with guarded tools, and
a jury-facing ops console.

All commands in this README run **from `backend/`**. From the repository root,
prefix them with `uv run --project backend …` (see the root
[`README.md`](../README.md)).

## Environment

```sh
uv sync                 # install deps into backend/.venv
cp .env.example .env    # then edit .env
```

`.env` is read from the backend directory regardless of the working directory
and is git-ignored. Never commit it.

| Variable | Required | Purpose |
|---|---|---|
| `PROSPER_API_BASE_URL` | yes | Prosper platform host handed out at the desk. |
| `PROSPER_API_KEY` | yes | Team `pk-…` key. Sent as `X-Api-Key`; invalid keys return `403`. |
| `HELMCODE_API_KEY` | yes | LLM brain key (`sk-hke_…`, OpenAI-compatible). |
| `HELMCODE_BASE_URL` | yes | Defaults to `https://api.helmcode.com/v1`. |
| `AGENT_MODEL` / `AGENT_MODEL_FALLBACK` | no | Brain model and fallback; pin these for a run. |
| `DEEPGRAM_API_KEY` | yes | STT (Deepgram `nova-3`, `multi`). |
| `ELEVENLABS_API_KEY` / `ELEVENLABS_VOICE_ID` | yes | TTS (turbo v2.5, multilingual). |
| `CARTESIA_API_KEY` | no | TTS fallback. |
| `VOICE_WS_HOST` / `VOICE_WS_PORT` | no | Voice socket bind address (default `0.0.0.0:7860`). |
| `OPS_HTTP_PORT` | no | Ops console port (default `7861`). |
| `CALLER_TZ`, `MAX_CALL_MINUTES`, `SUBMIT_WINDOW_SECONDS` | no | Behaviour knobs. |
| `DATA_DIR` | no | Runtime data root; relative values resolve to `backend/data`. |
| `LOG_LEVEL` | no | Loguru level. |
| `PUBLIC_WS_URL` | for `make check-ws` | The tunneled endpoint, e.g. `wss://<domain>.ngrok-free.app/ws`. |

Credentials come from the Prosper registration desk and are shown once; see
[`docs/prosper/quickstart.md`](../docs/prosper/quickstart.md). Rotate a lost key
at the desk.

## Run

```sh
make run                 # voice server: ws://0.0.0.0:7860/ws
make ops                 # ops console: http://localhost:7861/ops
```

Equivalent direct invocations:

```sh
uv run python -m agent.voice.server
uv run uvicorn agent.ops.console:app --port "${OPS_HTTP_PORT:-7861}"
```

Both servers are stateless at boot except for one optional outbound call: the
clinic catalogue is warmed from the Prosper API only when `PROSPER_API_KEY` is
set, so an offline host never touches the network. Without the key the agent
runs in degraded/offline mode and skips the warm call.

The voice server binds to every IPv4 interface by default. From another device
on the same network, use `http://<server-lan-ip>:7860/call` and
`ws://<server-lan-ip>:7860/ws`. Browser microphone access on a LAN IP requires
HTTPS; use the deployed host or ngrok for an actual browser call.

### Endpoints

| Endpoint | Server | Purpose |
|---|---|---|
| `GET /healthz` | voice server | Liveness; returns `{"status":"ok"}`. |
| `WS /ws` | voice server | One scored Twilio Media Streams call per connection. |
| `GET /call` | voice server | Browser microphone simulator. |
| `WS /ws/demo` | voice server | Non-submitting browser call pipeline. |
| `GET /ops` | ops console | Live call timeline, transcripts, actions. |
| `GET /ops/api/calls[?]` | ops console | JSON view over `data/calls/*.jsonl`. |
| `GET /ops/api/reflow` | ops console | JSON view over the reflow queue. |

## Test, lint and smoke checks

```sh
make test                # uv run pytest -q
make lint                # uv run ruff check src tests

# Import + health smoke test (no credentials, no network).
uv run python -c "from fastapi.testclient import TestClient; \
from agent.voice.server import app; print(TestClient(app).get('/healthz').json())"
```

The test suite is offline: it patches out every external service. Run it from
the repository root with `uv run --project backend pytest -q` for the same
result.

## Tunnel

The harness dials a public `wss://` endpoint, so `localhost` is unreachable.

```sh
make run       # keep this terminal open; starts the local upstream
```

In a second terminal:

```sh
make tunnel
```

Or use one terminal for both processes:

```sh
make public
```

`make public` reuses a healthy local voice server when one exists; otherwise it
starts one, waits for `/healthz`, then opens ngrok. Press Ctrl-C to close the
tunnel and any server it started itself.

On an ngrok Free plan, `make tunnel` prints a temporary public HTTPS URL. Copy
its `wss://.../ws` form into `PUBLIC_WS_URL` and the Prosper dashboard. The URL
changes whenever the tunnel restarts. If your account has a claimed static
domain, add it to `ops/ngrok-domain.txt`; the same target then uses that domain.
ngrok now selects the lowest-latency region automatically. The target verifies
the local health endpoint first, avoiding a public 502 when the backend is off.

Then set the endpoint on the dashboard **Settings → Integration** page (the
desk does not ask for it): the `wss://` URL **with the `/ws` path**. Smoke-test
the tunnel before a run:

```sh
printf 'PUBLIC_WS_URL=wss://your-current-ngrok-host/ws\n' >> .env
make check-ws
```

## Local simulator (no harness)

Open `http://localhost:7860/call` after `make run`, press **Call**, and allow
microphone access. Press the same button to hang up. The page exchanges the
Twilio Media Streams format with the real agent pipeline, but browser demo
calls are retained only in the local audit and never submitted to Prosper.

Microphone access requires `localhost` or HTTPS. The deployed page is available
at `https://<host>/call` and connects to same-origin `wss://<host>/ws/demo`.

The scripted WAV simulator remains available:

```sh
uv run python ops/simulate_call.py --audio tests/fixtures/hello.wav
```

Replays the harness wire format against the local socket and writes the agent
reply audio to `/tmp/agent_reply.raw` (8 kHz µ-law).

## Data and privacy

Runtime artifacts live under `backend/data/`:

- `data/calls/<call_id>.jsonl` — per-call audit trail (transcript, tool calls,
  actions). Treated as caller PII; git-ignored.
- `data/reflow/` — ClinicReflow queue shared with the optimizer.

Call data and recordings must not be committed. The root `.gitignore` excludes
`backend/data/calls/*`, `backend/data/reflow/*` and common audio extensions.
