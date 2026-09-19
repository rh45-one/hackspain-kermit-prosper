# Evaluator: laboratorio interno de desarrollo

## Alcance y revisión inicial

Base revisada: `767cc7f`, sincronizada con `origin/main` el 19 de septiembre de
2026. Todos los cambios de implementación, configuración, documentación y tests
se limitan a `evaluator/`. Backend y frontend son referencias de lectura.

El producto debe ayudar a decidir qué versión del agente funciona mejor,
explicar sus fallos y reproducir una conversación. No es un tablero comercial
ni el scorer oficial.

Verificación de la base: **418 tests pasan, 1 omitido**, en 314 segundos;
Ruff pasa. Se registran dos avisos de deprecación de dependencias. No se ha
ejecutado todavía una campaña con proveedores reales ni una revisión visual
en navegador. Esta entrega contiene el análisis y el plan, no implementación.

### Lo que ya funciona como base

- API FastAPI y consola estática sin compilación, con fuentes locales.
- 21 escenarios, clínica simulada, comparador determinista, experimentos con
  varios candidatos y repeticiones, informes y diferencias entre ejecuciones.
- Métricas de éxito, latencia, audio, interrupciones, errores, estabilidad y
  coste cuando el agente lo comunica.
- Observador post-hoc del audit del backend y evidencia de llamadas reales.
- Prueba manual mediante texto sintetizado y micrófono push-to-talk.
- Personas por reglas y LLM compatible con chat completions en la vía de texto.
- Backend externo con motores `gemini_live` y `cascade`; la cascada existente
  usa Deepgram, Helmcode y ElevenLabs. No hace falta duplicar el agente.

### Carencias verificadas en el código

- La consola gira alrededor de una sola ejecución; falta un histórico global
  filtrable y una vista general con tendencias y procedencia.
- La API no permite crear, seguir ni cancelar experimentos.
- Los candidatos se configuran en YAML; la prueba manual pide endpoints y
  rutas en vez de seleccionar un perfil conocido.
- El observador concatena fragmentos por interlocutor: pierde el orden de la
  conversación en su representación actual y no incorpora grabaciones reales.
- La comparación muestra resultados, pero falta inspeccionar las dos
  conversaciones y sus acciones desde el mismo escenario.
- La persona LLM es reactiva por texto; el runner de voz reproduce un guion.
- La prueba manual sube audio por turnos; no constituye una conversación
  simultánea con reproducción continua e interrupciones naturales.
- No se puede asumir que toda llamada tiene coste, transcripción, grabación o
  un resultado esperado. La interfaz debe mostrar esa cobertura.

## Diseño de producto

Mantener la identidad del proyecto: papel cálido, grafito, latón, acentos
naranja, marca Pronto y fuentes locales. Priorizar densidad legible, tablas,
filtros persistentes y acceso directo a evidencia. Conservar FastAPI y JS/CSS
sin framework; separar el JS por responsabilidades cuando se amplíe.

Navegación propuesta:

1. **Resumen**: candidato y periodo; volumen, éxito evaluado, errores técnicos,
   latencia de respuesta p50/p95, duración y coste conocido. Tendencias con
   acceso a las llamadas que forman cada agregado.
2. **Llamadas**: histórico de reales, simuladas y manuales, filtros por fecha,
   agente, origen, resultado y escenario; detalle con conversación cronológica,
   audio, herramientas, submissions y diagnóstico.
3. **Experimentos**: elegir perfiles, escenarios/personas, modalidad y
   repeticiones; validar, iniciar, observar progreso y cancelar.
4. **Comparar**: dos o más candidatos, resultado por escenario/persona,
   diferencias de latencia/coste, estabilidad y exploración de desacuerdos.
5. **En vivo**: seleccionar agente, comprobar disponibilidad, hablar o escribir,
   ver conversación y guardar la sesión en el histórico.
6. **Agentes y personas**: perfiles, capacidades, versiones y configuración
   no secreta; referencias a credenciales del servidor y estado de preparación.

Estados comunes: sin datos, carga, error recuperable, proveedor no disponible,
ejecución parcial/cancelada y evidencia ausente. Navegación por teclado, foco
visible, estados anunciados, reflow móvil y tablas desplazables.

## Plan de implementación y criterios de aceptación

### P0 — Contratos de evidencia y perfiles

Rutas principales: `models.py`, nuevos módulos de perfiles y almacenamiento,
`api/`, `tests/`, configuración de ejemplo dentro de `evaluator/`.

- Definir perfiles declarativos con ID, motor, versión, endpoints, capacidades
  de texto/voz, referencias a variables de entorno y metadatos de proveedores.
- Perfiles iniciales Gemini Live y cascada usando el backend existente como
  proceso externo. Verificar argumentos y variables reales antes de fijar el
  launcher. Clínica, audit y puertos separados de producción.
- Permitir únicamente perfiles de arranque predefinidos en el servidor;
  ninguna petición del navegador puede aportar un comando de shell.
- Esquema común de llamada y eventos con origen, candidato/versionado, tiempos,
  disponibilidad de evidencia y vínculos al run/caso original.
- Compatibilidad de lectura con runs antiguos. Credenciales nunca en JSON de
  API, manifiestos, errores públicos ni navegador. Artefactos locales ignorados
  mediante reglas dentro de `evaluator/`.

Aceptación: cargar artefactos antiguos, detectar perfiles incompletos, impedir
el puerto 7860 y destinos oficiales para ejecuciones del laboratorio, y probar
aislamiento entre sesiones sin depender de proveedores pagados.

### P1 — Histórico y resumen real

Rutas: `observer/`, `report/metrics.py`, `api/`, `web/`.

- Indexar artefactos existentes e importar audit de manera incremental e
  idempotente. Deduplificar llamadas observadas en varias importaciones.
- Conservar eventos de transcript en orden con timestamp y rol; no inventar
  separación de turnos donde el origen solo proporciona fragmentos.
- Descubrir grabaciones mediante configuración explícita y el contrato real
  del backend; servir solo ficheros contenidos en las raíces autorizadas.
  Si no existe una grabación, mostrar «audio no disponible».
- Filtros, paginación, detalle y reproductores de audio por dirección.
- Agregados por periodo, candidato, versión y origen. Calcular percentiles
  desde muestras, no promediando percentiles de ejecuciones.
- Éxito solo sobre llamadas evaluadas; costes con cobertura y moneda; distinguir
  latencia de texto, primer audio y respuesta por turno. No mezclar dobles con
  resultados de modelos reales por defecto.

Aceptación: una llamada importada dos veces cuenta una vez; transcript conserva
orden; filtros y métricas comparten población; audio ausente no aparece como
silencio ni dato cero; archivos corruptos no tumban todo el histórico.

### P2 — Ejecuciones controladas desde la consola

Rutas: `runner/`, nueva gestión de trabajos, `api/`, `web/`.

- Crear una especificación validada de experimento usando IDs de perfiles,
  escenarios/personas, modalidad, repeticiones y límites.
- Ciclo de trabajo persistente: pendiente, preparando, ejecutando, cancelando,
  completado, fallido o cancelado. Progreso por caso y candidato.
- Reutilizar el runner y sus resultados; conservar evidencia parcial. Capturar
  configuración, revisión del código, hashes de dataset/escenarios/personas y
  configuración efectiva de proveedores sin secretos.
- Gestionar readiness, puertos ocupados, exclusión de clínica compartida y
  limpieza de procesos propios. Reiniciar la consola no debe mostrar trabajos
  huérfanos como activos indefinidamente.
- Límites de casos, turnos, tiempo y concurrencia. El límite monetario requiere
  telemetría suficiente: no prometer un tope exacto con consumo desconocido.

Aceptación: iniciar/cancelar desde el navegador contra dobles, conservar los
casos terminados, liberar recursos y continuar leyendo los informes por CLI.

### P3 — Personas y comparación de comportamiento

Rutas: `simulator/`, `scenarios/`, `runner/`, `report/side_by_side.py`, `web/`.

- Catálogo de personas reutilizables: colaborativa, dubitativa, impaciente,
  correctora de datos, multilingüe e interruptora; escenarios siguen definiendo
  hechos y resultado esperado por separado.
- Mantener reglas deterministas para regresión rápida. Versionar prompt,
  modelo, temperatura y semilla de personas LLM. Registrar fallbacks y excluir
  o segmentar comparaciones degradadas; una semilla no garantiza determinismo.
- Validar cumplimiento de hechos y comportamiento del simulador; el prompt por
  sí solo no garantiza que la persona no invente datos.
- Añadir circuito de voz reactivo: respuesta audible del agente → transcript
  disponible/STT → persona → TTS → siguiente turno. Distinguir latencia del
  agente de latencia añadida por el simulador.
- Ejecutar candidatos sobre los mismos escenarios, perfiles de persona y
  repeticiones, con orden intercalado. La conversación puede divergir; el
  contexto de evaluación debe permanecer equivalente.
- Comparación lado a lado con audio, conversación, acciones, errores y
  comprobaciones omitidas. Mostrar tamaño de muestra y variabilidad; evitar
  declarar ganador con una sola ejecución.
- Comprobaciones explícitas de registro en dos fases, cambios de datos que
  invalidan confirmación y no lectura de DNI/teléfono. Los oráculos nunca
  llegan al agente ni a la persona.

Aceptación: matriz Gemini/cascada sobre personas seleccionadas; resultados
pareados reproducibles contra dobles; fallback visible; escenario de
interrupción comprueba que el agente vuelve a hablar, además de frames de 20 ms.

### P4 — Conversación manual con cada candidato

Rutas: `api/chat.py`, `harness/wsclient.py`, `web/mic-worklet.js`, `web/`.

- Selector de perfil con preflight: agente, clínica, TTS, STT y micrófono.
- Preservar texto y push-to-talk como modalidades explícitas. Añadir transporte
  navegador-servidor bidireccional para audio continuo y cancelación de
  reproducción cuando el usuario interrumpe.
- Evitar transmitir silencio acumulado o reproducir audio de una respuesta
  cancelada. Limpiar micrófono, socket y contexto de audio al terminar.
- Registrar sesión, eventos, audio y métricas en el mismo histórico, incluso
  ante cierre abrupto. Evaluar solo cuando se seleccionó un escenario adecuado.

Aceptación: probar ambos perfiles, hablar-interrumpir-volver a escuchar,
reconectar tras error y abrir la sesión guardada. Sin credenciales, mostrar
configuración pendiente; una prueba con dobles no certifica un modelo real.

### P5 — Integración visual, pruebas y entrega

- Implementar las pantallas progresivamente sobre contratos estables, manteniendo
  la identidad visual de frontend sin editarlo ni añadir dependencias cruzadas.
- Tests de integración de perfiles, trabajos, importación, agregados, evidencia,
  personas y chat; regresiones existentes del evaluador.
- Smoke completo sin gasto con dobles; prueba real acotada cuando proveedores
  y presupuesto estén configurados. No comprar servicios para construir la UI.
- Revisión visual desktop/móvil, teclado, permisos de micrófono y estados vacíos.
- README con arranque único, perfiles, configuración de proveedores y límites
  comprobados. Entrega diferenciando funcionalidades verificadas con dobles y
  verificadas con agentes reales.

Comandos base:

```sh
uv run --project evaluator --locked pytest -c evaluator/pyproject.toml evaluator/tests -q
uv run --project evaluator --locked ruff check evaluator/src evaluator/tests
uv run --project evaluator python -m evaluator.cli run --config evaluator/experiments/smoke-text.yaml
```

## Delegación propuesta mediante Orca

El lead fija contratos y revisa integración. Tras P0, dos trabajadores pueden
avanzar de forma independiente: histórico/métricas y jobs/perfiles. Un tercero
puede construir la UI sobre esos contratos, con propiedad exclusiva de `web/`.
P3 y P4 comienzan cuando jobs/perfiles están integrados; no asignar el mismo
archivo a dos trabajadores simultáneos.

Pi con DeepSeek es adecuado para tareas acotadas: tests de contratos, catálogo
de personas, documentación y pantallas con API cerrada. La configuración de
nan.builders se comprobará por disponibilidad sin mostrar claves. Cada tarea
debe incluir archivos permitidos, resultado observable y comando de validación.
No se han iniciado trabajadores durante esta revisión inicial.

### NaN/Pi: configuración revisada

Documentación consultada el 19 de septiembre de 2026:
https://nan.builders/docs/models y https://nan.builders/docs/pi.
Pi está instalado; su proveedor `nan` usa `https://api.nan.builders/v1`,
`openai-completions` y `supportsDeveloperRole: true`. Tiene configurados los
siete modelos de la guía y usa `glm5.3-flash` por defecto. Hay credenciales
locales presentes; no se han copiado al repositorio ni modificado.

- Trabajadores Pi: seleccionar explícitamente `deepseek-v4-flash` conforme a la
  preferencia del usuario. La guía propone `glm5.3-flash` para programación;
  puede ser una alternativa para tareas que necesiten razonamiento ajustable.
- DeepSeek tiene razonamiento adaptativo: `reasoning_effort` no reduce su
  profundidad. No prometer menor latencia por seleccionar `low`.
- Personas: evaluar DeepSeek o GLM Flash con límites de turnos y tokens,
  registrando el modelo efectivo por ejecución.
- Audio del simulador: NaN publica Kokoro TTS (voces españolas, 15 RPM) y
  Whisper STT (10 RPM, aproximadamente tiempo real en CPU). Son candidatos
  para pruebas por turnos y análisis; esas cifras no acreditan voz interactiva
  de baja latencia. Cambiar los proveedores de audio del agente externo sigue
  sujeto a las capacidades existentes del backend.
- `glm5.3` requiere membresía premium; estar en el catálogo local no prueba
  que la cuenta tenga acceso.

Una consulta autenticada de solo lectura a `/v1/models` devolvió HTTP 403.
La configuración está revisada, pero falta verificar inferencia efectiva y
cuotas de esta cuenta; ese resultado no identifica por sí solo la causa.

## Decisiones pendientes que no bloquean la base

- Catálogo y cuotas efectivas de Helmcode; qué credenciales de STT/TTS existen.
- Presupuesto máximo de las ejecuciones reales. Hasta conocerlo, validar con
  dobles y dejar perfiles reales configurables sin lanzar campañas pagadas.
- Ubicación/formato de grabaciones históricas: inspeccionar el contrato de
  almacenamiento antes de implementar su conexión; nunca fabricar audio.

Orden de entrega: P0 → P1/P2 → P3/P4 → P5. La primera entrega útil es resumen,
histórico con evidencia y selector de candidatos; la evaluación por personas
reactivas y el audio simultáneo son entregas posteriores con pruebas propias.
