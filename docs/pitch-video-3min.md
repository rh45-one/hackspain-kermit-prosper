# Vídeo de criba — 3 minutos

Criterios que tiene que **dejar juzgar** (sin Q&A): creatividad, problem
solving, craftsmanship. El vídeo cuenta el proyecto a fondo. **La demo no va
dentro**: va aparte, para que la prueben.

La sala de finalistas es otra pieza:
[`pitch-prosper-empleados.md`](pitch-prosper-empleados.md).

## Tres entregables, no uno

| Pieza | Qué es | Qué no es |
| --- | --- | --- |
| Vídeo 3 min | Relato del proyecto: problema, tesis, cómo se resuelve, oficio, idea propia | Un screen-record de una llamada |
| Demo jugable | Endpoint + FrontDesk que un juez puede marcar y mirar | Un montaje en el mp4 |
| 5 min en sala | Tablero + FrontDesk en vivo + preguntas | Repetir el vídeo |

Si el vídeo es solo una demo grabada, no pueden puntuar creatividad ni oficio:
solo ven que “suena”. Si el vídeo es solo arquitectura, no creen que exista.
Las dos cosas, separadas.

## Lo que el vídeo tiene que dejar claro

**Creatividad.** ClinicReflow: la clínica se reorganiza cuando un médico falla
(optimizador propone, la voz negocia, no promete un hueco invisible). FrontDesk
como veredicto — identificación, envío, mix — no como mando a distancia.
Tratar la negativa correcta como el trabajo, no como un fallo de conversación.

**Problem solving.** El problema real es el cruce paciente × médico × centro ×
plan × volante × calendario. Solución: resolver fechas en Europe/Madrid sin
el LLM; herramientas que solo aceptan ids de la API; vocabulario cerrado de
refusals; triage a 112. Evidencia: siete problemas a 4/4; Third Party 3/4;
New Patient a cero, nombrado.

**Craftsmanship.** Un socket por llamada. Envío en 30 s. Exact-match, sin
medio punto. Nunca leer DNI ni teléfono. Diagnóstico por llamada en el
mostrador. Sabemos dónde rompe (REGISTER / habla), no lo escondemos.

Números = mejor Run All, problemas 1–10 (19 Sep). No citar los 54 failed.

## Guión de voz (180 s, se dice todo esto)

Ensayad con cronómetro. ~380 palabras, ~130 ppm. Si os pasáis, recortad los
corchetes, no el cierre ni New Patient.

Imagen: cara a cámara o VO sobre planos fijos de FrontDesk / tablero recortado
/ un esquema de tres capas dibujado a mano. **Cero minutos de llamada
completa.** Un plano de 4 s del mostrador basta como ancla visual.

### 0:00 — El problema

> Somos Kermit. ClinicReflow.
>
> El problema no es que un modelo sepa hablar. Es que una cita es el cruce de
> un paciente, un médico, un centro, un seguro, un volante y un calendario.
> Un modelo voz-a-voz, él solo, inventa la María García que falta para que la
> conversación siga.
>
> Tesis: el modelo habla. El sistema decide.

### 0:28 — Oficio (craft)

> Cada llamada es un socket, sin estado compartido. El calendario es Python,
> Europe/Madrid, festivos, nunca el mismo día: el LLM no hace cuentas. Las
> herramientas solo aceptan ids que la clínica ya había devuelto. En menos de
> treinta segundos se envía un verbo: BOOK, CANCEL, NO_ACTION, ESCALATE.
> Silencio es fallo. Una negativa correcta lleva la razón cerrada: volante,
> baja, no cubierto. Nunca se lee un DNI ni un teléfono.

### 1:00 — Cómo se ataca el mostrador real (problem solving)

> Los casos de Prosper son ese mostrador. The Rules: si no se puede, no hay
> hueco inventado. When Exactly: “el lunes a primera hora” es Madrid, no el
> modelo. Triage: dolor de pecho es 112, no una cita.
>
> Cita simple, médico pedido por nombre, agenda llena, cambiar y cancelar:
> cuatro de cuatro. Un padre que llama por un hijo: tres de cuatro. Un alta
> nueva — DNI con letra, email al dictado —: cero. Es el test de voz más
> fino, y ahora mismo lo perdemos. Lo decimos porque lo medimos.

### 1:40 — Lo que no pedían (creatividad)

> La otra mitad es ver la llamada. FrontDesk no es un mando: en la tarjeta
> vemos si identificó el caso, si el POST aterrizó, y el mix booked, refused,
> diverted. Vuestro tablero dice si pasó. El nuestro dice qué vimos y qué
> enviamos, sin esperar al lunes.
>
> Y si el médico no viene, la clínica se reorganiza. Un optimizador propone
> alternativas ya legales; la voz negocia; no promete un hueco que no ha
> visto. Eso es una costura, no el motor cerrado. Es el producto.

### 2:25 — Por qué el tablero se ve así

> Mejor Run All, problemas 1 a 10: siete a pleno. No es el modelo que
> elegimos. Es que el record coincide después de normalizar, o el caso falla
> entero. No hay medio punto.

### 2:42 — Cierre (la demo está fuera)

> Somos Kermit. Esto era el porqué. La demo es el teléfono y el mostrador:
> se puede marcar y se puede mirar mientras habla. Ahí se prueba.

## Reloj

| Tiempo | Qué cubre | Criterio |
| --- | --- | --- |
| 0:00–0:28 | Problema + tesis | Creatividad de framing |
| 0:28–1:00 | Socket, fechas, ids, verbos, PII | Craft |
| 1:00–1:40 | Rules / fechas / triage / el miss | Problem solving |
| 1:40–2:25 | FrontDesk + ClinicReflow | Creatividad + craft |
| 2:25–2:42 | Siete a 4/4, binario | Craft / evidencia |
| 2:42–3:00 | La demo se prueba aparte | CTA |

## Demo jugable (fuera del mp4)

Empaquetad esto en el mismo envío que el vídeo, en un párrafo. Sin esto el
juez no puede “probar”:

- **Voz:** `wss://<túnel>/ws` (el mismo endpoint del harness).
- **Mostrador:** URL de FrontDesk, ruta `/calls`.
- **Qué marcar:** un caso público de The Rules o de Triage (respuesta
  publicada; no vale un Run All privado).
- **Qué mirar en el mostrador:** entidades en la tarjeta, verbo al colgar,
  envíos aceptados/fallidos, mix.
- **Qué no hacer:** no leer DNI ni teléfonos en voz alta si ellos llaman
  en sala; el agente tampoco.

Si el túnel se cae, el vídeo sigue valiendo: cuenta el proyecto. La demo es
el plus que pide el criterio “se puede probar”.

## Planos (esta noche, 20 minutos de grabación)

No montéis una llamada de 90 s. Grabad:

1. Un plano de FrontDesk `/calls` con una tarjeta (5 s).
2. El tablero recortado, sin la columna de failed (5 s).
3. Calendario con un REFUSED o BOOKED (3 s).
4. VO, 3 tomas, sitio quieto.

Supers: *Kermit · ClinicReflow*. Navy `#013653`, coral `#ff5533`. Sin logos
de vendors. 16:9, 1080p, subtítulos si podéis. mp4 H.264.

Revisión en tres preguntas:

1. Creatividad: ¿se entiende ClinicReflow y el mostrador-como-veredicto?
2. Problem solving: ¿se oye cómo se resuelve Rules / fechas / triage, y el miss?
3. Craft: ¿se oye el oficio (ids, 30 s, binario) sin lista de tecnologías?

## Relación con la final

El vídeo ya contó el proyecto. En sala no lo recitéis: abrid el tablero, el
mostrador en vivo, y dejad que prueben el mismo endpoint que enviasteis con
el vídeo.
