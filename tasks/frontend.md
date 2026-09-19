# Tarea: conectar FrontDesk con el backend real

Lee primero `PROJECT_CONTEXT.md` en la raíz. Resume el hackathon entero.

## Qué es tuyo

- `frontend/**` — todo
- `backend/src/agent/ops/console.py` — **solo este fichero del backend**

**No toques nada más de `backend/`.** Hay otro agente trabajando en
`backend/src/agent/{brain,voice,clinic,scheduling}/` a la vez, y el servidor de
voz está atendiendo llamadas puntuadas ahora mismo.

## El problema

El panel está **muerto en modo live**. Auditado hoy:

- `frontend/app/api/frontdesk/[resource]/route.ts` llama a
  `${AGENT_HTTP_BASE_URL}/ops/api/frontdesk/{calls,clinic}`
- El ops console (`backend/src/agent/ops/console.py`) solo expone
  `/ops`, `/ops/api/calls`, `/ops/api/calls/{call_id}` y `/ops/api/reflow`
- No hay ni una ocurrencia de "frontdesk" en `backend/`

Y los formatos tampoco casan: el front espera objetos `LiveCall` con
`transcript`, `entities`, `diagnostic.submissions_succeeded/_failed`,
`fallback_action_added` (ver `frontend/lib/types.ts` y
`frontend/components/metrics/observatory-charts.tsx:296-300`). El backend
devuelve `{call_id, actions}`.

Con `FRONTDESK_DEMO=true` tira de mocks y se ve bien. En live da 404 permanente.

## Qué hacer

1. Implementa `/ops/api/frontdesk/calls` y `/ops/api/frontdesk/clinic` en
   `backend/src/agent/ops/console.py`, con la forma exacta que `frontend/lib/types.ts`
   ya espera. **El contrato lo manda el frontend; no lo cambies para que te
   encaje, adáptate tú.**
2. La fuente de datos son las trazas JSONL en `DATA_DIR/calls/*.jsonl` (una por
   llamada: eventos `transcript`, `tool`, `action_queued`, `call_ended`,
   `submitted`, `audio_bridge_metrics`). Para `clinic`, el cliente de la API de
   Prosper vive en `backend/src/agent/clinic/client.py` — **impórtalo, no lo
   reescribas**.
3. **Cuidado con el coste**: el front hace polling cada **3 segundos por
   pestaña abierta**, y el `/ops/api/calls` actual lee hasta 30 ficheros
   completos por petición. Haz la lectura barata o cachéala; si no, con el panel
   abierto le metes carga al proceso que atiende llamadas reales.
4. Arregla el README del frontend: apunta a `../integration/README.md`, que no
   existe.

## Verificación

```sh
cd backend && uv run pytest -q && uv run ruff check src tests   # tiene que quedar verde
cd frontend && npm run typecheck && npm run lint
```

Arranca el backend en un puerto **distinto del 7860** para probar, que el 7860
tiene el túnel registrado en Prosper y recibe llamadas puntuadas:

```sh
VOICE_WS_PORT=17999 uv run --project backend python -m agent.voice.server
AGENT_HTTP_BASE_URL=http://127.0.0.1:17999 npm --prefix frontend run dev
```

## Reglas

- `/leaderboard` es mock siempre, a propósito. Déjalo.
- Cero secretos en el frontend hoy. Que siga así: las claves viven en `backend/.env`.
- Solo lectura. Ninguna ruta `POST/PUT/DELETE` hacia el backend.
- Tests y lint verdes antes de cada commit. Commits solo de lo tuyo.
