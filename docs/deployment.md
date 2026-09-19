# Deploying the backend for the hackathon

The harness needs one public, always-reachable `wss://` endpoint. The jury
needs one public `https://` console. Both read and write the same `DATA_DIR`,
so both run in **one process, on one machine, on one port**
(`backend/src/agent/serve.py`):

| URL | Purpose |
|---|---|
| `wss://<host>/ws` | voice WebSocket announced to the Prosper harness |
| `https://<host>/call` | browser microphone simulator (never submits actions) |
| `wss://<host>/ws/demo` | browser simulator WebSocket |
| `https://<host>/ops` | jury console |
| `https://<host>/healthz` | liveness |

Local development is unchanged: `make -C backend run` (7860) and
`make -C backend ops` (7861) still work as two processes.

## Recommendation: Fly.io, region `mad`

Chosen over the alternatives for three reasons that matter to this specific
workload:

1. **Madrid region.** Every millisecond on the audio path is round-tripped
   between the caller, Deepgram, the LLM and ElevenLabs. `mad` is the only
   cheap option physically next to the event.
2. **No scale-to-zero.** `min_machines_running = 1` and
   `auto_stop_machines = false`. This image imports pipecat, onnxruntime and
   numba; a cold start is seconds, and the call that pays it is the first call
   of the demo.
3. **Native WebSockets and a persistent volume**, so call JSONL survives a
   redeploy and the ops console keeps its history.

Cost: `shared-cpu-2x` / 2 GB running continuously is roughly **$0.02/h,
~$5 for a whole hackathon weekend** if left on. Stop the machine when done
(`fly scale count 0`) and it costs nothing but the volume.

### One-time setup

```sh
brew install flyctl && fly auth signup      # or: fly auth login
cd backend
fly launch --no-deploy --copy-config --name prosper-clinicreflow --region mad
fly volumes create prosper_data --region mad --size 1
make deploy-secrets                          # pushes backend/.env keys as secrets
make deploy
```

`fly launch` must not overwrite `fly.toml`; `--copy-config --no-deploy` keeps
the committed one. Verify before announcing the URL to the desk:

```sh
curl https://prosper-clinicreflow.fly.dev/healthz
wscat -c wss://prosper-clinicreflow.fly.dev/ws -x '{"event":"connected"}'
open https://prosper-clinicreflow.fly.dev/call
open https://prosper-clinicreflow.fly.dev/ops
fly logs
```

Then set `PUBLIC_WS_URL=wss://prosper-clinicreflow.fly.dev/ws` in
`backend/.env` and in the Prosper dashboard settings.

### Redeploy during the event

`make deploy` — about 40 s when only `src/` changed, because the dependency
layer is cached. **Never deploy while a judged call is running:** the machine
is replaced and the socket drops.

## Secrets

Secrets live only in `fly secrets` (`PROSPER_API_KEY`, `HELMCODE_API_KEY`,
`DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`, `CARTESIA_API_KEY`). They are never
baked into the image: `.dockerignore` excludes `.env`. Non-secret knobs are
plain `[env]` entries in `fly.toml`.

Call JSONL under `/data/calls` contains caller PII. The volume is wiped with
`fly volumes destroy prosper_data` after the event.

## Fallback: ngrok from a laptop (zero cost, zero deploy)

Already wired as `make -C backend tunnel` + `make -C backend run`. On ngrok
Free, the tunnel receives a random HTTPS URL at each start; copy its
`wss://.../ws` form to `PUBLIC_WS_URL` and the Prosper dashboard. An optional
`backend/ops/ngrok-domain.txt` supplies a claimed static domain for accounts
that support one. Keep ngrok as the contingency if the venue network blocks
outbound to Fly or a deploy breaks during judging. Its weakness is the venue
wifi: the tunnel dies with the laptop's connection, mid-call.

## Rejected alternatives

| Option | Why not |
|---|---|
| Render free tier | spins down when idle; the first call of the demo times out |
| Cloud Run | scale-to-zero cold start on a ~1 GB image; `min-instances=1` removes the cost advantage and the nearest region is still further than `mad` |
| Railway | works, WebSockets fine, but nearest region is Amsterdam and there is no Madrid option |
| Heroku / App Runner | more expensive for the same thing |

## Rollback

```sh
fly releases                 # list
fly deploy --image <prior>   # or: fly releases rollback
fly scale count 0            # stop paying, keep the volume
```
