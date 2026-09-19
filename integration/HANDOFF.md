# Continuidad: Prosper integrado y primeras pruebas reales

Este es el punto de entrada para una sesión nueva de Codex, GLM, DeepSeek u otro
agente. Lee este documento antes de arrancar procesos o modificar la integración.
Los nombres de modelos no implican que se hayan lanzado sesiones adicionales.

## Objetivo del usuario y último acuerdo

Unir las ramas del reto HackSpain / Prosper AI, ejecutar voz + herramientas +
evaluador + FrontDesk y probar llamadas en la plataforma oficial. El usuario ya
lanzó llamadas y un Run All puntuado. Su última instrucción es **esperar los
cierres y la cola**, documentar el estado y preparar el reparto en otras sesiones.

No reinicies backend, frontend ni ngrok mientras haya llamadas o casos en cola.
No cambies motor, timeouts ni endpoint durante ese run. La ausencia momentánea de
sockets no demuestra que la plataforma haya terminado su cola: confirma su estado
con el usuario antes de aplicar cambios al runtime oficial.

## Checkout y punto de partida

- Directorio original: `/home/germanpadua/proyectos/hackspain/hackspain-kermit-prosper`.
- Rama: `integration/prosper-tested`.
- Bundle recibido: `prosper-integration-tested.bundle`; informe anterior:
  `prosper-integration-delivery.md`. Son archivos locales sin seguimiento Git.
- Base importada: `fa3c4e2e6872d37ff98654c8149866b18a9f54b9`.
- Se ejecutaron `git fetch --all --prune` y `git pull --ff-only` en `evaluator`
  antes de importar y cambiar a la rama de integración.
- Se verificó que HEAD incluye los heads remotos disponibles de `main`,
  `evaluator`, `voice-call-diagnostics`,
  `fix/gemini-live-turn-taking-and-clinic-tools` y `admin-ui`.
- Los cambios posteriores al bundle deben heredarse desde el checkpoint local
  de esta rama, **no volviendo a clonar únicamente el bundle**.
- Consulta `git log -1 --oneline` y `git status --short` para el checkpoint final.
  No se ha hecho push ni abierto PR.

## Servicios que se dejaron activos

| Servicio | Entrada | Proceso / función |
|---|---|---|
| FrontDesk | http://localhost:3000/calls | Build de Next.js, `npm --prefix frontend run start -- --hostname 127.0.0.1` |
| Backend integrado | http://localhost:7860/healthz | `uv run --project backend python -m agent.serve` |
| Ops | http://localhost:7860/ops | Montado por `agent.serve` en el mismo proceso |
| Voz local | ws://localhost:7860/ws | Un contexto por WebSocket |
| Túnel | `ngrok http 7860` | Mantener abierto mientras Prosper trabaja |
| Inspección ngrok | http://localhost:4040 | API de túneles en `/api/tunnels` |

Endpoint público usado en esta sesión:

```text
wss://cloak-hydrated-psychic.ngrok-free.dev/ws
```

Su health público respondió 200 y llegaron llamadas reales. Verifica la URL
activa en ngrok si el proceso se ha reiniciado. El endpoint se guarda en
**Prosper → Settings → Integration**; `PUBLIC_WS_URL` es solo configuración local.

La consola separada en 7861 no es necesaria para el stack integrado. No se dejó
una clínica del evaluador ejecutándose en 8090.

### Archivos de configuración

Se copió `.env` de la raíz a `backend/.env` con permisos 0600. El backend carga
**backend/.env**, no el archivo de la raíz. Las dos copias pueden divergir: en esta
sesión se actualizó `PUBLIC_WS_URL` solo en `backend/.env`. No publiques ninguno.

Configuración comprobada:

- `PROSPER_API_BASE_URL=https://hackspain.getprosperapp.com`.
- `VOICE_ENGINE=gemini_live`, modelo `gemini-3.8-live`.
- Gemini autentica y devuelve audio con la voz configurada.
- La API de Prosper autentica y devuelve el catálogo: 12 profesionales.
- Cascade no está listo para alternar: Helmcode y el ID de voz de ElevenLabs
  siguen teniendo valores de ejemplo. No se validó cascade con proveedores.
- Python instalado por uv: 3.13.15; Node: 22.23.2. Se usaron los lockfiles.

`make agent-live` arranca con la configuración real de `backend/.env`.
**`make agent` fuerza clínica local y `pk-local-eval`**, por diseño. No confundirlos.

## Qué cambió después del bundle

1. Se añadió `make agent-live` y documentación de ejecución contra Prosper.
2. Se corrigió un contrato del directorio: la integración anterior llamaba
   `/api/v1/directory` sin filtros, permitido por el evaluador pero rechazado por
   Prosper con 422. El servicio oficial exige nombre y apellido o un campo exacto.
3. El backend de FrontDesk acepta `name` / `national_id`; una consulta vacía
   devuelve listas vacías sin intentar exportar pacientes. Los rechazos de
   búsqueda devuelven 422 con un mensaje utilizable, sin detalles privados.
4. El proxy Next.js transmite esos filtros. La interfaz tiene búsqueda explícita,
   validación, carga, error y reintento. Un documento completo tiene prioridad
   sobre el nombre. La agenda representa la última búsqueda, no toda la clínica.
5. El refresco de llamadas (3 s) y el de búsquedas (60 s) se ejecutan por separado.
   Se cancelan solicitudes al cambiar de búsqueda o desmontar el proveedor.
6. Se añadieron regresiones y se adaptó el contrato entre paquetes a una consulta
   identificada. No se modificó aún la voz ni la herramienta de registro.

## Evidencia y límites

- `make check`: backend **407 passed, 1 skipped**; evaluador **162 passed**;
  contratos **4 passed**. Ruff, ESLint, TypeScript y build correctos.
- `make smoke`: doble correcto 21 pass; incorrecto 21 fail; silencioso 21 fail.
  Esto comprueba al evaluador, no la capacidad conversacional del agente.
- Gemini directo: conexión y 104642 bytes de audio de una frase de prueba.
- Chromium, escritorio y 390 px: búsqueda real por nombre devuelve 10
  coincidencias y 24 citas; búsqueda sin coincidencias, validación de DNI,
  error/reintento y navegación correctos. Sin errores JS ni overflow de página.
- Primera llamada real: audio bidireccional, herramientas, 33 **fragmentos** de
  transcripción, un envío aceptado. GET `/api/v1/submissions` confirmó `BOOK`.
- **200 aceptado no significa caso aprobado.** No se ha consultado el veredicto
  puntuado en la interfaz de Prosper, ni se dispone aquí de un resultado final.
- Pipecat emite avisos de deprecación, corutinas en tests y turn-taking/VAD en
  runtime. No se ocultaron. No atribuir los silencios a esos avisos sin evidencia.

### Foto parcial del Run All

Corte: **2026-09-19 10:06:27 Europe/Madrid (08:06:27 UTC)**.

- 24 llamadas observadas desde el arranque, incluyendo la primera práctica y
  otras lanzadas por el usuario; no hay una asociación fiable local caso/run.
- 23 cerradas, 1 abierta.
- 21 envíos aceptados, 2 fallidos.
- 20 cierres añadieron el fallback `NO_ACTION / out_of_scope` por cola vacía.
- En muchas llamadas solo se transcribió el saludo inicial o un «Hello» del
  interlocutor. Algunas no tienen transcripción del interlocutor.
- No se observaron excepciones de pipeline ni respuestas de límite de cuota
  de Gemini en el corte revisado.

Estos contadores NO son el total de casos puntuados ni una tasa de aprobado.
La hipótesis del usuario es silencio del simulador. Es compatible con parte de
los registros, pero la falta de transcripción no demuestra falta de audio:
queda pendiente separar audio silencioso, transporte, VAD y transcripción.

### Incidencia concreta de registro

Dos `POST /api/v1/submit/register` devolvieron 422. Ambos payloads incluían
`insurer="Sanitas"`, mientras el contrato usa `sanitas`; uno de ellos además
tenía valores de relleno en los datos de contacto. No se ha conservado el cuerpo de validación 422, así que
no atribuir con certeza todo el rechazo a un único campo.

`ToolBox.register_new_patient` valida la letra del documento, pero copia el
resto de strings y solo hace `insurer.strip()`. Todavía NO se ha corregido.
No reenviar esa acción fuera de su ventana ni corregir datos inventándolos.

## Evidencias locales y estado temporal

- Auditorías por llamada: `backend/data/calls/*.jsonl` en el checkout original.
- Backend: `/tmp/prosper-agent.log`.
- FrontDesk: `/tmp/prosper-frontend.log`.
- Ngrok: `/tmp/prosper-ngrok.log`.
- Suites: `/tmp/prosper-check.log`; smoke: `/tmp/prosper-smoke.log`.
- Informe smoke: `evaluator/experiments/results/20260919T074450Z-54ec5f/report.html`.
- Resumen local: `python3 /tmp/prosper-monitor.py` (script temporal de solo lectura).
- Prueba de navegador: `/tmp/prosper-browser/check.cjs`, Playwright instalado allí.
- Capturas: `/tmp/prosper-patients-desktop.png` y `/tmp/prosper-patients-mobile.png`.
- Comprobación de proveedores: `/tmp/prosper-provider-check.py`.

Los archivos `/tmp` no son una entrega durable. Los JSONL y logs pueden contener
identificadores, documentos y conversaciones: no copiarlos a commits, prompts
externos ni fixtures públicas. Para regresiones, sintetiza casos mínimos.
Los worktrees nuevos no heredan `.env`, dependencias, datos ignorados ni procesos.

## Reparto en sesiones independientes

Cada agente debe leer este documento y solo su tarea. Las etiquetas son por
responsabilidad; puedes usar Codex, GLM o DeepSeek en cualquiera de ellas.

| Tarea | Prioridad | Handoff | Área principal |
|---|---|---|---|
| Validación de registros | Alta | [01-registration.md](tasks/01-registration.md) | brain/tools + schemas de submission |
| Diagnóstico de silencios y concurrencia | Alta | [02-voice-diagnostics.md](tasks/02-voice-diagnostics.md) | voice/audio + auditoría |
| Fidelidad del evaluador | Media | [03-evaluator-contract.md](tasks/03-evaluator-contract.md) | evaluator y contratos |
| Observabilidad en FrontDesk | Media | [04-frontdesk.md](tasks/04-frontdesk.md) | frontend + ops/frontdesk |

No se han creado esos worktrees ni arrancado agentes adicionales. La CLI
`orca-ide skills get orca-cli --json` devolvió:
`Orca CLI is unavailable; reopen Orca or register the CLI again.`
Para crear worktrees gestionados, reabrir Orca/restaurar su CLI y usar su guía.

Prompt de entrada para copiar a cualquiera de las sesiones, sustituyendo la tarea:

```text
Lee integration/HANDOFF.md y después integration/tasks/01-registration.md.
Realiza exclusivamente esa tarea en tu worktree. Conserva el runtime y la cola
oficiales del checkout original. No publiques ni ejecutes pruebas puntuadas.
Entrega un commit, las pruebas ejecutadas y las limitaciones restantes.
```

### Cómo arrancar una sesión sin interferir con el run

1. Parte del checkpoint local actual de `integration/prosper-tested` y crea una
   rama propia. No partas de `main`, `evaluator` ni solo del bundle.
2. Asigna un handoff por sesión. Reserva `brain/tools.py` a registro y
   `brain/prompts.py` a voz; cualquier cruce debe coordinarse.
3. Instala dependencias en ese worktree. Sus `.venv` y `node_modules` son propios.
4. Prueba primero offline. Si necesitas clínica, usa el evaluador local con
   credenciales locales y puertos distintos: por ejemplo 7870/8091 para registro,
   7872/8092 para voz, 7874/8093 para evaluador y 7876/3001 para FrontDesk.
5. No publiques otro túnel ni alteres el endpoint oficial. No compitas por
   7860/3000/4040 ni escribas en `backend/data` del checkout original.
6. Entrega commit, cambios, pruebas y limitaciones. El integrador reúne cambios
   secuencialmente, ejecuta `make check` y una práctica antes del siguiente Run All.
7. Un cambio de proveedor/modelo necesita las credenciales correspondientes y
   una prueba real aislada. No confundir el modelo del agente de código con el
   motor de voz o LLM configurado dentro de la aplicación.

## Próxima acción del integrador

Esperar a que Prosper finalice el Run All y la cola; pedir al usuario el resultado
por problema y los `failure_signal` disponibles. Correlacionar con auditorías,
resolver registro y diagnosticar silencios con evidencia. Después integrar los
commits, validar y reiniciar de forma coordinada. No declarar el reto resuelto
solo porque los POST respondan 200.
