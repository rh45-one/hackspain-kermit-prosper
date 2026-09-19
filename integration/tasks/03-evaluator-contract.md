# Sesión 03 — Alinear evaluador local y contrato oficial

Lee `integration/HANDOFF.md`. Trabaja solo en `evaluator/`, contratos y fixtures
sintéticas; coordina cualquier cambio de interfaz con el integrador.

## Problema verificado

El evaluador dejaba exportar el directorio con una consulta vacía y las pruebas
pasaban. Prosper exige nombre y apellido o un campo exacto y devuelve 422 sin
ellos. Esa divergencia ocultó un fallo real de FrontDesk.

## Objetivo y trabajo

- Contrasta búsquedas, enums, payloads de registro, disponibilidad y respuestas
  de submission con la documentación/esquema oficial actual, usando solo lectura.
- Reproduce primero la diferencia del directorio en una prueba de contrato.
- Alinea el comportamiento del evaluador cuando esté demostrado. Documenta las
  aproximaciones restantes; no inventes el contenido de los casos privados.
- Revisa semántica de HTTP 200/409/410/422, enum de aseguradoras y ventana de 30 s.
- Conserva casos correctos, incorrectos y silenciosos del smoke con sus veredictos
  esperados. No ajustes fixtures para esconder divergencias.
- Ten en cuenta que el runner arranca su propia clínica: no colisionar en 8090.
- La plantilla `agent-local.yaml` emite silencio si no hay audio/TTS; no usarla
  como prueba de comprensión de voz sin preparar audio y verificar su emisión.

## Aceptación

Tests del evaluador y contratos cruzados pasan. Tabla breve de divergencias
corregidas y limitaciones restantes. Smoke correcto=21 pass, incorrecto=21 fail,
silencioso=21 fail (o justificación explícita si cambia el corpus). Commit propio.
