# evaluator — evaluador local del agente Prosper

Evaluador, tester y benchmark independiente para el agente de recepción de
Clínica Arenal (HackSpain 2026, track Prosper). El agente es un sistema
externo bajo prueba: este paquete controla las entradas, los datos y el
resultado esperado, y nunca le entrega los `accepted_outcomes`.

Todo el evaluador vive en `evaluator/`: dependencias y lockfile, entorno virtual,
clínica simulada, escenarios, tests e informes. No importa módulos de `backend/`
ni necesita modificar el agente. La integración es exclusivamente HTTP/WebSocket.
Los ejemplos usan puertos separados: `18090` para la clínica y `18770–18772`
para los dobles; el runner aborta si un puerto ya está ocupado. No reutilices
el servidor ni el túnel con el que otro compañero está ejecutando Prosper.

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

## Verificación aislada

Desde la raíz del repositorio, sin instalar ni arrancar `backend/`:

```sh
uv sync --project evaluator --locked
uv run --project evaluator --locked pytest -c evaluator/pyproject.toml evaluator/tests -q
uv run --project evaluator --locked ruff check evaluator/src evaluator/tests
```

El contrato de submission se verifica en dos mitades.

La mitad **siempre activa** es `tests/test_submit_vocabulary.py`: fija las rutas,
los campos obligatorios y el vocabulario cerrado de `models.py` contra el
receptor local, y reproduce el resultado esperado de los 21 escenarios con un
cuerpo construido por el propio evaluador. No importa nada de `backend/`, así
que corre siempre y no puede omitirse: una deriva del vocabulario falla en voz
alta.

La mitad **opt-in** es `tests/test_agent_main_contract.py`:

```sh
PYTHONPATH=backend/src uv run --project evaluator --locked pytest \
    -c evaluator/pyproject.toml evaluator/tests/test_agent_main_contract.py -q
```

Usa el cliente HTTP y el constructor de payloads del agente contra una
aplicación ASGI en memoria. No arranca el backend, no carga sus credenciales ni
conecta con Prosper. Sin `PYTHONPATH` el archivo se omite con un motivo
explícito (`-rs` lo muestra); si la fuente del agente está en el path pero no se
puede importar —por ejemplo, por una dependencia ausente en este entorno— la
colección **falla** en lugar de dar un skip verde, para que un entorno roto no
se confunda con cobertura. No sustituye una prueba de conversación real ni
certifica la equivalencia con el evaluador oficial.

`smoke.yaml` usa exclusivamente la clínica simulada y tres dobles locales:
acierto, registro incorrecto y ausencia de registro. No necesita credenciales
reales ni realiza llamadas a Prosper. Los informes y audios se guardan bajo
`evaluator/experiments/results/`, excluido de Git.

## Evaluar el agente real

Usa una instancia dedicada del agente, gestionada por su responsable fuera
de este paquete. La plantilla apunta a `ws://127.0.0.1:17860/ws`; cambia
`ws_url` si esa instancia usa otro puerto. Nunca apuntes estas pruebas al
endpoint compartido que atiende las llamadas oficiales.

El agente debe usar la clínica y el receptor locales, no la API de Prosper.
Su responsable lo arranca con estas variables y su comando habitual:

```sh
# terminal A — agente; el runner arranca la clínica local en 18090
export PROSPER_API_BASE_URL=http://127.0.0.1:18090
export PROSPER_API_KEY=pk-local-eval
export PORT=17860

# terminal B — experimento (no arrancar otra clínica en 18090)
uv run --project evaluator python -m evaluator.cli run \
    --config evaluator/experiments/agent-local.yaml
```

El bloque `env` del candidato solo se aplica si se configura `start_command`;
no cambia el entorno de un agente que ya está arrancado. La plantilla no
arranca, reinicia ni modifica ningún agente. Cada candidato describe una
configuración externa (modelo, prompts, proveedores); compara varias con
`candidates` y `repetitions`.

La plantilla necesita escenarios con audio o `tts: true` y un TTS instalado
para una prueba de voz; los turnos solo de texto se convierten en silencio.
El reloj del fixture no cambia automáticamente el reloj del agente externo;
coordina ambos antes de interpretar pruebas con fechas relativas.

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

**Alternativas dentro de un mismo run (side-by-side).** Un experimento ya corre
cada candidato sobre cada escenario, así que comparar alternativas es renderizar
esa corrida, no ejecutar otra:

```sh
uv run --project evaluator python -m evaluator.cli compare results/<run>         # tabla
uv run --project evaluator python -m evaluator.cli compare results/<run> --json  # resumen
```

Las filas son (escenario, repetición) y las columnas, los candidatos; las filas
marcadas con `*` son los desacuerdos, que es donde dos alternativas contestan
distinto la misma llamada. Dos decisiones del runner sostienen esa comparación:

- **intercalado**: el candidato varía más rápido dentro de cada escenario, así
  que un backend que deriva durante la corrida no favorece al que va último;
- **espera de readiness**: un candidato lanzado con `start_command` se sondea
  hasta que responde (`ready_url`; por defecto `http://host:port/healthz`
  derivado de `ws_url`, con `ready_timeout_s`, 30 s). Si nunca levanta, sus casos
  quedan en `invalid_evaluation` con la causa: no se puntúan contra el modelo.

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
