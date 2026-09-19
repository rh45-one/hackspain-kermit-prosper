# evaluator — evaluador local del agente Prosper

Evaluador, tester y benchmark independiente para el agente de recepción de
Clínica Arenal (HackSpain 2026, track Prosper). El agente es un sistema
externo bajo prueba: este paquete controla las entradas, los datos y el
resultado esperado, y nunca le entrega los `accepted_outcomes`.

> **Resultado local.** El evaluador no es el juez oficial. Hasta validar su
> equivalencia con la plataforma, sus resultados son «resultado local».

## Qué contiene

| Pieza | Ruta | Qué hace |
| --- | --- | --- |
| Clínica local | `src/evaluator/clinic/` | API de lectura (`/api/v1/directory`, `/availability`, `/appointments`, catálogo) sobre un dataset versionado + receptor `/api/v1/submit/*` con la semántica del contrato: 404 call desconocida, 410 ventana cerrada (30 s), 409 reintento idéntico, 422 malformado (incluida la letra del DNI). Registra además los `attempts` por llamada para diagnóstico. |
| Llamador | `src/evaluator/harness/wsclient.py` | Cliente WebSocket que habla el formato Twilio Media Streams del contrato (camelCase, `sequenceNumber`/`chunk`/`timestamp` como strings, frames µ-law 20 ms). Mide latencia de respuesta por turno y primer audio, captura el audio en ambos sentidos y soporta barge-in (`interrupt_on_agent_audio`). |
| Audio/TTS | `src/evaluator/harness/audio.py`, `tts.py` | Codec µ-law↔PCM, WAV, mezcla de ruido con SNR, ruido sintético determinista; síntesis por subprocess (`espeak-ng`/`pico2wave`) con caché por texto. |
| Doble de prueba | `src/evaluator/harness/double_agent.py` | Agente mínimo que responde el wire format y envía acciones enlatadas vía `/control` **por call_id** (FIFO legacy sigue disponible). Expone `/usage/calls/{id}` con coste determinista para probar la telemetría. |
| Paciente simulado | `src/evaluator/simulator/patient.py`, `llm_patient.py` | Caller por reglas para el adaptador de texto: responde solo desde `caller.facts`, aplica `behavior` y nunca conoce el oráculo. `caller.llm` lo sustituye por un LLM restringido (endpoint OpenAI-compatible) con fallback automático a reglas. |
| Comparador | `src/evaluator/compare.py` | Veredicto binario: la lista de acciones grabadas debe coincidir con alguna `accepted_outcome` tras normalización, respetando `forbidden_actions`. Diagnóstico por campo, check de fuga (problema 14) y categorías de fallo del plan §14. |
| Normalización | `src/evaluator/normalize.py` | La tabla de tolerancia del scorer: DNI/NIE, nombres (NFKD, ñ→n), teléfonos, emails, slots en `Europe/Madrid` al minuto, enums. |
| Escenarios | `scenarios/**/*.yaml` | Casos versionados con esquema `caller`/`oracle`/`limits` del plan, `split` (development/holdout) y `leak_check`. |
| Experimentos | `experiments/*.yaml` | Candidatos (configuración del agente), set de escenarios, repeticiones. |
| Informe | `results/<run_id>/` | `manifest.json` (config + versión de reglas + hash del dataset), `cases.jsonl`, `report.html` con puntos locales por peso de problema, cobertura y latencias. |

## Quickstart

```sh
uv sync --project evaluator

# 1) Smoke test del propio evaluador (tres dobles: acierta / muta / calla)
uv run --project evaluator python -m evaluator.cli run \
    --config evaluator/experiments/smoke.yaml
# → evaluator/experiments/results/<run_id>/{manifest.json,cases.jsonl,report.html}
```

## Evaluar el agente real

El agente se apunta a la clínica local con su configuración habitual
(`PROSPER_API_BASE_URL`); el mismo base URL sirve clínica y submissions:

```sh
# terminal A — agente; el runner arranca la clínica local en 8090
PROSPER_API_BASE_URL=http://localhost:8090 \
PROSPER_API_KEY=pk-local-eval \
uv run --project backend python -m agent.serve

# terminal B — experimento (no arrancar otra clínica en 8090)
uv run --project evaluator python -m evaluator.cli run \
    --config evaluator/experiments/agent-local.yaml
```

Si el agente ya corre por su cuenta, basta `ws_url` en el candidato; si pones
`start_command`, el runner lo arranca él y espera el puerto. Cada candidato
del experimento es una configuración (modelo, prompts, proveedores) del
mismo agente — compara configuraciones con varios `candidates` +
`repetitions`.

La plantilla necesita escenarios con audio o `tts: true` y un TTS instalado
para una prueba de voz; los turnos solo de texto se convierten en silencio.
Consulta [la guía de integración](../integration/README.md) para pruebas de
contrato sin credenciales, FrontDesk y las limitaciones del reloj del agente.

## Formato de escenario

Esquema `caller`/`oracle`/`limits` del plan (§8):

```yaml
id: sb-001
problem_id: simple_booking        # familia del reto (ver pesos en models.PROBLEM_WEIGHTS)
version: 1
split: development                # development | holdout
language: es
clock: "2026-09-18T10:00:00+02:00"  # ancla para fechas relativas
clinic_fixture: seed-v1           # debe coincidir con meta.name del dataset
caller:
  persona: paciente_habitual
  from_number: "+34612345678"      # null = caller id oculto
  opening: "Buenos días, soy Marta…"   # primera línea del paciente simulado
  facts:                          # lo que el caller sabe y puede revelar
    name: "Marta Ruiz Gómez"
    national_id: "12345678Z"
    insurer: sanitas
    wants: "…"
  behavior:
    provide_identifier_when_asked: true
    accept_first_offer: true
    reveal_second_policy_when_asked: false
    corrections: []                # correcciones guionizadas ("No, he dicho…")
turns:                            # script para la vía de voz (WS)
  - text: "..."        # turno del caller (adaptador de texto / transcript)
    audio: turno1.ulaw # opcional: audio µ-law 8 kHz para la vía de voz
    tts: false         # true = sintetiza `text` con el TTS del experimento
    hold_ms: 2000
    noise:             # opcional: mezcla ruido sobre el audio del turno
      synth: brown     # o file: ruido.ulaw para un asset grabado
      snr_db: 5.0
    interrupt_on_agent_audio: false  # barge-in: el caller corta al oír al agente
oracle:                          # nunca se comparte con el agente
  accepted_outcomes:
    - actions:
        - action: BOOK
          patient_id: P00042
          ...
  forbidden_actions: [CANCEL]
  require_nonempty_submission: true
  leak_check:            # problema 14: comprobación de fuga en transcript
    national_id: "23456789D"
    phone: "622333444"
limits:
  max_call_seconds: 180
  max_turns: 24
```

Validar escenarios contra el fixture antes de un run:

```sh
uv run --project evaluator python -m evaluator.cli validate \
    --dataset evaluator/data/clinic_dataset.json \
    --scenarios 'evaluator/scenarios/**/*.yaml'
```

## Novedades de esta iteración

**Evidencia de audio.** Cada caso WS guarda `evidence/<case>.caller.wav` y
`<case>.agent.wav` (lo que realmente fue por el socket, en ambos sentidos)
y el informe los enlaza en la columna «evidencia». Los `interrupts[]`
(barge-in) también aparecen ahí.

**Ruido.** `turn.noise` mezcla ruido en el dominio PCM a la SNR pedida:
`synth: brown` genera ruido determinista (semilla por `scenario.id`) y
`file: asset.ulaw` usa una textura grabada. Ver `scenarios/noise/no-001.yaml`.

**Barge-in.** `turn.interrupt_on_agent_audio: true` hace que el caller corte
su propio turno en cuanto el agente empieza a hablar; el caso registra el
momento y la cola de audio que el agente siguió emitiendo
(`agent_tail_ms`). Ver `scenarios/difficult_caller/dc-002.yaml`.

**Concurrencia (switchboard).** `switchboard: {concurrency: N}` en el
experimento lanza N llamadas simultáneas con un escenario distinto cada
una tras la fase en serie — detecta contaminación de estado entre sesiones.
Ver `experiments/switchboard.yaml`. El doble usa `/control` por `call_id`,
imprescindible bajo concurrencia.

**TTS.** `tts_command: espeak-ng` (o `pico2wave`) en el experimento sintetiza
los turnos con `tts: true` a µ-law 8 kHz, cacheado por texto en
`.tts-cache/`. Sin binario, el turno cae a silencio (límite del rig, no
fallo del agente).

**Paciente LLM.** `caller.llm` activa un paciente con endpoint
OpenAI-compatible (Ollama, llama.cpp…). El prompt solo lleva persona +
`facts` + reglas de `behavior` — nunca el oráculo. Si el proveedor falla,
el caso continúa con el paciente por reglas (`fell_back` en el log).

**Coste.** `usage_url` en el candidato: el runner hace
`GET {usage_url}/calls/{call_id}` → `{cost, usage}` tras cerrar la llamada.
Coste ausente = `desconocido`, nunca cero. El doble expone
`/usage/calls/{id}` con coste determinista para autoverificación.

**Diff de runs.** Compara dos directorios de resultados:

```sh
uv run --project evaluator python -m evaluator.cli diff \
    results/<run_A> results/<run_B>          # texto
uv run --project evaluator python -m evaluator.cli diff A B --json
```

Reporta nuevos aciertos/fallos, cambios de veredicto, cambios de categoría
de fallo, casos solo presentes en un run y deltas de latencia/coste.

## Contrato con el responsable del agente

Lo que el evaluador necesita del agente (ver plan, §6):

- `CLINIC_API_BASE_URL` / `SUBMISSION_API_BASE_URL` configurables — con
  `PROSPER_API_BASE_URL` basta (el receptor local usa las mismas rutas).
- `WS` compatible con el contrato Twilio (`ws://host/ws`).
- Opcional: adaptador de texto `POST {text_url}/turns {call_id, text}` →
  `{reply}` — activa escenarios por texto y transcript para el check de
  fuga del problema 14.
- `call_id` = `start.callSid` exacto; ventana de submission 30 s tras el
  cierre del socket.

## Estado y límites conocidos

- 21 escenarios versionados cubriendo las 18 familias del reto (incluidas
  `noise` y `switchboard`), clínica local, receptor, doble, comparador,
  paciente por reglas/LLM, experimentos con repeticiones, JSON + informe.
- Veredictos `pass` / `fail` / `invalid_evaluation`: los fallos del propio
  rig (transporte, apertura de llamada, TTS ausente) invalidan el caso en
  vez de contarlos contra el agente.
- Evidencia: audio caller/agente por caso (`evidence/*.wav`), intentos de
  submission, latencias por turno, eventos de barge-in.
- Voz: turnos con fixture µ-law, TTS local opcional (`espeak-ng`/
  `pico2wave`, con caché) o silencio. El ruido por defecto es sintético
  determinista — las texturas oficiales (calle/TV/coche) irían como assets
  `noise.file` cuando existan.
- `availability` local es una aproximación fiel (calendario, schedules,
  `blocked` por baja y por aseguradora rechazada) — no reproduce cada
  restricción del backend oficial.
- `evaluator validate` comprueba que cada escenario resuelve contra su
  fixture (ids, slots dentro del calendario, letra de DNI).
- `evaluator score --scenario X --record Y` puntúa un record guardado sin
  llamar a nadie; `evaluator diff A B` compara dos runs.
- Coste: `desconocido` hasta que el agente exponga consumo vía
  `usage_url` (plan §13: nunca mostrar cero).
