# Tarea: adaptador de texto `POST /turns` — el mayor desbloqueo pendiente

Lee `PROJECT_CONTEXT.md` entero antes de tocar nada. Resume el hackathon, cómo
se puntúa, y las lecciones que salieron de perder llamadas puntuadas.

## Reparto de ficheros — LÉELO PRIMERO

Hay **otro agente trabajando en este backend a la vez**, y el servidor de voz
está atendiendo **llamadas puntuadas de verdad** ahora mismo.

**Tuyo:**
- `backend/src/agent/ops/turns.py` (nuevo)
- el cableado mínimo en `backend/src/agent/voice/server.py` y `agent/serve.py`
- `backend/tests/test_turns.py` (nuevo)

**NO tuyo, se está editando en caliente:**
- `backend/src/agent/brain/tools.py`
- `backend/src/agent/brain/prompts.py`
- `backend/src/agent/clinic/cache.py`
- `backend/src/agent/ops/console.py` (lo lleva el agente de frontend)

Si necesitas cambiar algo de esos, **pregunta antes**, no lo edites.

## Regla crítica de operación

**Nunca mates, reinicies ni arranques nada en el puerto 7860.** Esa instancia
tiene un túnel ngrok registrado en la plataforma y recibe llamadas puntuadas;
un reinicio a destiempo ya tumbó un run hoy. Para probar usa
`VOICE_WS_PORT=17999`.

## Por qué importa

La plataforma solo deja **una llamada puntuada cada 12 minutos**. No se puede
iterar. En `evaluator/` hay un banco de pruebas con 21 escenarios con oráculo
que cubren las 18 familias de problemas, clínica falsa incluida con la
semántica exacta del submit. Está listo salvo por una cosa:

`evaluator/src/evaluator/runner/experiment.py:_run_text_call` habla con el
candidato por `POST {text_url}/turns` y **nuestro backend no lo expone**.

Implementarlo da 21 casos conversacionales corriendo en segundos con **cero
llamadas puntuadas**. No prueba el pipeline de audio, pero sí prompt, brain,
tools, scheduling y submit, que es donde se juegan casi todos los puntos.

## Qué hacer

1. **Lee el contrato en el código del evaluador, no lo inventes.** Mira
   `_run_text_call` y `simulator/patient.py` en `evaluator/src/evaluator/`.
   A grandes rasgos: `POST /turns {call_id, text} -> {reply}`, más cómo se abre
   y se cierra la ventana de llamada. **El contrato manda; adáptate tú.**
2. Implementa un adaptador fino que, por cada `call_id`, mantenga un
   `CallContext` y un `ToolBox` (`backend/src/agent/brain/tools.py`, solo
   importar) y haga pasar el texto por el mismo cerebro y las mismas
   herramientas que usa la voz, **saltándose STT y TTS**. Al cerrar la llamada,
   el mismo `flush_call` de `agent/voice/flush.py`.
3. El agente del evaluador está documentando el contrato en
   `evaluator/README.md`. Coordínate con él por ahí.
4. Que sea **opt-in**: una variable de entorno o un router aparte. El proceso
   que atiende llamadas reales no debe montar rutas de prueba por defecto.

## Verificación

```sh
cd backend && uv run pytest -q && uv run ruff check src tests
VOICE_WS_PORT=17999 uv run --project backend python -m agent.voice.server   # nunca 7860
```

Y de punta a punta, cuando el evaluador esté listo:

```sh
uv run --project evaluator python -m evaluator.cli run --config evaluator/experiments/agent-local.yaml
```

## Aviso que te va a morder si lo ignoras

`evaluator/data/clinic_dataset.json` es una **miniatura inventada**: 6 pacientes,
7 médicos, 3 sedes, 4 planes; su propio `meta.note` dice «No es la clínica
oficial». La real tiene 12 médicos, 11 tipos de cita, 10 planes y ~3.000
pacientes. **Pasar en local valida lógica, no corrección.** No digas nunca que
un cambio "funciona" porque el banco local se puso verde.

## Reglas de la casa

- Tests y lint verdes antes de cada commit, sin excepciones.
- Nada de afirmar resultados sin evidencia: pega el comando y su salida.
- Simplicidad. Este proyecto ha mejorado más borrando código que añadiéndolo.
