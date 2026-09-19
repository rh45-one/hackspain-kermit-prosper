# La plataforma: varias clínicas, un bot por cada una, y un grafo que sabe a quién llamar

Escrito el 19 sep 2026 a las 21:00, con el agente ya desplegado y puntuando.
Esto es lo que hay, lo que falta, y cuánto cuesta cada pieza. Nada de aquí está
construido salvo donde dice **hecho**.

---

## 1. Lo que ya existe y hay que saber antes de diseñar nada

**Hecho:** el agente atiende llamadas reales en
`wss://prosper-clinicreflow.fly.dev/ws`, con su consola en `/ops` detrás de un
token, y el panel en Vercel leyendo de ella.

**Hecho:** el grafo de la clínica se calcula del catálogo
(`agent/clinic/graph.py`). 25 nodos y 47 aristas, de los cuales **solo 4 nodos
están escritos a mano**: Recepción, Coordinación, Guardia y 112. Todo lo demás
—12 médicos, 3 sedes, 6 especialidades, quién trabaja dónde, quién cubre qué—
sale de lo que publica la clínica.

**Hecho:** las 18 formas en que una llamada puede acabar sin cita están
enrutadas. Cada una dice quién se entera y con qué urgencia. Si el reto añade
una decimonovena, **falla un test**, no el proceso en mitad de una llamada.

**Lo que NO existe, y conviene decirlo claro:**

- **No hay base de datos.** Ni una dependencia de Postgres o SQLite en los tres
  proyectos. Todo el estado son ficheros JSONL en un volumen.
- **No hay noción de organización** en ninguna parte del backend. Ni en la
  configuración, ni en el contexto de llamada, ni en la caché.
- **No hay usuarios.** `/ops` tiene **un token compartido**: o lo tienes o no
  entras. No sabe quién eres.
- **El catálogo se calienta una vez al arrancar**, para una clínica, en una
  variable de proceso.

Eso último es lo que hace que "varias empresas" no sea una tarde.

---

## 2. Multi-organización: qué cambia de verdad

El cambio no es una tabla de empresas. Es que **hoy la clínica es una variable
global del proceso** y tiene que pasar a ser un argumento.

```
HOY                                  HACE FALTA
settings().prosper_api_key           credenciales por organización
CatalogueCache (una, al arrancar)    una caché por organización
CallContext(call_id=...)             CallContext(org_id=..., call_id=...)
DATA_DIR/calls/<call_id>.jsonl       DATA_DIR/<org_id>/calls/<call_id>.jsonl
OPS_TOKEN (uno, compartido)          sesión de usuario -> organizaciones
```

**El orden importa**, y no es el que parece. Meter `org_id` en el contexto de
llamada es lo primero y lo más barato; montar login es lo último y lo más
visible. Si se hace al revés, se acaba con una pantalla bonita delante de un
backend que sigue sirviendo una sola clínica.

### Por dónde se entra

1. **`org_id` en el contexto de llamada y en la ruta de los datos.** Sin esto
   no hay nada más. Dos organizaciones escribiendo en el mismo directorio de
   llamadas son dos verdades sobre el mismo disco.
2. **Caché por organización.** `CatalogueCache` pasa de singleton a un mapa
   `org_id -> caché`, calentada al primer uso y no al arrancar. El catálogo es
   inmutable **dentro de una organización**, que es lo que hace esto barato.
3. **Credenciales por organización.** Hoy hay una `PROSPER_API_KEY` en el
   entorno. Con varias clínicas, cada una tiene la suya y eso ya no cabe en un
   `.env`: es el primer dato que obliga a tener base de datos.
4. **Usuarios y pertenencia.** Una persona pertenece a una o varias
   organizaciones y cambia entre ellas. Sustituye a `OPS_TOKEN`, no convive con
   él.

---

## 3. La base de datos, cuando llegue

No hace falta para el reto y sí para la plataforma. Lo que obliga a tenerla no
son las llamadas —esas están bien en ficheros— sino **los usuarios, las
organizaciones y sus credenciales**.

```
organizations   id, nombre, prosper_api_key (cifrada), created_at
users           id, email, ...
memberships     user_id, org_id, rol           <- quién ve qué
employees       org_id, nombre, rol, teléfono  <- los nodos que hoy son 4 fijos
routes          org_id, reason, employee_id, urgencia
```

Esa tabla `employees` es la clave de la parte del grafo: **convierte los cuatro
roles escritos a mano en datos por organización.** Un hospital tendrá veinte
nodos humanos y una consulta tendrá dos, y ninguno de los dos debería tocar
código.

Las llamadas se quedan en disco. Escribir un JSONL mientras la llamada pasa es
lo que hace que el panel lea en directo sin inventar ningún canal, y meterlas
en una base de datos perdería eso a cambio de nada.

---

## 4. El grafo, y dónde entra Jev

El grafo ya calcula **quién puede**: especialidad, idioma, seguro, horario,
baja. Eso es aritmética sobre el catálogo y no debe ser nunca la opinión de un
modelo — "PR10 acepta DKV" es un hecho.

Lo que falta es **quién, de los que pueden, y si urge**. Ahí sí hay juicio, y
ahí entra Jev. Con una condición que hoy sabemos medida:

> Jev acierta cuando la pregunta tiene un **conjunto cerrado de opciones sacado
> de los datos**, y es ruido cuando la pregunta es vaga.

Las dos medidas que lo demuestran, las dos de hoy:

- `classify_plan`, con los diez planes del catálogo como opciones: colocó
  `sanitos premium` en `sanitas` y se abstuvo ante basura.
- `needs_clarification`, una pregunta vaga: dijo `True` en **12 de 15 turnos**,
  incluidos un nombre normal y un DNI normal, y `False` justo en el turno que
  importaba. Se retiró de lo que ve el modelo.

Así que el reparto es:

```
EL CATÁLOGO   quién puede        aritmética, nunca opinión
EL GRAFO      a quién le toca    las 18 razones cerradas de la clínica
JEV           cuál, y si urge    opciones cerradas + abstención
```

**Y la abstención es la función, no el fallo.** Cuando Jev no lo tiene claro no
se adivina a quién llamar: se escala al humano por defecto. En un clasificador
de aseguradoras eso es un turno perdido; en un grafo de escalado médico es
exactamente lo que se quiere. Un sistema que nunca duda es un sistema que un
día llama al cardiólogo por un esguince.

---

## 5. Llamar de verdad

Avisar en el panel es media tarde. **Marcar un teléfono es otro producto**:
Twilio o similar, números comprados, consentimiento, y un registro de quién fue
llamado y por qué que resiste que alguien lo pregunte.

La recomendación es hacerlo en dos pasos y no fingir que es uno: primero el
aviso —que ya se puede pintar, porque el grafo ya dice a quién y con qué
urgencia— y la llamada después, cuando alguien decida que un sistema automático
puede despertar a una persona.

---

## 6. Qué se puede enseñar mañana sin nada de lo anterior

Esto importa para el hackathon, que es lo que hay el domingo:

- **El grafo dibujado.** Ya se sirve en `GET /ops/api/live/graph`, con las
  capas y las etiquetas en castellano. Falta la pantalla.
- **Varias organizaciones falsas.** Un selector con dos o tres clínicas
  inventadas, aunque por debajo sea una, enseña la idea entera sin tocar el
  backend. Con la condición de decir que es una maqueta.
- **El escalado.** "No hay hueco" → Coordinación, hoy. "Urgencia médica" → 112,
  ahora. Eso ya es real, no maqueta: sale de las 18 razones de la clínica.

---

## 7. El orden que recomiendo

| # | qué | por qué ahora | coste |
|---|---|---|---|
| 1 | Dibujar el grafo | Ya se sirve. Es lo que se ve. | una tarde de front |
| 2 | `org_id` en contexto y rutas de datos | Sin esto nada de lo demás es real | medio día |
| 3 | Caché por organización | Segunda clínica de verdad | medio día |
| 4 | Base de datos + usuarios | Lo exige el login, no las llamadas | un día |
| 5 | `employees` y rutas por organización | Convierte los 4 roles fijos en datos | medio día |
| 6 | Llamada real | Producto aparte | no estimado |

Los pasos 2 y 3 son los que nadie ve y sin los que los demás son decorado.
