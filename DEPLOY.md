# Desplegar en Fly.io

Estado a 19 sep 2026, 19:40. `backend/` listo; falta ejecutar.

## Lo que ya está hecho

- `backend/fly.toml` — región `mad`, una máquina, siempre encendida, volumen en `/data`.
- `backend/Dockerfile` — `CMD python -m agent.serve`.
- `agent.serve` — **verificado funcionalmente**, no leyendo rutas: un puerto sirve
  `/ws`, `/ws/demo`, `/call`, `/healthz`, `/ops`, `/ops/api/calls`,
  `/ops/api/live/*` y `/ops/api/frontdesk/*`.
- `backend/ops/smoke.py` — comprueba salud, ops y un WebSocket real.

## Lo que falta, en orden

### 1. Entrar en Fly

```sh
flyctl auth login          # hoy: "no access token available"
```

### 2. Los secretos

**`OPS_TOKEN` es obligatorio.** Sin él la consola solo responde a loopback, así
que en un host desplegado no responde a nadie. Y con él, es lo único que separa
las transcripciones —donde el DNI y el teléfono que dicta un paciente están
literales— de cualquiera que tenga la URL.

```sh
cd backend
flyctl secrets set \
  PROSPER_API_KEY=...      \
  GEMINI_API_KEY=...       \
  TYPESAFE_API_KEY=...     \
  OPS_TOKEN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
```

`PROSPER_API_BASE_URL`, `GEMINI_LIVE_MODEL`, `VOICE_ENGINE=gemini_live` y
`CALLER_TZ` pueden ir en `[env]` de `fly.toml`: no son secretos.

**No pongas** `HELMCODE_API_KEY` ni `ELEVENLABS_VOICE_ID`: son marcadores de
posición (`REPLACE_ME`) y Helmcode devuelve 401. El camino de cascada no se usa.

### 3. Desplegar

```sh
flyctl deploy --remote-only --wait-timeout 600
```

### 4. Humo, antes de tocar el endpoint de la plataforma

```sh
OPS_TOKEN=<el mismo> uv run --with websockets python ops/smoke.py prosper-clinicreflow.fly.dev
```

Comprueba `/healthz`, que `/ops` **rechaza sin token** y responde con él, y que
el WebSocket acepta de verdad. Sin `OPS_TOKEN` en el entorno, un 200 en `/ops`
hace fallar el humo a propósito: significa que la puerta está abierta.

### 5. Cambiar el endpoint en Prosper

Solo **después** de que el humo pase, y **nunca con una llamada en vuelo**:

```sh
curl -s -H "X-Api-Key: $PROSPER_API_KEY" "$PROSPER_API_BASE_URL/api/v1/runs" \
  | python3 -c 'import json,sys; r=json.load(sys.stdin)["runs"][0]; print(r["mode"], r["status"])'
```

`completed` o `cancelled` para seguir. Si hay un run colgado:

```sh
curl -s -X POST -H "X-Api-Key: $PROSPER_API_KEY" \
  "$PROSPER_API_BASE_URL/api/v1/runs/<RUN_ID>/cancel"
```

Endpoint nuevo: `wss://prosper-clinicreflow.fly.dev/ws`.

## Riesgos

- **El túnel actual es el portátil de Ginés** (`retrain-hatching-stencil.ngrok-free.dev`
  → `localhost:7860`). Mientras sea ése, cerrar el portátil acaba el hackathon;
  y un reinicio a destiempo ya dejó un run colgado hoy.
- **`.github/workflows/ci.yml` está sin subir** a propósito: el token de GitHub
  no tiene permiso `workflow`, y ese CI despliega en cada push a `main`. Primero
  un despliegue manual verificado; el CI después.
- **`/docs` y `/openapi.json` quedan expuestos** en la app de voz (la consola de
  ops sí los desactiva). No filtran datos, pero publican la superficie entera.
- El volumen `/data` es de **una** máquina. Dos máquinas serían dos verdades
  sobre las mismas llamadas, y por eso `fly.toml` fija `min_machines_running = 1`
  sin escalado automático.
