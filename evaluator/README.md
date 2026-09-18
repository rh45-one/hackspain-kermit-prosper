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
| Llamador | `src/evaluator/harness/wsclient.py` | Cliente WebSocket que habla el formato Twilio Media Streams del contrato (camelCase, `sequenceNumber`/`chunk`/`timestamp` como strings, frames µ-law 20 ms). Mide latencia de respuesta por turno y primer audio. |
| Doble de prueba | `src/evaluator/harness/double_agent.py` | Agente mínimo que responde el wire format y envía acciones enlatadas vía `/control`. Sirve para verificar el evaluador antes de enchufar el agente real. |
| Paciente simulado | `src/evaluator/simulator/patient.py` | Caller por reglas para el adaptador de texto: responde solo desde `caller.facts`, aplica `behavior` (revelar identificadores, segunda póliza, correcciones) y nunca conoce el oráculo. |
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
# terminal A — clínica local (la runner también la levanta sola)
uv run --project evaluator python -m evaluator.cli clinic \
    --dataset evaluator/data/clinic_dataset.json --port 8090

# terminal B — agente con la clínica y el receptor locales
cd backend
PROSPER_API_BASE_URL=http://localhost:8090 \
PROSPER_API_KEY=pk-local-eval \
uv run python -m agent.voice.server

# terminal C — experimento
uv run --project evaluator python -m evaluator.cli run \
    --config evaluator/experiments/agent-local.yaml
```

Si el agente ya corre por su cuenta, basta `ws_url` en el candidato; si pones
`start_command`, el runner lo arranca él y espera el puerto. Cada candidato
del experimento es una configuración (modelo, prompts, proveedores) del
mismo agente — compara configuraciones con varios `candidates` +
`repetitions`.

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
    hold_ms: 2000
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

- MVP completo: 18 escenarios versionados (16 familias del reto),
  clínica local, receptor, doble, comparador, paciente por reglas para el
  adaptador de texto, experimentos con repeticiones, JSON + informe HTML.
- Veredictos `pass` / `fail` / `invalid_evaluation`: los fallos del propio
  rig (transporte, apertura de llamada) invalidan el caso en vez de
  contarlos contra el agente.
- Voz: el paciente reproduce fixtures µ-law o silencio; el paciente por
  reglas solo opera sobre el adaptador de texto hasta que exista TTS.
- `availability` local es una aproximación fiel (calendario, schedules,
  `blocked` por baja y por aseguradora rechazada) — no reproduce cada
  restricción del backend oficial.
- `evaluator validate` comprueba que cada escenario resuelve contra su
  fixture (ids, slots dentro del calendario, letra de DNI).
- `evaluator score --scenario X --record Y` puntúa un record guardado sin
  llamar a nadie.
- Coste: el informe muestra `desconocido` hasta que el agente exponga
  consumo (plan §13: nunca mostrar cero).
