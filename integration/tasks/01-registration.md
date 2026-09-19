# Sesión 01 — Registro válido y fiel a los datos del caller

Lee primero `integration/HANDOFF.md`. Trabaja en una rama/worktree propio del
checkpoint local de `integration/prosper-tested`.

## Objetivo

Impedir que `register_new_patient` encole registros que el contrato rechaza o
que completen información desconocida con datos de relleno. Hay evidencia real
de un 422 con `insurer="Sanitas"` y contacto de relleno. La causa exacta completa
requiere reproducir la validación; no reenvíes la llamada real ya cerrada.

## Propiedad y coordinación

Tu área: `backend/src/agent/brain/tools.py`, validación de submissions y tests
correspondientes. Coordina cambios a `brain/prompts.py` con la sesión de voz.
No toques frontend, transporte de audio, motor ni defaults globales.

## Trabajo

- Lee `register_new_patient`, `scheduling/submit.py`, schemas/build_body,
  cliente/catálogo y `docs/prosper/api.md` / `call-contract.md`.
- Contrasta el esquema oficial mediante consultas de lectura; no hagas escrituras
  de prueba con IDs inventados a Prosper.
- Normaliza el plan contra el catálogo/enum conocido y valida formatos antes
  de encolar. Devuelve errores que permitan preguntar el dato que falta.
- Revisa cómo garantizar que teléfono/email provienen del caller; no basta con
  que una cadena parezca válida. No introduzcas datos por defecto.
- Añade regresiones sintéticas: casing/alias del seguro, plan desconocido,
  campos ausentes/de relleno, documento incorrecto y registro válido.
- Mantén el comportamiento de reservas y envíos exactamente una vez.

## Aceptación

La entrada inválida no entra en `queued_actions`; el agente puede recuperarse
pidiendo datos. Un registro correcto usa el contrato exacto. Tests de herramientas,
submission y contratos pasan. Informa qué garantías son deterministas y cuáles
siguen dependiendo del modelo. Entrega commit y comandos de validación.
