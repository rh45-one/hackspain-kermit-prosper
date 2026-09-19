# Tarea: espejo local de la clínica, en Docker, con autocarga

Lee `PROJECT_CONTEXT.md` entero antes de tocar nada.

## Qué se quiere

Una plataforma donde ver el bot funcionando con **todos los datos de la
clínica**, sin depender de la API de Prosper para cada arranque. Y con la
puerta abierta a varias clínicas después: hoy una, mañana por tenant.

## Lo que YA he comprobado, para que no lo repitas

```
GET /api/v1/clinic     200 · 30 KB  → catálogo ENTERO. Volcable.
GET /api/v1/providers  200 · 11 KB  → volcable
GET /api/v1/directory  422 "directory query needs a name (given name plus at
                             least one surname)"
```

**Los 2.900 pacientes NO se pueden volcar.** El directorio es un buscador, no
un listado: exige nombre y apellido. No hay forma de enumerarlos y no se te
ocurra intentar sacarlos a fuerza bruta — es un endpoint de un reto en curso,
con nuestra clave, y machacarlo es la forma más rápida de que nos la quiten.

Así que el espejo contiene:

- **Catálogo completo y exacto**: 12 médicos, 6 especialidades, 11 tipos de
  cita, 10 planes, las sedes, el calendario publicado, la matriz de coberturas.
  Esto es lo que el agente razona, y es lo valioso.
- **Disponibilidad**: consultable por médico o especialidad en ventanas de
  **máximo 14 días**. Volcable por tramos si se quiere.
- **Pacientes: solo los que ya hemos visto.** Hay 172 trazas en
  `backend/data/calls/*.jsonl` con nombres, fechas de nacimiento y aseguradoras
  de pacientes reales del reto, y de ahí sale un directorio parcial legítimo:
  son datos que la plataforma ya nos dio a nosotros.

## Qué hacer

1. **Volcador.** Un comando que pida el catálogo a Prosper y lo deje en disco,
   versionado con fecha y con el hash de lo descargado. Que falle ruidosamente
   si la forma cambia, en vez de escribir basura.
2. **Docker de base de datos con autocarga.** Levanta y ya tiene los datos
   dentro, sin pasos manuales. Postgres o SQLite, tú eliges: justifica cuál y
   por qué, contando que esto acaba en Fly.
3. **Servidor que hable el contrato de Prosper.** Los mismos paths, las mismas
   formas, los mismos códigos de error — incluido el **422 del directorio sin
   nombre** y el **tope de 14 días** de disponibilidad. Si nuestro agente no
   nota la diferencia entre el espejo y el original, está bien hecho.
4. **Un interruptor**: `PROSPER_API_BASE_URL` apuntando al espejo y el agente
   funciona igual. Eso es todo lo que debería hacer falta.
5. **Por clínica desde el principio en el ESQUEMA**, aunque hoy solo haya una.
   Meter un tenant después es mucho más caro que dejarle el hueco ahora.

## Habla con el agente del evaluador antes de escribir nada

En `evaluator/` **ya existe una clínica falsa** (`src/evaluator/clinic/server.py`)
que sirve el contrato de lectura Y el receptor de `/submit` con su semántica
exacta: 404 llamada desconocida, 410 fuera de ventana, 409 repetida, 422 con la
letra del DNI re-derivada. Su limitación es el dataset: una miniatura de 6
pacientes y 7 médicos que su propio `meta.note` llama «no es la clínica
oficial».

**Lo más probable es que esto sea "dale datos reales a lo que ya existe" y no
un proyecto nuevo.** Habla con `evaluator-bench-1b` por SendMessage antes de
escribir una línea, y si resulta que el camino es extender lo suyo, hazlo así y
dilo. Dos clínicas falsas en el mismo repositorio sería el peor resultado.

## Reglas

- Solo `backend/` y lo que acordéis en `evaluator/`. Nada de `frontend/`.
- **Nunca arranques ni reinicies nada en el puerto 7860.** Ahí hay un túnel
  registrado en la plataforma recibiendo llamadas puntuadas de verdad.
- Los datos de paciente que saques de las trazas llevan DNI y teléfono. Si eso
  acaba en una imagen de Docker que alguien comparte, es una fuga aunque los
  datos sean sintéticos. Decide dónde viven y déjalo escrito.
- Tests y lint verdes antes de cada commit. Nada de afirmar resultados sin
  pegar el comando y su salida.
