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

## Empieza aquí (no hace falta conocer el proyecto)

Tres comandos. El primero comprueba que el banco funciona; los otros dos
prueban el agente sin gastar ninguna llamada puntuada.

```sh
uv sync --project evaluator

# 1) ¿Funciona el banco? (no toca el agente, no necesita credenciales)
uv run --project evaluator python -m evaluator.cli run \
    --config evaluator/experiments/smoke-text.yaml
# Esperado: 21 correctas / 21 incorrectas / 21 incorrectas, 0 no evaluables.
# Son tres agentes de mentira: uno acierta, uno se equivoca a propósito y
# uno no envía nada. Si esto no sale así, el roto es el banco.

# 2) El agente de verdad, por texto (rápido: segundos por caso)
#    Necesita el backend arrancado con TURNS_ADAPTER en un puerto que NO
#    sea el 7860, y apuntando a la clínica local. Ver «Evaluar el agente
#    real». Descomenta `text_url` en experiments/agent-local.yaml.
uv run --project evaluator python -m evaluator.cli run \
    --config evaluator/experiments/agent-local.yaml

# 3) Comparar dos ejecuciones
uv run --project evaluator python -m evaluator.cli diff <run_A> <run_B>
```

Cada ejecución deja `results/<run_id>/report.html`. **Ábrelo**: la primera
pantalla dice contra qué datos se ha corrido y cómo se lee.

**Qué mide**: que el agente identifica al paciente, elige la cita correcta,
respeta las reglas de cobertura y **envía la acción exacta que espera la
plataforma, campo por campo**. Un campo mal y el caso es incorrecto, igual
que en el reto: no hay puntos parciales.

**Un solo run no compara dos versiones del agente.** El agente no es
determinista: dos ejecuciones idénticas del mismo código movieron **6 de 21
escenarios, en las dos direcciones** (medido el 19 sep 2026). Si tocas el
backend y pasas de 13 a 15 correctas, eso cabe entero dentro del ruido. Usa
`repetitions: 3` o más, mira la **tabla de estabilidad** del informe, y basa
las decisiones en los escenarios que salen *siempre incorrectos*: ésos son
fallos de verdad. El total no es un número que se pueda leer.

**Qué no mide**:
- **No dice si vas a puntuar.** Los datos son un fixture inventado de 6
  pacientes y 7 médicos; la clínica real tiene ~3.000 y 12. Verde aquí es
  «la lógica aguanta», no «la respuesta es correcta».
- **No prueba la voz de verdad.** La vía de texto se salta reconocimiento y
  síntesis. La de voz usa `espeak-ng`, que suena a robot.
- **No mira privacidad por la vía de voz**: sin transcripción no hay
  comprobación de fuga, y el informe lo dice caso por caso.
- No es el juez oficial y nadie ha validado que coincida con él.

**Regla operativa que no se salta nadie:** el puerto **7860** atiende
llamadas puntuadas de verdad a través del túnel de ngrok registrado en
Prosper. No apuntes nunca el banco ahí ni arranques nada en ese puerto.

## Qué contiene

| Pieza | Ruta | Qué hace |
| --- | --- | --- |
| Clínica local | `src/evaluator/clinic/` | API de lectura (`/api/v1/directory`, `/availability`, `/appointments`, catálogo) sobre un dataset versionado + receptor `/api/v1/submit/*` con la semántica del contrato: 404 call desconocida, 410 ventana cerrada (30 s), 409 reintento idéntico, 422 malformado (incluida la letra del DNI). Registra además los `attempts` por llamada para diagnóstico. |
| Llamador | `src/evaluator/harness/wsclient.py` | Cliente WebSocket que habla el formato Twilio Media Streams del contrato (camelCase, `sequenceNumber`/`chunk`/`timestamp` como strings, frames µ-law 20 ms). Mide latencia de respuesta por turno y primer audio, captura el audio en ambos sentidos y soporta barge-in (`interrupt_on_agent_audio`). |
| Audio/TTS | `src/evaluator/harness/audio.py`, `tts.py` | Codec µ-law↔PCM, WAV, mezcla de ruido con SNR, ruido sintético determinista; síntesis por subprocess (`espeak-ng`/`pico2wave`) con caché por texto. |
| Doble de prueba | `src/evaluator/harness/double_agent.py` | Agente mínimo que habla **las dos vías** —WebSocket `/ws` y adaptador de texto `/turns`— y envía acciones enlatadas vía `/control` **por call_id** (FIFO legacy sigue disponible). Expone `/usage/calls/{id}` con coste determinista para probar la telemetría. |
| Paciente simulado | `src/evaluator/simulator/patient.py`, `llm_patient.py` | Caller por reglas para el adaptador de texto: responde solo desde `caller.facts`, aplica `behavior` y nunca conoce el oráculo. Responde primero a la pregunta en curso (las correcciones programadas van después, nunca por delante de la identificación) y, si le preguntan un dato que el escenario no le dio, lo dice —queda en `log.unanswerable`, no en `log.missed`— en vez de pedir que le repitan. `caller.llm` lo sustituye por un LLM restringido (endpoint OpenAI-compatible) con fallback automático a reglas. |
| Comparador | `src/evaluator/compare.py` | Veredicto binario: la lista de acciones grabadas debe coincidir con alguna `accepted_outcome` tras normalización, respetando `forbidden_actions`. Diagnóstico por campo, check de fuga (problema 14) y categorías de fallo del plan §14. |
| Normalización | `src/evaluator/normalize.py` | La tabla de tolerancia del scorer: DNI/NIE, nombres (NFKD, ñ→n), teléfonos, emails, slots en `Europe/Madrid` al minuto, enums. |
| Escenarios | `scenarios/**/*.yaml` | Casos versionados con esquema `caller`/`oracle`/`limits` del plan, `split` (development/holdout) y `leak_check`. |
| Experimentos | `experiments/*.yaml` | Candidatos (configuración del agente), set de escenarios, repeticiones. |
| Informe | `results/<run_id>/` | `manifest.json` (config + versión de reglas + hash del dataset), `cases.jsonl`, `report.html` con puntos locales por peso de problema, cobertura y latencias. |

## Quickstart

```sh
uv sync --project evaluator

# 1) Smoke test del propio evaluador por WebSocket
#    (tres dobles: acierta / muta / calla)
uv run --project evaluator python -m evaluator.cli run \
    --config evaluator/experiments/smoke.yaml
# → evaluator/experiments/results/<run_id>/{manifest.json,cases.jsonl,report.html}

# 2) Lo mismo por la vía de texto: verifica el contrato `/turns` de punta a
#    punta (paciente simulado → adaptador → envío dentro de la ventana)
uv run --project evaluator python -m evaluator.cli run \
    --config evaluator/experiments/smoke-text.yaml
```

Para la vía de voz hace falta un TTS local:

```sh
brew install espeak-ng        # macOS
sudo apt install espeak-ng    # Debian/Ubuntu
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
export VOICE_WS_PORT=17860     # `python -m agent.voice.server`
# export PORT=17860            # solo si se arranca con `python -m agent.serve`

# terminal B — experimento (no arrancar otra clínica en 18090)
uv run --project evaluator python -m evaluator.cli run \
    --config evaluator/experiments/agent-local.yaml
```

**Nunca uses el 7860.** Ese proceso tiene el túnel ngrok registrado en Prosper
y atiende llamadas puntuadas de verdad; meterle tráfico de pruebas puede
tumbar una. Un test del repositorio comprueba que ningún experimento lo
menciona.

El bloque `env` del candidato solo se aplica si se configura `start_command`;
no cambia el entorno de un agente que ya está arrancado. Con `start_command`
el runner **espera a que el puerto acepte conexiones** antes del primer caso
(TCP, 60 s de tope) y aborta si nunca escucha: arrancar el proceso no es lo
mismo que tener el servicio en pie, y sin esa espera el primer caso se
perdía. La plantilla no
arranca, reinicia ni modifica ningún agente. Cada candidato describe una
configuración externa (modelo, prompts, proveedores); compara varias con
`candidates` y `repetitions`.

El reloj del fixture no cambia automáticamente el reloj del agente externo;
coordina ambos antes de interpretar pruebas con fechas relativas.

### Las dos vías, y cuál usar

| | vía de texto (`text_url`) | vía de voz (`ws_url`) |
| --- | --- | --- |
| qué prueba | prompt, brain, herramientas, agenda, envío | además STT, TTS, turn-taking, ruido |
| paciente | simulado y **reactivo** (responde a lo que dice el agente) | guion fijo, con pausas adaptativas |
| transcripción | sí → el check de fuga del problema 14 se evalúa | no (el evaluador no hace STT) |
| coste por caso | segundos | el tiempo real de la llamada |

`text_url` tiene prioridad sobre `ws_url` en el mismo candidato. Para iterar
sobre la lógica usa texto; para comprobar que la llamada suena, voz.

## Adaptador de texto `/turns`

Contrato exacto que consume `_run_text_call` (`runner/experiment.py`). El
doble de prueba lo implementa entero (`harness/double_agent.py`), así que se
puede verificar sin el agente real:

```sh
uv run --project evaluator python -m evaluator.cli run \
    --config evaluator/experiments/smoke-text.yaml
```

**Obligatorio**

```http
POST {text_url}/turns
Content-Type: application/json

{"call_id": "9f8e…", "text": "Buenos días, quiero una cita."}
```

```http
200 OK
{"reply": "Clínica Arenal, ¿en qué puedo ayudarle?", "ended": false}
```

- `call_id` es el mismo identificador que el `start.callSid` de la vía de
  voz y el `call_id` de `POST /api/v1/submit/*`. **La primera petición con un
  `call_id` nuevo abre la llamada**; no hay ruta de apertura.
- `reply` es **una sola intervención del agente**, en texto. `null` o cadena
  vacía significa "no dije nada"; no rompe la llamada, pero no entra en la
  transcripción.
- **Un turno es un turno entero del agente**: varias vueltas al LLM y sus
  llamadas a herramientas dentro de un mismo POST. Medido contra el agente
  real (65 turnos): p50 3,4 s, p90 12,3 s, p95 13,6 s, max 20,2 s. El tope
  es `text_timeout_seconds` del candidato, **120 s por defecto**: un seguro
  contra cuelgues, no un presupuesto de latencia. El adaptador tiene su
  propio cliente HTTP; el de la clínica local sigue en 10 s.
- `scenario.limits.max_call_seconds` acota la **conversación entera** (como
  los 3 minutos de la plataforma). Al agotarse, el evaluador cuelga y
  puntúa lo que se haya enviado: no invalida el caso.

**Opcional pero recomendado**

- `"ended": true` en la respuesta: el agente da la llamada por terminada y el
  evaluador deja de hablar. Si se omite, la llamada acaba cuando el paciente
  simulado se despide o agota `limits.max_turns`.
- Cierre explícito de la ventana:

  ```http
  POST {text_url}/turns
  {"call_id": "9f8e…", "text": null, "event": "hangup"}
  ```

  Es el equivalente a que se caiga el socket: el momento de vaciar las
  acciones encoladas. **Es best-effort**: el evaluador ignora el código de
  estado y el cuerpo, así que un agente que no lo implemente no pierde
  ningún caso por ello (devolverá 422 y no pasa nada). Debe ser idempotente.

  Best-effort **no es invisible**: el resultado del `hangup` queda en
  `notes` del caso y el informe lo imprime junto a la evidencia. `notes` es
  diagnóstico que ningún veredicto lee. Pasó de verdad —un adaptador que
  declaraba `text: str` devolvía 422 a todos los `hangup` y nadie lo veía—,
  y en este proyecto una señal que se traga en silencio es exactamente cómo
  se pierde un run.

**Ventana de envío.** Igual que en la vía de voz: el receptor local acepta
`POST /api/v1/submit/*` mientras la llamada está abierta y hasta 30 s después
de cerrarla (410 pasado ese plazo, 404 si el `call_id` no existe, 409 si se
repite una acción idéntica, 422 si faltan campos o la letra del DNI no
cuadra). Tras el `hangup` el evaluador **sondea el registro** durante
`submit_drain_s` segundos (2 s por defecto) antes de puntuar, para que un
flush tardío no se pierda.

**Errores.** Si el adaptador no responde, responde algo que no sea 200 o
devuelve un cuerpo que no es JSON, el caso se marca `invalid_evaluation`
—defecto del rig, no fallo del agente— salvo que aun así hubiera envíos
grabados.

**Lo que el adaptador no tiene que hacer**: ni audio, ni ngrok, ni estado
global. Un `call_id` por conversación, aislado de los demás.

### Cómo se conecta, y en qué orden

El candidato necesita `text_url` apuntando al adaptador; con eso basta, y
tiene prioridad sobre `ws_url`.

**El orden de arranque importa y no es intercambiable:**

1. **La clínica local primero.** El backend calienta su catálogo una sola vez,
   en el lifespan del servidor. Si la clínica no está escuchando cuando el
   agente arranca, la caché se queda fría y `describe_clinic`,
   `find_nearest_site` y la ventana de calendario **degradan en silencio**:
   no hay excepción ni log, simplemente responden peor. Es la peor forma de
   fallar y la más fácil de atribuir al agente.
2. **El agente después**, apuntando a esa clínica (`PROSPER_API_BASE_URL`).
3. **Los casos al final.**

Con `start_command` en el candidato, el runner espera a que el puerto acepte
TCP antes del primer caso, pero **eso no reordena nada**: si el
`start_command` arranca el agente antes de que exista la clínica, la caché
sigue quedándose fría. Arranca la clínica tú.

### Control de acceso

`/turns` está detrás del control de acceso del ops console del backend:

- Sin `OPS_TOKEN`, solo se sirve a **loopback**.
- Con `OPS_TOKEN` puesto, hace falta la cabecera `X-Ops-Token`.

El banco corre en `127.0.0.1`, así que por defecto no hay que hacer nada. Si
alguna vez lo corres **desde otra máquina**, necesitas el token. La razón de
que esté cerrado: un `/turns` alcanzable desde fuera ejecuta el ToolBox real
y puede enviar acciones contra la API de Prosper con la clave del equipo.

## La vía de voz: qué mide de verdad

Todos los turnos de `scenarios/**` llevan `tts: true`, y
`experiments/agent-local.yaml` define `tts_command: espeak-ng`. El llamante
sintetiza cada línea a µ-law 8 kHz (caché en `.tts-cache/` por texto, así
que dos candidatos oyen exactamente la misma voz) y la reproduce en tiempo
real por el socket.

**Sé honesto con lo que eso significa:**

- `espeak-ng` es un sintetizador formántico. Suena a robot: prosodia plana,
  sin respiraciones, sin dudas, sin acento, sin ruido de línea. **No es una
  voz humana ni se le parece.** Un STT que entienda a espeak-ng puede fallar
  con una persona, y al revés.
- Sirve para lo que estaba roto: comprobar que el agente **oye algo**,
  arranca, hace preguntas, usa herramientas y envía. No sirve para concluir
  nada sobre la calidad del reconocimiento ni sobre el turn-taking real.
- El guion es fijo: el llamante dice sus líneas en orden, pase lo que pase.
  Espera a que el agente termine de hablar (silencio de 800 ms, tope de 15 s
  por turno, `VOICE_MAX_HOLD_MS`) antes de soltar la siguiente, pero no
  improvisa. Si el agente pregunta otra cosa, el guion no se entera.
- El ruido de `scenarios/noise/no-001.yaml` se mezcla ahora sobre voz de
  verdad, no sobre silencio, pero es ruido marrón sintético: una
  aproximación, no las texturas oficiales (calle, TV, coche).
- Sin `tts_command`, o si falla el binario, el caso sale
  `invalid_evaluation` con el motivo. **Ya no se puntúa a un agente al que
  se le ha reproducido silencio.**

Para una prueba con voz humana, graba los turnos y ponlos en `audio:`
(µ-law 8 kHz crudo, relativo al escenario): tiene prioridad sobre el TTS.

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
    tts: true          # sintetiza `text` con el TTS del experimento.
                       # Todos los escenarios del repo lo llevan: sin él
                       # (o sin `audio:`) el caso sale invalid_evaluation.
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
`.tts-cache/`. Todos los escenarios llevan ya `tts: true`. Sin binario el
turno cae a silencio **y el caso se marca `invalid_evaluation`** con el
motivo: es un defecto del rig, no un fallo del agente, y puntuarlo era el
error que hacía fallar los 21 casos. Ver «La vía de voz: qué mide de
verdad».

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
  con `wait_until_listening` hasta que acepta la conexión TCP del socket que va
  a usar (funciona igual para el WS y para el adaptador de texto, sin asumir
  ninguna ruta de salud). Si nunca levanta, sus casos quedan en
  `invalid_evaluation` con la causa y el resto de las alternativas conserva su
  evidencia: no se puntúan contra el modelo.

## Contrato con el responsable del agente

Lo que el evaluador necesita del agente (ver plan, §6):

- `CLINIC_API_BASE_URL` / `SUBMISSION_API_BASE_URL` configurables — con
  `PROSPER_API_BASE_URL` basta (el receptor local usa las mismas rutas).
- `WS` compatible con el contrato Twilio (`ws://host/ws`).
- Adaptador de texto `POST {text_url}/turns {call_id, text}` → `{reply}`:
  la vía de más valor, porque corre los 21 escenarios en segundos y sin
  gastar ninguna llamada puntuada. Contrato completo en «Adaptador de texto
  `/turns`»; el doble lo implementa y `smoke-text.yaml` lo verifica.
- `call_id` = `start.callSid` exacto; ventana de submission 30 s tras el
  cierre del socket.

## Consola de developer

El front-desk y el developer son usuarios distintos: la consola de developer es
para quien prueba el agente, mira métricas y compara alternativas, y vive dentro
de este paquete. No tiene build, ni npm, ni CDN: el propio evaluador sirve el
HTML, el JS y el CSS.

```sh
uv run --project evaluator python -m evaluator.cli dev --port 8099
# → http://127.0.0.1:8099/          consola
# → http://127.0.0.1:8099/api/docs  API documentada
```

Opciones: `--results` (dónde lee las corridas, por defecto
`evaluator/experiments/results`) y `--web` (la carpeta de la consola).

La API es **read-only sobre las corridas**: lee lo que una corrida ya escribió y
no lanza corridas, no edita escenarios y no escribe en un directorio de
resultados. Un identificador de corrida es un nombre de carpeta, nunca una ruta,
y un archivo de evidencia tiene que resolver dentro de su corrida.

| Endpoint | Devuelve |
|---|---|
| `GET /api/runs` | lista de corridas con conteos y si tienen informe |
| `GET /api/runs/{id}` | manifest + métricas agregadas + resumen side-by-side |
| `GET /api/runs/{id}/cases` | los casos completos |
| `GET /api/runs/{id}/compare` | side-by-side por caso, con desacuerdos marcados |
| `GET /api/diff?a=&b=` | resumen del diff entre dos corridas |
| `GET /api/runs/{id}/report` | el `report.html` de esa corrida |
| `GET /api/runs/{id}/evidence/{stream}?case_id=` | el WAV de audio de un caso |
| `POST /api/chat` | abre una llamada real contra el agente |
| `POST /api/chat/{sid}/say` | dice un turno y devuelve el audio del agente |
| `POST /api/chat/{sid}/close` | cierra, lee submissions y diagnostica |

La pestaña de chat usa el mismo `CallSession`, la misma clínica local y el mismo
receptor que las corridas automáticas: lo que se ve ahí es lo que un experimento
mediría. Al cerrar muestra frames por dirección, segundos de voz del caller,
caracteres de transcript que el agente registró, submissions aceptadas y
rechazadas, y —con `--agent-audit-dir`— el diagnóstico de si el agente escuchó
al caller. Sin ruta de auditoría el diagnóstico dice `unavailable`, nunca culpa
al modelo.

Límites: la API no lanza corridas ni acepta comandos; el micrófono queda para
una segunda iteración (el chat es tipeado, con TTS local en el servidor), y
`OPS_TOKEN` no aplica acá porque la consola se ata a `127.0.0.1`.

## Estado y límites conocidos

- 21 escenarios versionados cubriendo las 18 familias del reto (incluidas
  `noise` y `switchboard`), clínica local, receptor, doble, comparador,
  paciente por reglas/LLM, experimentos con repeticiones, JSON + informe.
- Veredictos `pass` / `fail` / `invalid_evaluation`: los fallos del propio
  rig (transporte, apertura de llamada, TTS ausente) invalidan el caso en
  vez de contarlos contra el agente.
- Evidencia: audio caller/agente por caso (`evidence/*.wav`), intentos de
  submission, latencias por turno, eventos de barge-in.
- Voz: turnos con fixture µ-law o TTS local (`espeak-ng`/`pico2wave`, con
  caché). La voz sintética es robótica y el guion es fijo: mide que el
  agente oye y reacciona, no la calidad del reconocimiento. El ruido por
  defecto es sintético determinista — las texturas oficiales
  (calle/TV/coche) irían como assets `noise.file` cuando existan.
- **El check de fuga (problema 14) solo se evalúa en la vía de texto.** Por
  WebSocket no hay transcripción porque el evaluador no hace STT, así que
  no puede comprobar si el agente dijo un DNI en voz alta. En ese caso el
  resultado marca `checks_not_run: ["leak_check"]` y el informe lo imprime:
  un caso puede pasar con la comprobación de privacidad sin ejecutar, y eso
  tiene que verse. Para cubrir el problema 14 de verdad, corre ese
  escenario por texto.
- El dataset local es una miniatura inventada (6 pacientes, 7 médicos, 3
  sedes, 4 planes, 8 tipos de cita) frente a la clínica real (~3.000
  pacientes, 12 médicos, 10 planes, 11 tipos). `report.html` abre con ese
  aviso y la tabla comparativa: pasar aquí valida **lógica**, no
  corrección contra los datos oficiales.
- `availability` local es una aproximación fiel (calendario, schedules,
  `blocked` por baja y por aseguradora rechazada) — no reproduce cada
  restricción del backend oficial.
- `evaluator validate` comprueba que cada escenario resuelve contra su
  fixture (ids, slots dentro del calendario, letra de DNI).
- `evaluator score --scenario X --record Y` puntúa un record guardado sin
  llamar a nadie; `evaluator diff A B` compara dos runs.
- Coste: `desconocido` hasta que el agente exponga consumo vía
  `usage_url` (plan §13: nunca mostrar cero).
