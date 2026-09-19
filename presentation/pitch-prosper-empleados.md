# Guión — 5 minutos para finalistas (sala)

Equipo Kermit. Producto: **ClinicReflow**. Clínica de demo: **Clínica Arenal**.

Hay **tres piezas**, no una:

- Criba, esta noche: vídeo de 3 minutos —
  [`pitch-video-3min.md`](pitch-video-3min.md). Cuenta el proyecto (creatividad,
  problem solving, craft). **Sin demo dentro.**
- Demo jugable, junto al vídeo: `wss://…/ws` + FrontDesk `/calls` + un caso
  público de The Rules o Triage. Que lo marquen ellos.
- Finalistas, en sala: **este** documento +
  [`presentacion-finalistas.html`](presentacion-finalistas.html).
  Quien esté delante ya vio el vídeo: no lo recitéis. Tablero, FrontDesk en
  vivo, preguntas.

Audiencia en sala: gente que ya opera voz en clínicas. No les expliquéis qué es un EHR.
Idioma: español. Si la sala pide inglés, usad el cierre bilingüe del final.
Deck: abrir [`presentacion-finalistas.html`](presentacion-finalistas.html) a pantalla completa
(`F`). Flechas para pasar. `N` enseña las notas del guión. El design system de
Prosper ya está aplicado a las seis slides. FrontDesk no se re-brandéa.

Regla de oro, copiada de su propio brief: *demo what you built*. Si hay que
cortar, se cortan slides, no la pantalla.

## Antes de entrar (5 minutos de prep)

- Un portátil en **FrontDesk `/calls`**, ya cargado, fuente grande, notificaciones off.
- Un segundo portátil o teléfono listo por si hay que colgar y reabrir.
- Audio del agente a volumen de sala, no de auricular.
- No abrir Settings. El leaderboard de problemas **sí** puede estar a un alt-tab si preguntan un caso; no es la pieza central (está en las slides 2–3).
- Decidir **quién habla** (A) y **quién conduce la pantalla** (B). A no mira el
  portátil. B no improvisa historia.
- Tener un call card con transcripción visible. Ideal: una llamada real o de
  práctica. Si el harness está caído, el monitor mock con dos tarjetas concurrentes
  sigue sirviendo — el brief de Prosper lo admite para el jury.

## Reloj

| Tiempo | Quién | Qué |
| --- | --- | --- |
| 0:00–0:20 | A | Quiénes somos. El tablero, no el modelo. |
| 0:20–0:55 | A | Siete problemas a 4/4. El agujero, en una frase. |
| 0:55–1:40 | A | Tres casos que una clínica entiende: Rules, When Exactly, Triage. |
| 1:40–2:05 | A | FrontDesk no es solo control: identificación, envío, mix. |
| 2:05–3:50 | A narra, B enseña | `/calls`: entidades, diagnóstico, gráficos. |
| 3:50–4:30 | A | New Patient a cero. Third Party a 3/4. |
| 4:30–5:00 | A | Cierre: por eso el modelo no escribe. |

Si se comen el reloj: saltad la 5 (el miss) y dejadlo para Q&A. No salteis el tablero.

## Diapositivas

Seis, en [`presentacion-finalistas.html`](presentacion-finalistas.html). Números del mejor Run All
sobre los problemas 1–10 (captura del 19 Sep). Si el tablero se mueve, se
actualiza la slide 2.

1. **ClinicReflow** — vuestra plataforma, nuestro scoreboard.
2. **Seven at 4/4** — chips de los siete perfectos, Third Party 3/4, New Patient 0/4.
3. **What a perfect run means** — Rules 12/12, When Exactly 8/8, Triage 12/12.
4. **Did we identify the case?** — Identify · Land · Mix, luego alt-tab a `/calls`.
5. **What still fails** — New Patient 0/8, Third Party 9/12, Switchboard sin score.
6. **The model does not write** — por eso el tablero es binario.

No cotizar los “54 failed”: son intentos, no el mejor run. No decir que
REGISTER ya rinde; The New Patient está a cero.

---

## Guión hablado

Cortad las acotaciones en ensayo. Lo que va entre comillas es lo que se dice.
Cada bloque cabe en voz alta sin correr; si os pasáis de 5:00, recortad las
frases entre corchetes, no el demo.

### 0:00 — Apertura

> Somos Kermit. Nuestro agente coge el teléfono de Clínica Arenal y envía la
> acción a vuestra plataforma. No os vamos a explicar el problema: lo
> escribisteis vosotros. Os vamos a decir cómo rinde contra esos casos.

### 0:20 — El tablero

> Mejor Run All, problemas 1 a 10. Siete problemas a cuatro de cuatro:
> la cita simple, el médico y el centro, “cuándo exactamente”, las reglas,
> agenda llena, cambiar y cancelar, y triage.
>
> Third Party va tres de cuatro. The New Patient sigue a cero. Eso no es un
> detalle: es el REGISTER, la letra del DNI y el email al dictado. El motor
> de citas no es el que falla ahí.

### 0:55 — Qué significa un run perfecto

> The Rules, doce de doce. Si la clínica no puede, el agente no inventa un
> hueco. Envía NO_ACTION con la razón cerrada: volante, baja, no cubierto.
>
> When Exactly, ocho de ocho. “El lunes a primera hora” se resuelve en
> Madrid, con festivos y sin mismo día. El modelo no hace cuentas de calendario.
>
> Triage, doce de doce. Dolor de pecho no es una cita. Es 112. ESCALATE.
>
> También están a pleno el médico pedido por nombre, y cambiar o cancelar.
> Si queréis oír una, la marcamos ahora.

### 1:40 — El mostrador puntúa con nosotros

> No es solo un mando para el bot. En FrontDesk vemos, en la propia llamada,
> si identificó el caso: nombre, documento, tipo de cita, anclados en la
> tarjeta mientras habla.
>
> Vemos si el verbo aterrizó: envíos aceptados o fallidos, y el diagnóstico
> si la acción salió vacía. Y el mix de la hora: booked, refused, diverted.
> Vuestro tablero dice si el caso pasó. El nuestro dice por qué lo enviamos
> así, sin esperar al reveal del lunes.

[B: alt-tab a `/calls`. Señala entidades en una tarjeta, la línea de
diagnóstico, los gráficos de mix y envíos. Una llamada BOOK o NO_ACTION.]

> El browser no está colgado al WebSocket del teléfono. Si preguntáis
> *why did it say that?*, esta es la pantalla.

### 3:50 — Lo que aún falla

> The New Patient: cero de ocho. Hay que dar de alta, no citar. Dos apellidos,
> DNI con letra, email dictado letra a letra. Es el test de voz más fino del
> set, y ahora mismo lo perdemos.
>
> Third Party: nueve de doce. Un padre llama por un hijo. Tres de cuatro
> casos. El que falta lo estamos acotando.
>
> Switchboard no puntúa. Es un diagnóstico de diez y veinte líneas a la vez.

### 4:30 — Cierre

> Por eso el modelo no escribe. Un hueco inventado no os da medio punto.
> El caso falla entero. Cada llamada envía un verbo — BOOK, CANCEL,
> NO_ACTION, ESCALATE — y tiene que coincidir después de normalizar.
>
> Somos Kermit. Preguntad, o marcamos The Rules ahora mismo.

---

## Qué no decir

- El tablero sí se cita: el **mejor Run All**, no el recuento de intentos
  (20 passed / 54 failed). Eso último parece que perdéis.
- No decir que REGISTER ya rinde. The New Patient está a **0/8**.
- No decir que hacemos verificación de seguros ni facturación. Eso es Prosper.
  Nosotros hacemos citas, y las reglas que impiden una cita.
- No decir que clonamos su tabla naranja de “Run for score”. Esa es su harness.
  Lo nuestro es el mostrador: identificación en la tarjeta, POST aceptado o
  fallido, mix de verbos.
- No leer ids ni teléfonos en la demo.
- No abrir `.env`, logs crudos, ni transcripciones de casos privados.

## Plan B (30 segundos, si el live muere)

B deja una captura de `/calls` con dos tarjetas y el calendario con un REFUSED
legible. A dice:

> El browser no se engancha al WebSocket del teléfono a propósito. El mostrador
> lee el registro. Si el hilo de voz se cae, la recepción sigue pudiendo
> explicar la última llamada. Eso no es un fallo de producto: es el diseño.

Luego cierre. No debugueéis en escena.

## Q&A probable (respuestas de una frase)

**¿Por qué no dejáis que el modelo reserve?**
Porque un hueco inventado es peor que una negativa. Availability decide el tipo
de cita; nosotros enviamos exactamente ese id.

**¿Cómo identificáis?**
El caller id es una pista. Segunda prueba hablada (fecha de nacimiento o
documento) antes de leer o escribir. Un campo exacto que no cuadra excluye, no
reordena.

**¿Y si pide consejo médico o datos de otro paciente?**
No practicamos medicina. Escalamos urgencias a 112. Fuera de alcance: se niega,
no se reserva, no se filtra nada al audio.

**¿Diez llamadas a la vez?**
Diez es el diseño que puntuáis. Veinte sockets es el diagnóstico. Cada socket
trae su pipeline, su contexto y su envío. Cero estado de conversación compartido.

**¿Cuánto cuesta una llamada?**
Lo medimos por llamada: motor, conversión de audio, primer token, herramientas,
latencia del sidecar. Os lo enseñamos en el registro, no en una slide.

**¿Catalán / euskera / gallego?**
El prompt contesta en el idioma del primer turno y cambia si el llamante cambia.
El tablero comprueba el idioma; el jury, si se usó bien. No fingimos un acento.

## Versión inglesa de emergencia (~90 s, si cambian de idioma)

> We're Kermit. Our agent answers Clínica Arenal and files the action on your
> harness. Best Run All on problems 1–10: seven problems at four of four —
> booking, named doctor and site, relative dates, standing rules, a full diary,
> change and cancel, and triage.
>
> Third Party is three of four. New Patient is still zero: registration, the
> check letter, the email spelled aloud. That is speech, not the rules engine.
>
> The Rules is a correct refusal with a closed reason. When Exactly is Madrid,
> never same-day. Triage is 112, not a slot. FrontDesk is not just a remote:
> we see who we identified, whether the verb posted, and the outcome mix —
> without waiting for Monday's reveal.
>
> The model does not write, because an invented slot fails the whole case.
>
> Questions — or we dial The Rules now.

## Marca (Prosper Design System)

Fuente: zip que nos pasaron. Coral de producto `#ff5533`, no un lavado de
naranja. Lienzo blanco, tinta `#212b36`, bordes `#e5e5e5`. Public Sans en UI,
Inter en cuerpo, Manrope en números, Instrument Serif solo en el titular.
Sentence case. Sin emoji. Iconos lucide, stroke 1.75. El mark es la P de dos
paneles (carbón + coral); en la slide oscura el panel coral sostiene la marca.

El deck habla inglés visual (voz de su producto). El guión se dice en español.

No re-brandear FrontDesk: Clínica Arenal es la clínica que opera la recepción.
Mezclar las dos marcas en el UI parece un reskin, no una clínica. Se queda
Ventriloc, copy en español, nombre Arenal.
