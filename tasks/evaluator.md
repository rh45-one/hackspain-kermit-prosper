# Tarea: que el evaluador sirva de verdad para probar el agente

Lee primero `PROJECT_CONTEXT.md` en la raíz. La sección 10 resume la auditoría
de este proyecto.

## Qué es tuyo

- `evaluator/**` — todo y solo esto.

**No toques `backend/` ni `frontend/`.** Hay dos agentes trabajando ahí a la vez
y el servidor de voz atiende llamadas puntuadas ahora mismo.

## Por qué importa

La plataforma solo permite **una llamada puntuada cada 12 minutos**. No se puede
iterar. Un banco de pruebas local que funcione cambia el ritmo del proyecto
entero.

Lo que ya está montado y es bueno: la clínica falsa en `127.0.0.1:18090` con la
semántica exacta del submit (404/410/409/422 con la letra del DNI re-derivada),
21 escenarios con oráculo para las 18 familias, comparador determinista,
informe ponderado y `diff` entre ejecuciones.

## El problema

**Ninguna de las dos vías funciona hoy contra el agente real.**

1. **Vía WebSocket: manda silencio.** `runner/experiment.py:_scenario_turns` —
   si el turno no trae `audio:` ni `tts: true` con `tts_command` definido, envía
   `silence(2000)`. Y verificado: no hay ni un fichero de audio en `scenarios/`,
   ningún turno pone `tts: true`, y `tts_command` está comentado en
   `experiments/agent-local.yaml:13`. El agente no oye nada y todos los casos
   salen `fail`. El escenario `noise/no-001.yaml` mezcla ruido marrón **sobre
   silencio**.

2. **Vía texto: es la buena** (paciente simulado reactivo, multi-turno) pero
   necesita `POST {text_url}/turns {call_id, text} -> {reply}`, y el backend no
   lo expone. **Ese endpoint lo está haciendo el agente del backend.** Coordínate
   con él por el contrato; no lo implementes tú.

## Qué hacer, por orden

1. **Deja la vía de texto lista para enchufar.** Documenta el contrato exacto de
   `/turns` que espera `_run_text_call` (cuerpo, respuesta, manejo de errores,
   cómo se abre y cierra la ventana de llamada) en `evaluator/README.md`, y
   verifica el camino de punta a punta contra el doble de prueba que ya existe
   en `harness/double_agent.py`.
2. **Haz real la vía de voz.** Instala `espeak-ng` o `pico2wave`, descomenta
   `tts_command` en `experiments/agent-local.yaml` y **añade `tts: true` a los
   turnos de todos los escenarios**. Sé honesto en el README sobre lo que eso
   mide y lo que no: `espeak-ng` no es una voz humana.
3. **Arregla la errata del README** (`evaluator/README.md:86`): dice
   `export PORT=17860`, y eso solo vale para `python -m agent.serve`. Con
   `python -m agent.voice.server` la variable es `VOICE_WS_PORT`.
4. **Avisa del dataset en el propio informe.** `data/clinic_dataset.json` es una
   miniatura inventada —6 pacientes, 7 médicos, 3 sedes, 4 planes— y su
   `meta.note` dice «No es la clínica oficial». La real tiene 12 médicos, 11
   tipos de cita, 10 planes y ~3.000 pacientes. Pasar en local valida **lógica,
   no corrección**. Que eso salga impreso en `report.html`, no escondido en el
   README: alguien va a confundir un verde local con un punto en el tablero.
5. Si te sobra tiempo: el check de privacidad del problema 14
   (`oracle.leak_check`) solo se evalúa si hay transcript, y el transcript solo
   se llena en la vía de texto. Por WebSocket queda inerte. Documéntalo o arréglalo.

## Verificación

```sh
uv sync --project evaluator
uv run --project evaluator python -m evaluator.cli run --config evaluator/experiments/smoke.yaml
uv run --project evaluator --locked pytest -c evaluator/pyproject.toml evaluator/tests -q
```

## Regla de oro, operativa

**No apuntes nunca el evaluador al puerto 7860.** Esa instancia tiene el túnel
ngrok registrado en el dashboard de Prosper y recibe llamadas puntuadas de
verdad; meterle tráfico de pruebas puede tumbar una. Tal como viene apunta al
17860, que es lo correcto. Déjalo así.
