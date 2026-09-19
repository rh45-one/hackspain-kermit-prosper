# Agente + evaluador + FrontDesk

La rama de integración reúne `fix/gemini-live-turn-taking-and-clinic-tools`,
`voice-call-diagnostics`, `evaluator` y `admin-ui` sobre `main`.

## Instalación y pruebas sin proveedores externos

Desde la raíz, con Python 3.12, uv y Node >=20.9:

```sh
make setup
make check
make smoke
```

`make check` ejecuta las suites originales, pruebas de contrato entre paquetes,
Ruff, ESLint, TypeScript y el build de Next.js. Las pruebas de contrato arrancan
la clínica y el backend en puertos locales libres y prueban:

- identificación → disponibilidad → reserva → envío exactamente una vez →
  registro del evaluador → comparación con el resultado esperado;
- caller WebSocket del evaluador → servidor real del agente → stop →
  fallback por silencio → diagnóstico en FrontDesk;
- lectura del directorio y agenda usando el cliente real del backend;
- rechazo del receptor o del esquema → contador de fallo, nunca de éxito.

La reserva invoca las herramientas directamente. En la prueba WebSocket los
servicios STT/LLM/TTS están desactivados. Esto verifica contratos y transporte,
no comprensión del habla, latencia de proveedores ni calidad de conversación.
La prueba de reserva fija el reloj al escenario de septiembre de 2026.

`make smoke` prueba el evaluador con dobles, no el agente. El resultado esperado
es: doble correcto aprueba; dobles mutado y silencioso fallan. Los informes
quedan en `evaluator/experiments/results/<run>/`.

## Stack interactivo local

En tres terminales, desde la raíz:

```sh
make clinic
```

```sh
make agent
```

```sh
make frontend
```

Puertos:

| Servicio | URL |
|---|---|
| FrontDesk | http://localhost:3000/calls |
| Backend combinado | http://localhost:7860/healthz |
| Voz | ws://localhost:7860/ws |
| Ops | http://localhost:7860/ops |
| Clínica local | http://localhost:8090/api/v1/health |

`make agent` apunta explícitamente a la clínica local y a su clave de prueba
`pk-local-eval`; no envía acciones a la plataforma oficial. La UI funciona sin
claves de voz. `agent.voice.server` por sí solo no monta las rutas de Ops usadas
por FrontDesk: el entrypoint de integración es `agent.serve`.

FrontDesk está en modo backend por defecto. Opcionalmente copia
`frontend/.env.example` a `frontend/.env.local`; `AGENT_HTTP_BASE_URL` se lee en
el servidor Next.js. `FRONTDESK_DEMO=true` activa los mocks y las interacciones
locales originales.

El panel muestra las últimas 30 llamadas de `backend/data/calls`, las
transcripciones y los contadores de envío. El estado activo se infiere de los
eventos y su antigüedad, no de una conexión de audio del navegador. Los logs sin
cierre que exceden el límite de llamada aparecen como desconocidos. El directorio
y la agenda reflejan el EHR configurado; el receptor de submissions guarda acciones
para evaluación y **no cambia las citas del EHR**.

Los ajustes y la toma manual de llamadas solo funcionan en demo. En backend
se configuran motores y proveedores con `backend/.env`. No hay API de escritura
de ajustes o control de llamada. Estos paneles heredan el acceso local de Ops;
no se han añadido autenticación ni un despliegue público.

## Llamada con proveedores reales

Configura `backend/.env` siguiendo `backend/.env.example` y `backend/README.md`:
`VOICE_ENGINE=gemini_live` necesita Gemini; `cascade` necesita STT, LLM y TTS.
No hay fallback silencioso entre motores. Jev y los proveedores opcionales
requieren sus propias claves si se habilitan.

El runner de experimentos **arranca su propia clínica**. Detén `make clinic`
antes de ejecutar `evaluator/experiments/agent-local.yaml`; usa `make agent`
apuntando al mismo puerto 8090. No arranques dos clínicas: además del conflicto
de puerto, el registro de llamadas debe pertenecer al mismo proceso receptor.

La plantilla `agent-local.yaml` no constituye una prueba de voz lista para usar:
los turnos sin `audio` o sin `tts: true` se transmiten como silencio. Para voz,
prepara un escenario con audio µ-law 8 kHz o habilita `tts: true` en sus turnos
y `tts_command: espeak-ng` con el binario instalado. Verifica en la evidencia
que existe audio del caller: si TTS falla, el evaluador actual cae a silencio.
El agente externo tampoco hereda automáticamente `reference_now` del experimento;
ajusta escenario/fixture a las fechas de ejecución.

```sh
uv run --project evaluator python -m evaluator.cli validate \
  --dataset evaluator/data/clinic_dataset.json \
  --scenarios 'evaluator/scenarios/**/*.yaml'
uv run --project evaluator python -m evaluator.cli run \
  --config evaluator/experiments/agent-local.yaml
```

## Diferencias relevantes de la integración

La clínica local selecciona `appointment_type` por especialidad e historial
cuando el agente no lo pasa. Los tipos específicos tienen prioridad sobre
`first_visit`/`review`; sin paciente se usa historial de revisión como
aproximación local. Los slots y el tipo seleccionado coinciden. La clínica
continúa siendo una aproximación del contrato oficial.

`Submitter.post_route` lanza un error si la acción no fue aceptada, para que
`flush_call` registre correctamente los fallos. Los detalles privados del
proveedor no se devuelven en los errores de FrontDesk.
