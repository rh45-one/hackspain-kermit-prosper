# Feature: laboratorio de evaluación del agente Prosper

Plan de referencia: `evaluator/DEVELOPMENT_PLAN.md` (261 líneas, base `767cc7f`).
Propietario del contrato: el lead. Alcance de escritura: `evaluator/**` y este
fichero. `backend/**` y `frontend/**` son solo lectura.

## Base verificada (esta sesión)

- Suite completa: **418 passed, 1 skipped**, 314 s. Ruff: `All checks passed!`.
- El skip es un chequeo opt-in de módulo (`tests/test_agent_main_contract.py:32`,
  requiere `PYTHONPATH=backend/src`), no un fallo.
- Sin mutaciones fuera de `evaluator/`. Baseline reproducible.

## Contratos congelados del backend (verificados, no supuestos)

Fuente: reconocimiento read-only de `backend/` con `file:line`. El launcher de
los perfiles se fija contra esto, no contra suposiciones.

| Hecho | Valor | Evidencia |
| --- | --- | --- |
| Arranque app completa (voz + ops, un puerto) | `uv run --project backend python -m agent.serve` | `backend/src/agent/serve.py:29-30` |
| Arranque servidor de voz (dev) | `python -m agent.voice.server` | `backend/src/agent/voice/server.py:113-116` |
| Motor | env `VOICE_ENGINE` ∈ {`cascade`, `gemini_live`}, default `cascade`, validado fail-fast | `backend/src/agent/config.py:45,91-97` |
| Puerto de voz | env `VOICE_WS_PORT`, **default `7860` = producción** | `backend/src/agent/config.py:77` |
| Host | env `VOICE_WS_HOST`, default `0.0.0.0` | `backend/src/agent/config.py:76` |
| Puerto ops | env `OPS_HTTP_PORT`, default `7861` | `backend/src/agent/config.py:78` |
| Readiness | `GET /healthz` → `{"status":"ok"}` | `backend/src/agent/voice/server.py:62-64` |
| Ruta de texto | `POST /turns` `{call_id, text\|event}` → `{reply, ended}` | `backend/src/agent/ops/turns.py:474-491` |
| Montaje de `/turns` | solo si `TURNS_ADAPTER` ∈ {1,true,yes,on}; además exige loopback u `OPS_TOKEN` | `backend/src/agent/ops/turns.py:58,139-142,501-506` |
| Cierre de ventana | `{"event":"hangup"}` (flushea antes de responder) o `POST /turns/{call_id}/close` | `backend/src/agent/ops/turns.py:477-498` |
| Errores de `/turns` | 504 por timeout de turno (90 s), 500 por defecto del adaptador; nunca 200 con disculpa | `backend/src/agent/ops/turns.py:80,486-490` |
| Audit por llamada | `<DATA_DIR>/calls/<call_id>.jsonl`, claves `ts`, `event`, `data` | `backend/src/agent/voice/context.py:75-78,115-120` |
| Eventos de audit | `engine_selected`, `transcript{role,text}`, `action_queued`, `submitted`, `submit_failed`, `call_ended{reason,elapsed_s}` | `voice/pipeline.py:179`, `voice/context.py:130`, `brain/tools.py:1076`, `voice/flush.py:33-86` |
| Grabaciones | **no existe escritor de WAV en el backend** (`add_wav_header=False`) | `backend/src/agent/voice/pipeline.py:154` |
| `DATA_DIR` | default `./data` anclado a `backend/` | `backend/src/agent/config.py:99-108` |

**Producción prohibida:** `7860` es la instancia con ngrok registrado en el panel
y atiende llamadas puntuadas (`backend/README.md:150-151`). El laboratorio nunca
la usa ni la reinicia. El template de banco del backend usa `17999`.

## Hallazgos que corrigen el plan

1. **`POST /turns` ya existe** en el árbol de trabajo (`backend/src/agent/ops/turns.py`).
   El plan lo daba por pendiente del agente del backend. P0 no debe especular:
   integra contra este contrato y lo prueba contra el doble existente.
2. **No hay grabaciones de llamadas reales.** Sin escritor de WAV en el backend,
   el histórico real mostrará «audio no disponible» de forma sistemática. La
   cobertura de audio debe modelarse como capacidad declarada del perfil y como
   dato ausente por llamada, nunca como silencio ni como cero.
3. **Fuga de credenciales ya presente.** `GET /api/runs/{run_id}` devuelve el
   manifiesto crudo y `candidates[].env` sobrevive a la serialización
   (`experiment.py:846` solo excluye `start_command`); `api/app.py:101-110`.
   Ejemplo real en `experiments/agent-local.yaml:31`. Es criterio de P0.
4. **La prueba manual acepta superficie arbitraria del navegador.**
   `api/chat.py:289-303` toma `ws_url`, `clinic_url`, `scenario` (ruta de fichero
   del servidor) y `agent_audit_dir` del cuerpo POST. No ejecuta shell, pero sí
   permite al navegador elegir destino y leer rutas del servidor. P0 lo cierra
   con IDs de perfil predefinidos en el servidor.
5. **Sin deduplicación en el observador.** Cada `observe()` reimporta todos los
   `.jsonl` y crea un run nuevo (`observer/run.py:130-194`). P1 necesita índice
   idempotente; hoy no existe.
6. **Sin campo de versión en artefactos.** No hay `schema_version` en
   `manifest.json` ni en `cases.jsonl`; la compatibilidad actual depende de
   defaults de pydantic (`models.py:326-333`). P0 añade versión explícita y
   lectura tolerante, sin romper lo viejo.

## P0 — Contratos de evidencia y perfiles (activo)

Resultado observable: un run antiguo se lee igual que antes; un perfil
incompleto no arranca y dice qué falta; el laboratorio se niega a usar 7860 o
un destino oficial; ninguna respuesta de API ni manifiesto contiene valores de
credenciales; el navegador no puede elegir rutas ni comandos.

- [ ] **P0.1** Esquema declarativo de perfil: `id`, `engine`, `version`,
      endpoints (`ws_url`, `text_url`, `usage_url`), capacidades (texto, voz,
      audio, coste, transcripción), referencias a variables de entorno por
      **nombre**, metadatos de proveedor. Validación que nombra cada campo
      faltante. `start_command` es propiedad del servidor, jamás del navegador.
- [ ] **P0.2** Catálogo de perfiles iniciales `gemini_live` y `cascade` contra el
      contrato congelado de arriba, más guarda de laboratorio: rechazo de
      `7860`, de destinos oficiales y de puertos ocupados, con mensaje explícito.
- [ ] **P0.3** Esquema común de llamada y eventos: origen (real, simulado,
      manual), candidato y versión, tiempos, disponibilidad de evidencia
      (audio/transcript/coste/resultado), vínculos a run y caso. Transcripción
      como **eventos ordenados con timestamp y rol**; sin inventar turnos donde
      el origen solo da fragmentos. `schema_version` explícito y lectura de
      artefactos antiguos sin migración manual.
- [ ] **P0.4** Endurecimiento de `api/`: redacción de `env` y de cualquier valor
      sensible en respuestas, manifiestos y errores; la prueba manual y los
      experimentos se piden por ID de perfil, no por URL ni ruta; los errores
      públicos no revelan claves ni rutas internas.
- [ ] **P0.5** Tests de contrato de P0: carga de artefactos antiguos, detección
      de perfiles incompletos, rechazo de 7860 y de destinos oficiales, ausencia
      de credenciales en toda respuesta, aislamiento entre sesiones. Todo
      offline, sin proveedores pagados.

Comandos de validación de P0:

```sh
uv run --project evaluator --locked ruff check evaluator/src evaluator/tests
uv run --project evaluator --locked pytest -c evaluator/pyproject.toml evaluator/tests -q
uv run --project evaluator python -m evaluator.cli run --config evaluator/experiments/smoke-text.yaml
```

## Backlog P1–P5 (no iniciado)

- **P1** — histórico indexado e idempotente, transcript en orden, audio
  descubierto o «no disponible», filtros y paginación, agregados por periodo
  con percentiles desde muestras, éxito solo sobre llamadas evaluadas, coste
  con cobertura y moneda, separación de dobles y modelos reales.
- **P2** — especificación validada de experimento, ciclo de trabajo persistente
  con cancelación, evidencia parcial conservada, hashes de dataset y
  escenarios, readiness y limpieza de procesos huérfanos, límites sin prometer
  tope monetario exacto.
- **P3** — catálogo de personas, versionado de prompt/modelo/temperatura/semilla,
  fallbacks visibles, validación de cumplimiento de hechos, circuito de voz
  reactivo, comparación pareada con tamaño de muestra.
- **P4** — selector de perfil con preflight, audio continuo bidireccional,
  cancelación de reproducción al interrumpir, sesión guardada en el histórico.
- **P5** — pantallas sobre contratos estables, tests de integración, smoke con
  dobles, revisión visual, README de arranque único.

## Decisiones abiertas (no bloquean P0)

- Presupuesto de ejecuciones reales: hoy se valida con dobles; los perfiles
  reales quedan configurables pero no se lanzan campañas pagadas.
- Grabaciones históricas: el backend no las escribe; hay que decidir formato y
  ubicación antes de conectarlas. Nunca fabricar audio.
- Catálogo y cuotas efectivas de Helmcode; qué credenciales de STT/TTS existen.
- Modelo de escritura para P1/P2: en serie en el árbol actual o en worktrees
  Orca. Los documentos del plan están sin commitear, así que un worktree creado
  desde `HEAD` no los vería; paralelizar exige decidir antes qué se commitea.

## Riesgos

- Confundir un verde local con un punto en el panel: el dataset de la clínica es
  una miniatura inventada. Debe quedar impreso en el informe, no solo en README.
- Prometer límite monetario con telemetría incompleta.
- Trabajar contra un destino oficial por accidente: guarda en P0.2.
