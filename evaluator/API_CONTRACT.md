# Contrato HTTP del laboratorio

Versión: **v1**. La consola usa exclusivamente estas rutas locales. Todos los
errores tienen la forma `{"detail": "mensaje seguro"}` y nunca repiten valores
de credenciales, rutas internas ni destinos proporcionados por el cliente.

## Convenciones

- Las listas paginadas responden `{items, page, page_size, total, next_page}`.
  `page` empieza en 1; `page_size` está entre 1 y 100; `next_page` es `null` al
  final. Los filtros se aplican antes de calcular `total`.
- La disponibilidad de evidencia es `present`, `absent` o `unknown`. Un valor
  ausente nunca se convierte en cero, silencio ni una transcripción inventada.
- Los perfiles se seleccionan por `profile_id`. El navegador no envía URLs,
  comandos, rutas de escenarios ni directorios de auditoría.

## Rutas ya disponibles

| Método y ruta | Respuesta | Notas |
| --- | --- | --- |
| `GET /healthz` | estado del servidor | Local solamente. |
| `GET /api/profiles` | perfiles declarados | Incluye capacidades y rechazos de laboratorio, sin secretos. |
| `GET /api/runs` | lista de runs heredada | Se conserva por compatibilidad; el histórico v1 está abajo. |
| `GET /api/runs/{run_id}` | manifiesto, métricas y comparación | Manifiesto redactado. |
| `GET /api/runs/{run_id}/cases` | casos del run | Compatible con artefactos antiguos. |
| `GET /api/diff?a=&b=` | diff de dos runs | Admite candidatos opcionales. |
| `POST /api/chat` | sesión manual | Usa `profile_id`; `say`, `say-audio` y `close` siguen bajo `/api/chat/{id}`. |

## Histórico v1

### `POST /api/history/import`

Importa auditorías desde raíces declaradas en el servidor. Por ahora solo admite
`{"source": "runs"}` para indexar artefactos ya presentes bajo `results_root`.
La misma importación es idempotente.

Respuesta `202`:

```json
{"indexed": 21, "created": 0, "updated": 0, "skipped": 21}
```

### `GET /api/history/calls`

Filtros opcionales: `origin` (`simulated`, `real`, `manual`), `candidate`,
`version`, `verdict` (`pass`, `fail`, `invalid_evaluation`, `unknown`),
`scenario_id`, `from`, `to`, `include_doubles` (por defecto `false`), `page` y
`page_size`.

```json
{
  "items": [{
    "id": "simulated:run-1:baseline/sb-001/r0",
    "origin": "simulated",
    "candidate": "baseline",
    "candidate_version": "lab-1",
    "verdict": "pass",
    "evaluated": true,
    "started_at": "2026-09-19T17:00:00+00:00",
    "evidence": {"transcript": "present", "audio": "absent", "cost": "present"}
  }],
  "page": 1, "page_size": 25, "total": 1, "next_page": null
}
```

### `GET /api/history/calls/{record_id}`

`record_id` es el identificador opaco devuelto por la lista; el `call_id` del
agente puede repetirse entre orígenes. Devuelve la llamada completa: identidad, resultado, acciones, transcripción
ordenada por `seconds` cuando existe, evidencias y vínculos `run_id`/`case_id`.
Si la fuente solo contiene fragmentos, se devuelve como `transcript_fragments`
sin fingir turnos. `404` para una llamada inexistente.

### `GET /api/history/summary`

Acepta los mismos filtros que la lista y devuelve población, éxito únicamente
sobre llamadas evaluadas, cobertura de coste/audio/transcripción y agregados.
Dobles quedan excluidos por defecto.

## Trabajos de experimento v1

### `GET /api/scenarios`

Devuelve los escenarios declarados por el servidor como `{id, problem_id,
split}`. El navegador usa el `id` en `POST /api/jobs`; no envía rutas YAML.

### `POST /api/jobs`

```json
{
  "profile_ids": ["double"],
  "scenario_ids": ["baseline/sb-001"],
  "mode": "text",
  "repetitions": 1
}
```

El servidor valida perfiles, escenarios y límites antes de crear el trabajo.
No acepta comandos ni endpoints. Responde `202` con el trabajo `pending`.

### `GET /api/jobs` y `GET /api/jobs/{job_id}`

Estados: `pending`, `preparing`, `running`, `cancelling`, `completed`,
`failed`, `cancelled`. La respuesta incluye progreso
`{"completed": 1, "total": 3}`, `run_id` cuando exista, y evidencia parcial.
Tras un reinicio, un trabajo que estuviera activo se declara `failed` con motivo
`"servidor reiniciado"`; nunca queda activo indefinidamente.

### `POST /api/jobs/{job_id}/cancel`

Marca una solicitud de cancelación. Responde `202` con `cancelling`, o `409` si
el trabajo ya es terminal. Los casos terminados y el directorio de resultados
se conservan.

## Comparación v1

### `GET /api/comparisons`

Parámetros `run_id` (requerido), `candidate` (repetible) y `include_cases`
(booleano). Devuelve la tabla existente, tamaño de muestra por candidato y
estabilidad si hay repeticiones. Con una repetición responde
`"stability": {"available": false, "reason": "se requieren repeticiones"}`.

## Compatibilidad

Las rutas de runs y chat no cambian. El índice se puede reconstruir a partir de
`cases.jsonl`, `manifest.json` y `real_calls.jsonl` antiguos; los campos que no
existían se expresan como `unknown` o `null`. Esta versión no migra ni reescribe
artefactos previos.
