# Plan del evaluador / tester / benchmark

Estado y próximos pasos del paquete `evaluator/`. Todo lo de este documento se
implementa **dentro de `evaluator/`**: no importa código de `backend/`, no lee
`backend/.env`, y habla con el agente solo por el contrato del cable
(WebSocket de voz + receptor de submissions).

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
| Comparación de alternativas (A/B) | **Pendiente** | ver F-C |

Suite: `uv run --project evaluator --locked pytest -c evaluator/pyproject.toml evaluator/tests -q`
→ 288 passed, 1 skipped. Lint: `ruff check evaluator/src evaluator/tests`.

Defecto externo conocido: el backend de `main` no procesa el audio del caller
(solo transcribe fragmentos), así que una llamada real termina en el fallback
`NO_ACTION/out_of_scope`. El tester lo detecta y lo declara como falla del
lado del agente. Repararlo requiere tocar `backend/`, fuera de este paquete.

## F-C — comparación de alternativas

| Pieza | Estado |
|---|---|
| **Espera de readiness**: un candidato lanzado con `start_command` se sondea con `wait_until_listening` (socket TCP, en `runner/experiment.py`, también usado por el adaptador de texto) hasta que acepta la conexión; si no levanta, sus casos salen `invalid_evaluation` con la causa y el resto de las alternativas conserva su evidencia | **Hecho** |
| **Intercalado**: el candidato varía más rápido, para que un backend que deriva no favorezca al que va último | **Hecho** (`runner/experiment.case_plan`) |
| **Side-by-side por caso entre candidatos de un mismo run** con marca de desacuerdos y totales | **Hecho** (`report/side_by_side.py`, `cli.py compare`) |
| **Pareo entre runs**: el caso A de un run contra el caso B de otro (hoy `diff` compara el mismo candidato entre dos runs) | Pendiente |
| **Matriz declarativa**: azúcar para declarar variantes de entorno sin escribir cada candidato a mano | Pendiente |

Criterio de aceptación (cumplido en lo hecho): dos alternativas vivas corren en
un solo experimento, los primeros casos no se pierden por carrera, y el reporte
muestra cada caso con sus resultados en columnas contiguas.

## Métricas de ejecución

Regla de oro: **cada métrica declara de dónde sale y de quién es la culpa.**
Ningún agregado mezcla fallas del rig con fallas del modelo, y un dato que no
existe se muestra como `n/d`, nunca como `0`.

### Ya medidas por caso (`models.CaseResult`)

`verdict` (pass / fail / invalid_evaluation) · `failure_signal`
(missing_record / record_mismatch / transcript_leak) · `categories`
(atribución) · `matched_outcome` y `field_diffs` · `submitted` y
`submit_attempts` (con código HTTP) · `transcript` · `turn_latencies_ms` ·
`first_audio_ms` · `cost` y `usage` · `audio` (rutas WAV) · `interrupts`
(barge-in) · `duration_s` · `errors`.

### Agregados a añadir

| Métrica | Definición | Fuente | Estado |
|---|---|---|---|
| Terminó sin errores | casos sin `errors` y con veredicto válido / casos totales | `CaseResult` | falta el agregado |
| Errores por tipo | transporte, timeout de submission, TTS del tester, tool del agente | `errors`, `submit_attempts` | falta |
| Turnos por llamada | turnos del caller y respuestas del agente; turnos sin respuesta | `transcript`, `frames_sent/received` | falta |
| Primera respuesta | p50/p95 de `first_audio_ms` | `CaseResult` | falta (hoy solo se agrega por turno) |
| Latencia por turno | p50/p95 (ya) + dispersión entre repeticiones | `turn_latencies_ms` | parcial |
| Interrupciones | nº de barge-ins y **si el agente retomó** después | `interrupts` + audio posterior | parcial |
| Submissions | aceptadas, rechazadas por código (404/409/410/422) y motivo | `submit_attempts` | parcial |
| Acciones vacías | llamadas que terminan sin acción y **por qué** | `empty_action_reason` si el agente lo expone | `n/d` en `main` |
| Audio | segundos enviados/recibidos por llamada y relación caller/agente | evidencia del harness | falta |
| Coste | por llamada (ya) + total por candidato y por run | `usage_url` | parcial |
| Estabilidad | tasa de cambio de veredicto entre repeticiones | `CaseResult` por repetición | falta |

### Resultado de la llamada: cuatro clases, no dos

`pass` · `fail` (del modelo) · `invalid_evaluation` (del rig) ·
`agent_input_failure` (**nuevo**: el tester envió voz del caller y el agente no
registró transcript). Ninguna métrica agregada puede contar
`agent_input_failure` como fallo del modelo: sin eso, una entrada rota baja el
score de un modelo que nunca escuchó la pregunta.

### Dónde se ven

- `report.html`: tabla por candidato y matriz por problema (ya) + columnas
  nuevas: errores, turnos, primera respuesta, estabilidad.
- `metrics.json` por run (nuevo): el mismo contenido en formato máquina, para
  A/B y para el `diff`.
- CLI: `evaluator.cli metrics <run>` (nuevo) y deltas de métricas en
  `diff` (extender lo existente).

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
- Sin PII ni transcripciones versionadas: los resultados y WAV viven bajo
  `evaluator/experiments/results/`, ignorado por Git.
- Las métricas describen el agente observado por el cable; no certifican
  equivalencia con el evaluador oficial de la plataforma.
