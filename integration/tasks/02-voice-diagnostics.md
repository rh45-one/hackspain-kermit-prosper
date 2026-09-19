# Sesión 02 — Distinguir silencio del caller de fallos de audio

Lee `integration/HANDOFF.md`. Usa un worktree propio; no modifiques ni reinicies
el runtime oficial mientras el usuario espera la cola de Prosper.

## Objetivo

Explicar los cierres sin acción del Run All con evidencia. Varias llamadas solo
muestran saludo o «Hello». El usuario sospecha silencio del simulador. Es una
hipótesis, no un diagnóstico confirmado. La primera llamada sí acabó en BOOK
aceptado con audio bidireccional.

## Propiedad

`backend/src/agent/voice/`, `audio/`, `brain/prompts.py` y sus tests. Coordina cambios
con registro si necesitas `brain/tools.py` y con FrontDesk si amplías diagnósticos.

## Trabajo

- Lee `twilio.py`, `gemini_live.py`, `pipeline.py`, `context.py` y `flush.py`.
- Correlaciona tiempo de conexión, primer audio entrante, energía/silencio,
  VAD, transcripción, audio saliente, stop/desconexión y fallback.
- Los JSONL históricos no guardan necesariamente audio o niveles: declara lo
  que no puede inferirse retrospectivamente. No inventes métricas ausentes.
- Si falta evidencia, añade contadores baratos por socket sin guardar audio ni
  secretos por defecto. Diseña pruebas de entrada silenciosa vs audio audible.
- Reproduce con clínica local y grabaciones sintéticas, primero un socket y
  después 10/20. Verifica aislamiento y carga, no solo handshake.
- Revisa los avisos de turn frames/VAD y cambio de idioma sin asumir causalidad.
- No alargues timeouts a ciegas, ni conviertas todos los fallos en otra acción.
  Respeta `start.callSid` y la ventana de envío de 30 segundos tras el cierre.

## Aceptación

Informe con hechos, hipótesis y próximos experimentos separados. Si hay cambio,
regresiones que fallen con el comportamiento anterior y pasen con el nuevo.
Distingue cierre normal sin habla, fallo de proveedor y fallo de procesamiento.
Entrega commit + métricas, sin publicar conversaciones ni audio del usuario.
