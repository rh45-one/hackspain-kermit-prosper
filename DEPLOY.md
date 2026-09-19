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

---

# Desplegar el frontend

El panel es Next.js y su única salida a red es **desde el servidor**, no desde
el navegador: `app/api/live/[...path]` y `app/api/frontdesk/[resource]` hacen de
proxy y añaden la cabecera `X-Ops-Token`. Por eso el token vive en el entorno
del proceso Next y **nunca lleva prefijo `NEXT_PUBLIC_`**: si lo llevara,
acabaría en el paquete que descarga el navegador y cualquiera tendría la llave
de `/ops`.

## Vercel, que es lo que encaja

```sh
cd frontend
npx vercel --prod
```

Variables, las tres, como **entorno de servidor**:

```
AGENT_HTTP_BASE_URL = https://prosper-clinicreflow.fly.dev
OPS_TOKEN           = <el mismo secreto que en Fly>
FRONTDESK_DEMO      = false
```

`FRONTDESK_DEMO=true` levanta el panel con datos inventados y sin backend. Sirve
para enseñarlo sin exponer nada; con `false` manda el agente real.

## La alternativa: una segunda app de Fly

Si no quieres una cuenta más, `frontend/` puede ir como otra app de Fly con su
propio Dockerfile de Node. Son dos apps, no una: la máquina del agente corre
Python y no debe compartir proceso con nada.

## Antes de dar la URL a nadie

1. `/en-vivo` es la vista de producto y la que funciona.
2. `/calls`, `/patients`, `/calendar` y `/directory` son el panel anterior.
   Su endpoint existe desde hoy, pero la navegación mezcla los dos mundos.
3. `/leaderboard` son datos inventados, siempre, con cualquier configuración.
4. El panel no enseña DNI ni teléfono de ningún paciente. Es deliberado y hay
   un test que lo fija; si alguien "lo arregla" para que se vean, ha roto algo.
