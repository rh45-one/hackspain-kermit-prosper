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
Prosper. No apuntes nunca el banco ahí ni arranques nada en ese puerto. Desde
P0 no hace falta recordarlo: `evaluator.profiles.guard` rechaza cualquier perfil
que apunte al 7860, a un destino oficial o a un puerto ocupado, con el motivo
escrito (ver «Perfiles del laboratorio»).

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
| Informe | `results/<run_id>/` | `manifest.json` (config + versión de reglas + hash del dataset), `cases.jsonl`, `metrics.json` (los mismos agregados que la consola, en máquina) y `report.html` con puntos locales por peso de problema, cobertura, latencias, audio, barge-ins y errores por tipo. |
| Observador post-hoc | `src/evaluator/observer/` | Convierte las llamadas **reales** que el backend ya atendió (`DATA_DIR/calls/*.jsonl`) en una corrida: transcripts, acciones encoladas con su payload completo y submissions. Puntúa solo las llamadas etiquetadas en un mapa de oráculos; el resto queda informativo. No cambia el backend. |
| Métricas | `src/evaluator/report/metrics.py` | Agregados por corrida y candidato: aciertos, no evaluables, errores por tipo, turnos, primera respuesta p50/p95, latencia por turno, submissions, audio por dirección, barge-ins, coste, estabilidad. Cada uno con numerador y denominador; `n/d` cuando el dato no existe. |

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

## Perfiles del laboratorio

Un **perfil** es una declaración de con qué se habla y qué se puede esperar de
ese agente, y vive en el servidor: el catálogo por defecto está en
`evaluator/src/evaluator/profiles/catalog.py` y la copia editable —con el
contrato congelado del backend comentado— en
`evaluator/experiments/profiles.yaml`. Declara:

- `id`, `engine` (`cascade` | `gemini_live` | `external` | `double`) y `version`;
- endpoints: `ws_url` (voz), `text_url` (adaptador `/turns`) y `usage_url`;
- capacidades: texto, voz, captura de audio y **de dónde sale** ese audio,
transcripción, telemetría de coste y resultado esperado;
- metadatos del proveedor (stack, documentación, notas);
- credenciales **por nombre de variable de entorno**, nunca por valor
(`agent_api_key: PROSPER_API_KEY`); los valores los pone el entorno del
servidor.

Un perfil incompleto o contradictorio no carga, y el error nombra **todos** los
campos en falta en un solo mensaje: una capacidad de voz sin `endpoints.ws_url`,
una capacidad de audio sin fuente (`audio_source`), una telemetría de coste sin
`usage_url`, un motor desconocido, o una credencial pegada como valor en vez de
como referencia. `start_command` es material del servidor: lo declara quien
escribe el archivo en esta máquina y **nunca** llega desde el cuerpo de una
petición.

### Guarda del laboratorio

Antes de usar un perfil, la guarda rechaza con el motivo por escrito:

- **el puerto 7860**, que atiende llamadas puntuadas. El rechazo sale de una
  constante: para hablar del 7860 el código no abre ningún socket.
- **cualquier destino oficial o remoto** (`prosper…`, `hackspain…`, `ngrok…`,
  cualquier host que no sea loopback o red privada).
- **un puerto ya ocupado**, solo cuando el laboratorio *arrancaría* algo ahí.
  Una sesión en vivo habla con un proceso que ya está escuchando, así que ese
  camino no sondea puertos (y nunca toca el 7860).

```sh
# la lista de perfiles que declara este servidor, con su veredicto de guarda
curl -s http://127.0.0.1:8099/api/profiles | python -m json.tool

# prueba manual por perfil, sin escribir ninguna URL
evaluator chat --profile cascade
```

### Esquema de llamada y evidencia

Todo lo que el laboratorio escribe sobre una llamada (`cases.jsonl`) usa un
mismo esquema, con `schema_version` explícito. Cada caso dice:

- **origen**: `real` (llamada que el backend atendió, leída de su audit),
  `simulated` (caso guionado del runner) o `manual` (persona en la consola);
- candidato **y versión**, más el `run_id` y el `case_id` que lo produjeron;
- **tiempos**: `started_at`, `ended_at`, `duration_s`;
- **disponibilidad de evidencia** una por una — audio, transcripción, coste,
  resultado — con tres valores: `present`, `absent`, `unknown`. Nunca un cero
  silencioso: el coste que nadie midió es `unknown`, y una llamada real con
  audio `absent` es una fuente sin grabación, no un silencio;
- **transcripción como eventos ordenados** con rol, marca de tiempo y
  `fragment`. El backend entrega fragmentos: el evaluador los conserva en orden
  y no inventa fronteras de turno donde la fuente no las da. Los campos por
  interlocutor que ya existían siguen funcionando.

**Lectura tolerante.** Un artefacto escrito por una corrida anterior se lee sin
migración manual: `load_cases` lo pasa por el mismo modelo, que infiere lo que
falta y marca lo inferido (rol y fragmento a partir del transcript viejo). Una
línea sin `schema_version` se registra como versión 1 —la de antes de que el
campo existiera— en lugar de disfrazarse de la actual. Por eso
`GET /api/runs/{id}` y `GET /api/runs/{id}/cases` siguen respondiendo sobre las
corridas que ya están en `experiments/results/`.

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

**Llamadas reales del backend (observador post-hoc).** El backend ya deja un
audit por llamada en `DATA_DIR/calls/<call_id>.jsonl` con el transcript de los
dos lados, la acción encolada **con su payload completo** y el flush de
submissions. El evaluador lo lee y lo convierte en una corrida, sin tocar el
backend ni la red:

```sh
uv run --project evaluator python -m evaluator.cli observe \
    --data-dir backend/data                       # todas informativas
uv run --project evaluator python -m evaluator.cli observe \
    --data-dir backend/data --map evaluator/experiments/oracle-map.yaml
```

El mapa de oráculos es un YAML con `call_id` (o un prefijo inequívoco) contra el
escenario que esa llamada estaba jugando:

```yaml
calls:
  060b5378: evaluator/scenarios/simple_booking/sb-001.yaml
  2d154827: evaluator/scenarios/the_rules/rules-001.yaml
```

Las llamadas etiquetadas se puntúan con el **mismo comparador** de siempre
(normalización campo por campo, `forbidden_actions`) y, como el audit trae
transcript del agente, también corre la **comprobación de fuga del problema
14**, que la vía de voz no puede hacer. Las no etiquetadas no inventan
veredicto: se muestran como evidencia (qué acción se envió, si se confirmó la
identidad, qué se dijo) en el informe y en la pestaña «Llamadas reales». El
resultado es una corrida normal (`manifest.json`, `cases.jsonl`,
`metrics.json`, `report.html` + `real_calls.jsonl`), así que `metrics`, `diff`
y la consola funcionan igual.

Un prefijo que coincide con dos entradas del mapa es un error, no una
adivinanza: puntuar la llamada equivocada en silencio es peor que parar. Los
transcripts quedan solo bajo `results/`, que Git ignora.

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
de fallo, casos solo presentes en un run, deltas de latencia/coste y una tabla
de **deltas de métricas** (aciertos, no evaluables, primera respuesta, audio,
barge-ins, estabilidad…), con `n/d` cuando alguno de los dos lados no midió.

**Pareo entre candidatos de corridas distintas.** El diff también responde «¿el
candidato B de la corrida Y le ganó al candidato A de la corrida X?»:

```sh
uv run --project evaluator python -m evaluator.cli diff \
    results/<run_X> results/<run_Y> --candidate-a viejo --candidate-b nuevo
```

En ese modo las claves pasan a ser (escenario, repetición) y no (candidato,
escenario, repetición): los casos se parean por lo que se corrió, no por cómo se
llamaba la configuración. Con varios candidatos por lado hay que decir cuál
(la CLI y la API lo exigen); con uno solo se resuelve solo.

**Matriz declarativa de variantes.** Un candidato puede declarar variantes de
entorno y el runner las expande en un candidato por variante, con el nombre
`<candidato>-<sufijo>` y el `env` base sobrescrito por el de la variante:

```yaml
candidates:
  - name: agent
    ws_url: ws://127.0.0.1:17860/ws
    env: { PROSPER_API_BASE_URL: "http://127.0.0.1:18090" }
    variants:
      sin-memoria: { PROMPT_VARIANT: none }
      con-memoria: { PROMPT_VARIANT: history }
```

Dos configuraciones que no se pueden distinguir en un informe son peor que un
YAML que no carga: nombres duplicados tras expandir son un error.

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
HTML, el JS, el CSS y las fuentes (Inter e Inter Tight, variables y con licencia
OFL, en `web/fonts/`). El lenguaje visual es ClinicReflow: papel cálido, tinta
grafito, latón para los metadatos y brasa solo cuando algo está vivo o roto.

Cinco pestañas:

| Pestaña | Qué muestra |
|---|---|
| Benchmarks | hechos de la corrida (dataset, reglas, repeticiones), una tarjeta por candidato y la matriz de aciertos por familia de problema |
| Métricas | el detalle por candidato: cada agregado con su numerador/denominador, el desglose de errores por tipo y la lista de errores registrados |
| Comparar | alternativas de la misma corrida, lado a lado, y el diff entre dos corridas con pareo de candidatos |
| Llamadas reales | el observador post-hoc: qué llamadas reales vio esta corrida, con acción enviada, identidad confirmada, veredicto de las etiquetadas y el transcript plegado |
| Probar el agente | la llamada en vivo, tipeada o **hablada** (ver micrófono), contra el **perfil** que elijas del catálogo del servidor |

```sh
uv run --project evaluator python -m evaluator.cli dev --port 8099
# → http://127.0.0.1:8099/          consola
# → http://127.0.0.1:8099/api/docs  API documentada
```

Opciones: `--results` (dónde lee las corridas, por defecto
`evaluator/experiments/results`) y `--web` (la carpeta de la consola).

La API conserva las corridas como evidencia inmutable y añade dos escrituras
controladas: reconstruir un índice local de historial desde esos artefactos y
crear trabajos desde perfiles y escenarios declarados en el servidor. Nunca
acepta rutas, comandos, URLs ni entorno del navegador. Un identificador de
corrida es un nombre de carpeta, nunca una ruta, y un archivo de evidencia tiene
que resolver dentro de su corrida.

| Endpoint | Devuelve |
|---|---|
| `GET /api/runs` | lista de corridas con conteos y si tienen informe |
| `GET /api/runs/{id}` | manifest + métricas agregadas + resumen side-by-side |
| `GET /api/profiles` | los perfiles que declara el servidor (id, capacidades, proveedor, veredicto de la guarda), sin valores de credenciales, rutas ni comandos |
| `GET /api/runs/{id}/cases` | los casos completos |
| `GET /api/runs/{id}/compare` | side-by-side por caso, con desacuerdos marcados |
| `GET /api/diff?a=&b=` | resumen del diff entre dos corridas |
| `GET /api/runs/{id}/report` | el `report.html` de esa corrida |
| `GET /api/runs/{id}/evidence/{stream}?case_id=` | el WAV de audio de un caso |
| `POST /api/chat` | abre una llamada real contra el perfil indicado por `profile_id` |
| `GET /api/runs/{id}/real-calls` | las llamadas reales que observó esa corrida (vacío si no es una corrida del observador) |
| `POST /api/history/import` | reconstruye idempotentemente el índice local desde los runs existentes |
| `GET /api/history/calls` | histórico filtrable y paginado de llamadas simuladas, reales y manuales; los dobles se excluyen por defecto |
| `GET /api/history/calls/{record_id}` | evidencia y detalle de una llamada del histórico |
| `GET /api/history/summary` | población, éxito evaluado y cobertura de audio, transcript, coste y resultado |
| `POST /api/jobs` | crea una corrida controlada con `profile_ids`, `scenario_ids`, modalidad y repeticiones |
| `GET /api/jobs` | trabajos persistidos y su progreso |
| `POST /api/jobs/{id}/cancel` | solicita cancelación entre llamadas, preservando los casos ya terminados |
| `GET /api/comparisons?run_id=` | comparación con tamaño de muestra y disponibilidad de estabilidad |
| `POST /api/chat/{sid}/say` | dice un turno (TTS del servidor) y devuelve el audio del agente |
| `POST /api/chat/{sid}/say-audio` | dice un turno con **audio µ-law** del micrófono del navegador |
| `POST /api/chat/{sid}/close` | cierra, lee submissions y diagnostica |

`GET /api/diff` acepta `candidate_a` y `candidate_b` para parear dos candidatos
de corridas distintas; con varios candidatos por lado el pareo es obligatorio y
la API responde 400 si falta, en vez de elegir uno.

La pestaña de chat usa el mismo `CallSession`, la misma clínica local y el mismo
receptor que las corridas automáticas: lo que se ve ahí es lo que un experimento
mediría. Al cerrar muestra frames por dirección, segundos de voz del caller,
caracteres de transcript que el agente registró, submissions aceptadas y
rechazadas, y —con auditoría configurada en el perfil— el diagnóstico de si el
agente escuchó al caller. Sin ruta de auditoría el diagnóstico dice
`unavailable`, nunca culpa al modelo.

**La sesión se pide por perfil, no por URL.** El cuerpo de `POST /api/chat`
lleva un `profile_id` del catálogo del servidor, el TTS/STT y tiempos; cualquier
campo que elija destino, ruta, comando o entorno (`ws_url`, `clinic_url`,
`scenario`, `agent_audit_dir`, `start_command`, `env`, …) se **rechaza por
nombre**, y un campo inventado también. El destino, la clínica, la clave, el
escenario y el directorio de auditoría los resuelve el servidor desde el perfil.
El rechazo nombra el campo y nunca repite el valor que venía en él.

**Micrófono (push-to-talk).** El botón «Hablar» captura del micrófono con un
`AudioWorklet` que codifica µ-law a 8 kHz en frames de 160 bytes (20 ms), el
mismo patrón que el demo del propio backend (`backend/serverwebsock/`) y el
mismo sobre el que habla el `wsclient`. Los frames suben a
`POST /api/chat/{sid}/say-audio` en base64 y el rig los manda al agente tal
cual: nada se decodifica ni se re-sintetiza en el servidor, así que el agente
oye exactamente lo que capturó el navegador. El botón sólo aparece si el
navegador puede capturar (`isSecureContext`, `getUserMedia`,
`AudioWorkletNode`); si hay STT, el log muestra la transcripción de lo que
dijiste. El último frame se rellena con silencio µ-law (`0xff`) para no mandar
un frame corto, y hay un tope de 60 s por subida.

Límites: los trabajos no arrancan procesos de agente ni aceptan comandos; hablan
con perfiles de laboratorio ya declarados y el runner limpia únicamente los
procesos propios. `OPS_TOKEN` no aplica acá porque la consola se ata a
`127.0.0.1`. El navegador tampoco ve valores de
credenciales: el manifiesto se sirve con **todos** los valores de `env`
reemplazados por `***` —los nombres quedan, que es lo que sirve para leer una
corrida— y los errores públicos pasan por el mismo cepillo.

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
- **El check de fuga (problema 14) no se evalúa en la vía de voz.** Por
  WebSocket no hay transcripción porque el evaluador no hace STT, así que
  no puede comprobar si el agente dijo un DNI en voz alta. En ese caso el
  resultado marca `checks_not_run: ["leak_check"]` y el informe lo imprime:
  un caso puede pasar con la comprobación de privacidad sin ejecutar, y eso
  tiene que verse. Sí se evalúa en la vía de texto y en **las llamadas
  reales observadas**, porque ahí el audit del backend trae el transcript
  del agente.
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
  llamar a nadie; `evaluator diff A B` compara dos runs (con
  `--candidate-a/--candidate-b` para parear candidatos distintos);
  `evaluator metrics <run>` imprime la tabla de agregados de una corrida
  (`--json` para máquina) y `evaluator observe` convierte el audit real del
  backend en una corrida.
- Coste: `desconocido` hasta que el agente exponga consumo vía
  `usage_url` (plan §13: nunca mostrar cero).
