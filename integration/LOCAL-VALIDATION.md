# Validación local — 19 de septiembre de 2026

Rama de trabajo: `integration/prosper-tested`, importada del bundle
`prosper-integration-tested.bundle` en `fa3c4e2`. Se actualizaron las referencias
remotas; la integración contiene los cinco heads remotos disponibles. No se ha
publicado la rama ni abierto un PR en esta sesión.

## Configuración y arranque

Se copió el `.env` de la raíz a `backend/.env` (ignorado por Git, permisos 0600).
El motor configurado es `gemini_live`. Las claves no se incluyen en este informe.
El modo cascade todavía necesita completar Helmcode y el identificador de voz
de ElevenLabs; no se ha validado ese motor con proveedores reales.

Servicios locales:

- `make agent-live`: backend de voz y Ops en 7860, con la clínica oficial.
- `npm --prefix frontend run start -- --hostname 127.0.0.1`: build de FrontDesk
  en 3000. Para desarrollo puede usarse `make frontend`.
- `ngrok http 7860`: túnel; su URL activa se puede consultar en
  `http://127.0.0.1:4040/api/tunnels`. Usar el esquema `wss://` y añadir `/ws`
  al guardar en Prosper → Settings → Integration.

`make agent` sigue siendo el target de la clínica simulada. `PUBLIC_WS_URL` no
actualiza por sí solo el endpoint guardado en la plataforma.

## Comprobaciones realizadas

| Comprobación | Resultado |
|---|---|
| Backend, después de la corrección | 407 passed, 1 skipped |
| Evaluador | 162 passed |
| Contratos entre paquetes | 4 passed |
| Ruff, ESLint, TypeScript y build Next.js | Correctos |
| Smoke de dobles | Correcto: 21 pass; incorrecto: 21 fail; silencioso: 21 fail |
| Prosper health y catálogo con las credenciales configuradas | HTTP 200; 12 profesionales |
| Gemini Live, sesión directa con el modelo y voz configurados | Conexión y 104642 bytes de audio devueltos |
| Health local y por ngrok | HTTP 200 |
| FrontDesk, búsqueda por nombre contra Prosper | HTTP 200; 10 coincidencias y 24 citas |
| Chromium, escritorio y móvil de 390 px | Validación de búsqueda, resultado vacío, error/reintento y calendario correctos; sin errores JS ni desbordamiento de página |

Las suites conservan avisos de deprecación y de corutinas de Pipecat. Las
pruebas automatizadas de voz usan dobles; la comprobación directa de Gemini
no equivale a una llamada completa por el harness de Prosper.

## Corrección descubierta frente al servicio oficial

El bundle consultaba el directorio sin filtros. La clínica local lo admitía,
pero Prosper devuelve 422: exige nombre y apellido o un identificador exacto.
FrontDesk ahora envía una búsqueda explícita, valida la entrada y carga las
citas de sus coincidencias. La agenda representa esa última búsqueda, no una
exportación de la clínica. Las llamadas se actualizan independientemente.
Se añadieron regresiones para las búsquedas vacías y los rechazos de validación.

## Primera llamada real

La primera llamada del harness terminó con audio bidireccional, herramientas,
33 entradas de transcripción, una acción enviada y cero envíos fallidos. La
API de lectura `/api/v1/submissions` confirmó una acción `BOOK`. FrontDesk
mostró el cierre y su diagnóstico. La aceptación de la acción no acredita por
sí sola que el caso haya aprobado: el veredicto pertenece a la plataforma.

El usuario inició después un Run All puntuado. Se monitoriza sin reiniciar los
servicios; sus resultados aún no forman parte de esta validación.


Corte posterior del Run All: 10:06:27 Europe/Madrid. Se observaron 24 llamadas
(incluyendo prácticas previas), 23 cerradas y una abierta; 21 envíos aceptados,
dos registros rechazados con 422 y 20 cierres con fallback por cola de acciones
vacía. Ambos registros rechazados usaban `Sanitas` en lugar de `sanitas`; uno
además incluía datos de contacto de relleno. No se modificó esa herramienta ni
se reiniciaron los servicios durante el run. El resultado puntuado sigue pendiente.

La continuidad y el reparto en nuevas sesiones están en [HANDOFF.md](HANDOFF.md).
