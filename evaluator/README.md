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
| Clínica local | `src/evaluator/clinic/` | API de lectura (`/api/v1/directory`, `/availability`, `/appointments`, catálogo) sobre un dataset versionado + receptor `/api/v1/submit/*` con la semántica del contrato: 404 call desconocida, 410 ventana cerrada (30 s), 409 reintento idéntico, 422 malformado (incluida la letra del DNI). |
| Llamador | `src/evaluator/harness/wsclient.py` | Cliente WebSocket que habla el formato Twilio Media Streams del contrato (camelCase, `sequenceNumber`/`chunk`/`timestamp` como strings, frames µ-law 20 ms). |
| Doble de prueba | `src/evaluator/harness/double_agent.py` | Agente mínimo que responde el wire format y envía acciones enlatadas vía `/control`. Sirve para verificar el evaluador antes de enchufar el agente real. |
| Comparador | `src/evaluator/compare.py` | Veredicto binario: la lista de acciones grabadas debe coincidir con alguna `accepted_outcome` tras normalización. Diagnóstico por campo + check de fuga de datos (problema 14). |
| Normalización | `src/evaluator/normalize.py` | La tabla de tolerancia del scorer: DNI/NIE, nombres (NFKD, ñ→n), teléfonos, emails, slots en `Europe/Madrid` al minuto, enums. |
| Escenarios | `scenarios/**/*.yaml` | Casos versionados con `accepted_outcomes`, `from_number`, `reference_now`, `leak_check` y notas. |
| Experimentos | `experiments/*.yaml` | Candidatos (configuración del agente), set de escenarios, repeticiones. |
| Informe | `results/<run_id>/` | `manifest.json` (config + versión de reglas + hash del dataset), `cases.jsonl`, `report.html`. |

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

```yaml
scenario_id: sb-001
problem_id: simple_booking
version: 1
reference_now: "2026-09-18T10:00:00+02:00"  # ancla para fechas relativas
from_number: "+34612345678"                  # null = caller id oculto
turns:
  - text: "..."        # turno del caller (adaptador de texto)
    audio: turno1.ulaw # opcional: audio µ-law 8 kHz para la vía de voz
    hold_ms: 2000
accepted_outcomes:
  - - action: BOOK
      patient_id: P00042
      ...
leak_check:            # problema 14: comprobación de fuga en transcript
  national_id: "23456789D"
  phone: "622333444"
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

- MVP completo: escenarios, clínica local, receptor, doble, comparador,
  experimentos con repeticiones, JSON + informe HTML.
- Voz: el paciente reproduce fixtures µ-law o silencio; generar habla con
  TTS (corpus de voz) es la siguiente prioridad del plan.
- `availability` local es una aproximación fiel (calendario, schedules,
  `blocked` por baja y por aseguradora rechazada) — no reproduce cada
  restricción del backend oficial.
- `evaluator score --scenario X --record Y` puntúa un record guardado sin
  llamar a nadie.
