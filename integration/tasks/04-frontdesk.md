# Sesión 04 — Observabilidad útil de llamadas en FrontDesk

Lee `integration/HANDOFF.md` y `frontend/AGENTS.md` antes de tocar Next.js.
Usa worktree y puertos propios. El frontend original sirve al usuario durante
el run; no lo reinicies ni alteres sus archivos de build.

## Estado de partida

Llamadas y transcripciones se consultan cada 3 s. Directorio y agenda ya usan
búsqueda explícita contra Prosper, validación y reintento; conservarlo. La API
oficial no permite exportar pacientes con una consulta vacía.

## Objetivo

Hacer que el operador distinga una llamada abierta, un cierre sin acción, un
rechazo de envío y un resultado aceptado. No mostrar «aprobado» por HTTP 200:
la aplicación aún no tiene el veredicto puntuado de Prosper ni el estado de cola.

## Propiedad y trabajo

- `frontend/`, `backend/src/agent/ops/frontdesk.py` y sus pruebas.
- Leer los diagnósticos existentes (`queued_action_count`, `fallback_action_added`,
  `empty_action_reason`, `submissions_succeeded`, `submissions_failed`, `stages`).
- Priorizar indicadores explícitos de fallback/rechazo. «Sin transcripción» no
  equivale a «caller silencioso» sin métricas de entrada.
- Las transcripciones son fragmentos streaming: no confundir fragmentos con
  turnos completos ni inventar cambios de hablante.
- El estado activo actual se infiere del registro y su edad; etiquetarlo con
  precisión. Coordinar métricas nuevas con la sesión de voz.
- Mantener frontend en lectura para clínica real, mocks solo en demo y errores
  visibles. No añadir controles de takeover o guardado sin APIs reales.
- Probar búsqueda/ficha/agenda, errores/reintento, datos de llamada, vista móvil
  y ausencia de datos. Aplicar las guías locales de React/Next/UI.

## Aceptación

Validación de TypeScript, ESLint y build; comprobación de navegador con datos
sintéticos aislados y estados reales disponibles de solo lectura. Sin regresión
del directorio ni exposición de claves. Entregar commit, capturas apropiadas y
limitaciones, sin atribuir puntuaciones no recibidas de Prosper.
