# Plan del evaluador / tester / benchmark

Estado y próximos pasos del paquete `evaluator/`. Todo lo de este documento se
implementa **dentro de `evaluator/`**: no importa código de `backend/`, no lee
`backend/.env`, y habla con el agente solo por el contrato del cable
(WebSocket de voz + receptor de submissions). La única lectura del backend es
el **audit de llamadas** (`DATA_DIR/calls/*.jsonl`), en modo observador y sin
modificarlo.

## Estado actual (verificado)

| Pieza | Estado | Evidencia |
|---|---|---|
| Contrato de submissions (rutas, campos, vocabulario cerrado) | Listo | `tests/test_submit_vocabulary.py`, siempre activo, sin `backend/` |
| Contrato opt-in con el agente del mismo checkout | Listo y fail-closed | `tests/test_agent_main_contract.py`: skip explícito si falta la fuente, error de colección si está rota |
| STT pluggable (`deepgram` \| `openai-compat` \| `none`) | Listo | `harness/stt.py`; Deepgram confirmado contra el servicio real |
| Sesión dúplex (`enviar` / `escuchar` / `cerrar`) y `dial()` encima | Listo | `harness/wsclient.py`, `tests/test_chat_session.py` |
| Tester de chat manual (`cli.py chat`) | Listo | Verificado contra el WS real del backend de `main` |
| Diagnóstico "el agente no escuchó al caller" | Listo | `harness/agent_audit.py` (lectura opcional del audit del agente) |
| Benchmark con dobles y escenarios | Listo | `cli.py run`, `experiments/smoke.yaml` |
| Comparación de alternativas (A/B) | Listo | espera de readiness, intercalado y `cli.py compare` |
| Pareo entre corridas y entre candidatos | Listo | `cli.py diff --candidate-a/--candidate-b`, `/api/diff?candidate_a=&candidate_b=` |
| Matriz declarativa de variantes de entorno | Listo | `CandidateConfig.variants`, `expand_candidates`, `tests/test_runner_extras.py::TestVariantMatrix` |
| Métricas agregadas de una corrida | Listo | `report/metrics.py`, `metrics.json` por corrida, `cli.py metrics` |
| API read-only + chat en vivo | Listo | `api/app.py`, `api/chat.py`, `cli.py dev` |
| Consola de developer (estática, sin build ni CDN) | Listo | `web/`, servida por `cli.py dev`, con fuentes locales en `web/fonts/` |
| Observador post-hoc de las llamadas reales del backend | Listo | `observer/`, `cli.py observe`, pestaña «Llamadas reales», `/api/runs/{id}/real-calls` |
| Chat con micrófono en la consola (push-to-talk) | Listo | `web/mic-worklet.js` + `web/app.js` + `POST /api/chat/{sid}/say-audio` |
| Lanzar corridas desde la consola | Pendiente y deliberadamente fuera | la API es read-only: una consola que reescribe su benchmark no es confiable |

Suite: `uv run --project evaluator --locked pytest -c evaluator/pyproject.toml evaluator/tests -q`
→ 400+ passed, 1 skipped. Lint: `ruff check evaluator/src evaluator/tests`.

Defecto externo conocido: el backend de `main` no procesa el audio del caller
(solo transcribe fragmentos), así que una llamada real termina en el fallback
`NO_ACTION/out_of_scope`. El tester lo detecta y lo declara como falla del
lado del agente. Repararlo requiere tocar `backend/`, fuera de este paquete.

## Seguimiento de esta iteración

Todo lo de esta lista quedó dentro de `evaluator/` (no se tocó `backend/` ni la
raíz del repositorio):

| # | Tarea | Estado | Evidencia |
|---|---|---|---|
| 1 | Observador post-hoc de las llamadas reales | listo | `observer/`, `tests/test_observer.py`, `cli.py observe` |
| 2 | Métricas pendientes (errores por tipo, audio, barge-ins, `metrics.json`, `cli metrics`, deltas en `diff`) | listo | `report/metrics.py`, `tests/test_metrics.py`, `tests/test_runner_metrics.py` |
| 3 | Pareo entre corridas y candidatos en `diff` (+ API) | listo | `report/diff.py`, `tests/test_diff.py::TestCandidatePairing` |
| 4 | Matriz declarativa de variantes de entorno | listo | `models.expand_candidates`, `tests/test_runner_extras.py::TestVariantMatrix` |
| 5 | Rediseño de la consola web (ClinicReflow, fuentes locales, sin CDN, pestaña de llamadas reales) | listo | `web/index.html`, `web/styles.css`, `web/app.js`, `web/fonts/` |
| 6 | Rediseño del `report.html` a la guía | listo | `report/render.py` (CSS propio, autocontenido) |
| 7 | Micrófono push-to-talk en la consola | listo | `web/mic-worklet.js`, `api/chat.py` (`say-audio`), `tests/test_api_chat.py` |
| 8 | Documentación al día | listo | `README.md`, este `PLAN.md` |
| 9 | Verificación completa | listo | 418 passed, 1 skipped; `ruff` sin hallazgos |

## Observador post-hoc: las llamadas que el backend ya hizo

Implementado (`observer/backend_calls.py`, `observer/run.py`):

- **Fuente**: `DATA_DIR/calls/<call_id>.jsonl` (o el `DATA_DIR`; el loader
  acepta ambos). Se toleran líneas corruptas o a medio escribir: el backend
  appendea mientras la llamada está viva.
- **Reconstrucción**: transcript de caller y agente, `identity_confirmed`,
  acciones encoladas (`action_queued`) **con su payload completo**, flush de
  submissions, motor, duración y cierre.
- **Puntuación**: sólo las llamadas etiquetadas en un mapa de oráculos
  (`call_id` o prefijo inequívoco → escenario) se puntúan, con el mismo
  `compare` + normalización + `forbidden_actions` del banco, y con la
  comprobación de fuga del problema 14 (el audit trae transcript del agente).
- **Honestidad**: sin etiqueta no hay veredicto. La llamada queda como
  evidencia (`real_calls.jsonl`, informe y pestaña propia) con la acción
  enviada, la identidad y el transcript plegado. Una llamada sin cierre
  registrado es `invalid_evaluation`, no un fallo del agente.
- **Salida**: una corrida normal (`manifest.json`, `cases.jsonl`,
  `metrics.json`, `report.html` + `real_calls.jsonl`), así que `metrics`,
  `diff`, la API y la consola la consumen sin casos especiales.

Límites del observador: no hay audio ni latencias del cable (el audit no las
tiene), el veredicto depende de que el mapa sea correcto, y una llamada real
puede no corresponder a ningún escenario del banco (esas son las
informativas).

## F-C — comparación de alternativas

Implementado: espera de readiness, intercalado de candidatos, side-by-side por
caso entre alternativas (`cli.py compare`, `/api/runs/{id}/compare`), pareo de
candidatos entre corridas (`cli.py diff --candidate-a --candidate-b`) y matriz
declarativa de variantes de entorno (el runner expande una entrada en un
candidato por variante, `manifest.json` incluido).

## Consola de developer

Implementado: API read-only sobre las corridas, chat en vivo contra el agente
tipeado o hablado, observador en su pestaña, y una consola estática servida por
el propio evaluador (`cli.py dev`) con el lenguaje visual ClinicReflow
(papel/tinta/latón/brasa), tipografías Inter e Inter Tight servidas localmente y
sin CDN. El detalle y el contrato de endpoints están en `README.md`.

Pendiente:

- **Lanzar corridas**: descartado a propósito. Si se agrega, tiene que ser sobre
  una lista blanca de configuraciones, nunca un comando arbitrario.
- **Acciones vacías (`empty_action_reason`)**: el agente de `main` no expone por
  qué terminó sin acción; la métrica queda `n/d` en vez de inventar un motivo.

## Métricas de ejecución

Regla de oro: **cada métrica declara de dónde sale y de quién es la culpa.**
Ningún agregado mezcla fallas del rig con fallas del modelo, y un dato que no
existe se muestra como `n/d`, nunca como `0`.

### Ya medidas por caso (`models.CaseResult`)

`verdict` (pass / fail / invalid_evaluation) · `failure_signal`
(missing_record / record_mismatch / transcript_leak) · `categories`
(atribución) · `matched_outcome` y `field_diffs` · `submitted` y
`submit_attempts` (con código HTTP) · `transcript` · `turn_latencies_ms` ·
`first_audio_ms` · `cost` y `usage` · `audio` (rutas WAV) y **segundos por
dirección** (`caller_audio_s`, `agent_audio_s`) · `frames_sent` /
`frames_received` · `interrupts` (barge-in) · `duration_s` · `errors`.

### Agregados (`report/metrics.py`)

| Métrica | Definición | Fuente | Estado |
|---|---|---|---|
| Terminó sin errores | casos sin `errors` / casos totales | `CaseResult` | listo |
| Errores por tipo | transporte, timeout, TTS, adaptador de texto, clínica, submission, STT, other — con conteo y casos con error | `errors` | listo |
| Turnos por llamada | mediana de `turn_latencies_ms` por caso | `CaseResult` | listo |
| Primera respuesta | p50/p95 de `first_audio_ms` | `CaseResult` | listo |
| Latencia por turno | p50/p95 | `turn_latencies_ms` | listo |
| Interrupciones | nº de barge-ins y llamadas con barge-in | `interrupts` | listo |
| Submissions | aceptadas y rechazadas por código (404/409/410/422) | `submit_attempts` | listo |
| Audio | segundos enviados/recibidos por candidato y relación caller/agente | `caller_audio_s`, `agent_audio_s` | listo |
| Coste | total por candidato (por llamada ya) y `n/d` si el candidato no expone `usage_url` | `usage_url` | listo |
| Estabilidad | tasa de acuerdo con el veredicto mayoritario por escenario | `CaseResult` por repetición | listo |
| Acciones vacías | llamadas que terminan sin acción y **por qué** | `empty_action_reason` si el agente lo expone | `n/d` en `main` |
| Dispersión entre repeticiones | además de estabilidad, spread de latencias | `turn_latencies_ms` por repetición | pendiente |

### Dónde se ven

- `report.html`: tabla por candidato (con errores, turnos, audio y barge-ins),
  matriz por problema, estabilidad, detalle por caso y —si es una corrida del
  observador— la sección de llamadas reales.
- `metrics.json` por corrida: el mismo contenido en formato máquina, para A/B y
  para el `diff`.
- CLI: `evaluator.cli metrics <run>` (`--json` para máquina) y deltas de
  métricas en `diff`.

### Criterios de aceptación

1. Toda métrica agregada declara numerador y denominador, y cuántos casos
   quedaron afuera por datos faltantes.
2. Una corrida con falla de entrada del agente no baja el score del modelo.
3. Cada métrica nueva tiene test con fixture sintético; ninguno toca la red.
4. El coste sigue siendo `None` cuando el candidato no expone `usage_url`; el
   backend de `main` no lo expone, así que se reporta `n/d` (nunca `0`).

### Límites

- El audit del agente es **evidencia opcional** (`--agent-audit-dir`), no un
  contrato: si el layout cambia, la métrica queda en `n/d`.
- Sin PII ni transcripciones versionadas: los resultados, los WAV y los
  transcripts del observador viven bajo `evaluator/experiments/results/`,
  ignorado por Git.
- Las métricas describen el agente observado por el cable; no certifican
  equivalencia con el evaluador oficial de la plataforma.
