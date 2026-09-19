# FrontDesk

Next.js App Router dashboard for the integrated Prosper agent.

```sh
npm install
cp .env.example .env.local
npm run dev
```

Open http://localhost:3001, which redirects to `/en-vivo`.

The live view needs an ops process reading the same `DATA_DIR` the voice
pipeline writes. Start it on its own port — **never 7860**, which is the voice
server that answers scored calls through the registered tunnel:

```sh
uv run --project backend uvicorn agent.ops.console:app --port 7861
```

- `AGENT_HTTP_BASE_URL`: server-side backend URL, default `http://127.0.0.1:7861`.
- `OPS_TOKEN`: shared secret for `/ops`, added to every request by the Next
  route handler. It stays in the server's environment; naming it
  `NEXT_PUBLIC_*` would ship it to the browser. Without `OPS_TOKEN` set the ops
  process serves loopback only, which is enough on a single machine.
- `FRONTDESK_DEMO=true`: opt into the original simulated data and local settings.
  Without this flag the dashboard uses only backend data, including in production.

The Next.js `/api/frontdesk/{calls,clinic}` handlers proxy read-only resources.
Provider keys remain in the backend. Calls refresh every three seconds, clinic
data every minute. Failures are displayed without replacing real data with mocks.
The calendar shows the clinic EHR; submissions do not mutate that EHR.

Prompt editing, knowledge uploads and manual takeover do not have backend write
APIs. The live UI disables them. Demo mode keeps the local mock interactions.

```sh
npm run lint
npm run typecheck
npm run build
npm run start
```

`typecheck` generates Next.js route types before invoking TypeScript. The demo
flag is read at request time, so changing it requires restarting the process but
does not require rebuilding.

## La vista en vivo, de punta a punta

`/en-vivo` muestra lo que el agente va haciendo en cada llamada mientras la
llamada pasa, escrito para alguien de recepción. Lee las trazas JSONL que el
pipeline de voz escribe en `DATA_DIR/calls/`, que crecen en directo.

Dos procesos, en este orden:

```sh
# 1. El lector de trazas. NUNCA en el 7860: ese es el servidor de voz que
#    atiende las llamadas puntuadas a través del túnel registrado en Prosper.
cd backend
DATA_DIR=./data OPS_TOKEN=un-secreto \
  uv run uvicorn agent.ops.console:app --port 7861

# 2. El panel.
cd frontend
AGENT_HTTP_BASE_URL=http://127.0.0.1:7861 OPS_TOKEN=un-secreto npm run dev
```

Abre http://localhost:3001.

- **`OPS_TOKEN`** es opcional en una sola máquina: sin él, `/ops` solo atiende a
  loopback y el panel funciona igual. En cuanto el lector deje de estar en
  `localhost`, es obligatorio, y una petición reenviada por un proxy nunca
  cuenta como loopback.
- El token lo añade el route handler de Next en `app/api/live/[...path]`, que
  corre en el servidor. Nunca lo renombres a `NEXT_PUBLIC_*`.
- `PROSPER_API_KEY` en el proceso del 7861 es opcional pero recomendable: sin
  ella el panel dice `PR10` y `norte` en vez de "Dra. Nuria Peral" y "Arenal
  Norte". El catálogo se pide una sola vez por proceso.

### Qué no puede enseñar, y por qué

- **El nombre solo aparece en las altas.** Es el único caso en que la traza lo
  guarda; en una reserva solo hay un `patient_id` y la API de la clínica no
  tiene búsqueda por ese id.
- **No hay número de teléfono.** El `from_number` de la traza sale siempre
  vacío: el contexto de la llamada nace antes de que llegue el evento `start`.
- **Los tipos de cita salen en inglés** ("Orthopaedic First Visit") porque el
  catálogo de Prosper está en inglés. Traducirlos aquí sería inventarlos.
- **El DNI, el teléfono y el correo no salen nunca**, ni del cuerpo de un alta
  ni de la transcripción, donde el paciente los dicta en voz alta.
