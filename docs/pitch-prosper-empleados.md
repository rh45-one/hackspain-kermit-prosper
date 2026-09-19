# Guión — 5 minutos para empleados de Prosper

Equipo Kermit. Producto: **ClinicReflow**. Clínica de demo: **Clínica Arenal**.
Audiencia: gente que ya opera voz en clínicas. No les expliquéis qué es un EHR.
Idioma: español. Si la sala pide inglés, usad el cierre bilingüe del final.
Deck: abrir [`docs/pitch/index.html`](pitch/index.html) a pantalla completa
(`F`). Flechas para pasar. `N` enseña las notas del guión. El design system de
Prosper ya está aplicado a las seis slides. FrontDesk no se re-brandéa.

Regla de oro, copiada de su propio brief: *demo what you built*. Si hay que
cortar, se cortan slides, no la pantalla.

## Antes de entrar (5 minutos de prep)

- Un portátil en **FrontDesk `/calls`**, ya cargado, fuente grande, notificaciones off.
- Un segundo portátil o teléfono listo por si hay que colgar y reabrir.
- Audio del agente a volumen de sala, no de auricular.
- No abrir Settings, Problems ni Leaderboard. Eso es nuestro backstage.
- Decidir **quién habla** (A) y **quién conduce la pantalla** (B). A no mira el
  portátil. B no improvisa historia.
- Tener un call card con transcripción visible. Ideal: una llamada real o de
  práctica. Si el harness está caído, el monitor mock con dos tarjetas concurrentes
  sigue sirviendo — el brief de Prosper lo admite para el jury.

## Reloj

| Tiempo | Quién | Qué |
| --- | --- | --- |
| 0:00–0:20 | A | Quiénes somos. Una frase. |
| 0:20–0:55 | A | Les devolvemos su problema, con sus palabras. |
| 0:55–1:40 | A | Tesis: el modelo habla, el sistema decide. |
| 1:40–4:10 | A narra, B enseña | FrontDesk en vivo. |
| 4:10–4:40 | A | ClinicReflow: cuando el médico no viene. |
| 4:40–5:00 | A | Cierre. Una cosa que se pueden llevar. |

Si se comen el reloj: saltad ClinicReflow (4:10) y cerrad desde el calendario.

## Diapositivas

Seis, en [`docs/pitch/index.html`](pitch/index.html). Marca Prosper en 1–3, 5 y 6.
La 4 es un corte a negro: alt-tab a FrontDesk.

1. **ClinicReflow** — lockup Prosper + título en Instrument Serif.
2. **From your brief** — cita literal de su challenge, en inglés.
3. **The system around the model** — Voice · Deterministic core · FrontDesk.
4. **Switch to FrontDesk** — tinta `#212b36`. Producto a pantalla completa.
5. **When a doctor drops out** — optimizer → voice → clinic.
6. **What the model never does** — los seis verbos en pills.

No pongáis logos de Gemini, Deepgram ni Helmcode en la 1. Si preguntan el stack,
se responde en Q&A. El modelo no es el premio; ellos mismos lo escribieron.

---

## Guión hablado

Cortad las acotaciones en ensayo. Lo que va entre comillas es lo que se dice.
Cada bloque cabe en voz alta sin correr; si os pasáis de 5:00, recortad las
frases entre corchetes, no el demo.

### 0:00 — Apertura

> Somos Kermit. Este fin de semana hemos construido ClinicReflow: un agente de
> voz que coge el teléfono de una clínica, y el mostrador con el que la
> recepción ve esa llamada mientras ocurre.
>
> No vamos a explicaros el problema. Lo escribisteis vosotros.

### 0:20 — Devolverles el brief

> Dijisteis que una cita es el cruce de un paciente, un médico, un centro, un
> tipo de visita, un seguro, un volante y un calendario. Y que un modelo
> voz-a-voz, él solo, no sabe cuál de las cuatro Marías García está al teléfono.
> Inventará una respuesta con mucha educación.
>
> También dijisteis que el trabajo interesante no es el prompt. Es el sistema
> alrededor: fichas reales, huecos reales, una comprobación antes de escribir,
> y poder explicar después por qué dijo lo que dijo.
>
> Eso es lo que hemos construido.

### 0:55 — Tesis (la única frase de arquitectura)

> El modelo habla. El sistema decide.
>
> Tres capas, y ninguna puede hacer el trabajo de las otras.
>
> **La voz** coge la llamada por el mismo hilo que usáis vosotros: WebSocket,
> μ-law a 8 kHz, una conversación por socket, diez llamadas a la vez sin
> mezclar estado. Puede ir audio-a-audio o por la cascada clásica. Si una
> ruta no está lista, no improvisamos un cambio a mitad de frase: se elige
> antes de descolgar.
>
> **El cerebro** no es el modelo. Es Python puro. Calendario en Europe/Madrid,
> días festivos, horarios del centro, matriz de plan × especialidad × médico ×
> centro. El modelo no hace cuentas de fechas. El modelo no inventa un id: las
> herramientas solo aceptan valores que la API de la clínica ya había devuelto.
>
> **El mostrador** es FrontDesk. No está colgado al teléfono. Mira el registro
> de la llamada: transcripción, entidades, si el paciente interrumpió, y qué
> acción se envió. Si el jury pregunta *why did it say that?*, no abrimos un
> log. Abrimos esta pantalla.

[B, en silencio: FrontDesk ya visible en `/calls`.]

### 1:40 — Demo FrontDesk

A habla. B no explica; señala.

> Esto es recepción de Clínica Arenal. Arriba: si el túnel público está vivo, y
> cuántas de las diez líneas están ocupadas. Abajo: hasta diez tarjetas a la vez.

[B: una tarjeta activa. Transcripción en marcha.]

> Cada tarjeta es una llamada. Nombre, documento, tipo de cita — lo que el
> agente ya ha anclado, no lo que el llamante ha dictado. El teléfono y el DNI
> no se leen nunca en voz alta. Ni para confirmar. Eso es un problema
> adversarial, no un detalle de UX.
>
> El llamante puede cortar. El agente para, escucha, y sigue desde ahí. Si la
> recepción tiene que entrar, *Tomar el control* desvía la llamada: deja de ser
> una cita y pasa a ser un humano. En el calendario eso se ve como DIVERTED.

[B: abre el modal de la llamada. Transcripción completa. Cierra sin pulsar
control de verdad si la llamada es live de harness.]

> Cada llamada termina en un verbo cerrado. BOOK, REGISTER, RESCHEDULE, CANCEL,
> NO_ACTION o ESCALATE. Siempre se envía algo, en menos de treinta segundos
> después de colgar. Un silencio no es una negativa educada: es un fallo.
> Una negativa correcta lleva la razón del vocabulario de la clínica:
> hace falta volante, profesional de baja, especialidad no cubierta, urgencia
> médica. No un texto libre.

[B: `/calendar`. Un chip REFUSED con la razón visible, uno BOOKED.]

> El calendario está anclado a Madrid. Un hueco a las 16:30 en Getafe no se
> pinta a las 15:30 porque el portátil esté en UTC. Booked, cancelled, refused,
> diverted: la recepción lee el estado sin abrir un JSON.

[B: `/patients`. Filtro por apellido y DNI con letra.]

> El directorio busca como el mostrador: nombre y DNI o NIE, incluida la letra
> de control. Una letra que no cuadra con los dígitos no consulta. El triaje
> que veis no es clínico: es la última acción del agente. Si escaló a urgencias,
> la ficha lo dice. Si se negó por volante, también.

### 4:10 — ClinicReflow

[Slide 5, o B se queda en calendario.]

> Hasta aquí es el inbound que puntuáis: alguien llama, la clínica responde.
>
> ClinicReflow es lo que pasa cuando el médico no viene. Un martes a las ocho,
> Requena está de baja, y hay una cola de citas que ya no existen. El
> optimizador —otra pieza del equipo— propone alternativas ya filtradas por
> profesional, duración, centro y reglas. La voz llama al paciente, ofrece en
> orden, y si dice que no, guarda la restricción: *no ese día, no cambiar de
> médico*. El optimizador recalcula. La voz no promete un hueco que no ha visto.
>
> Eso todavía es un costura, no el motor entero. Lo enseñamos porque es el
> producto, no porque esté cerrado.

### 4:40 — Cierre

> Si nos llevarais una sola cosa a Prosper, que no sea el modelo.
>
> Que cada cita que sale de este agente se pueda trazar a un id que la clínica
> ya había devuelto. El modelo narra. Un sidecar puede anotar la intención.
> Ninguno de los dos escribe.
>
> Somos Kermit. Esto es ClinicReflow. Preguntad.

---

## Qué no decir

- No cotizar el leaderboard, ni “casi pasamos el problema N”, ni el modelo
  como premio. Ellos puntuaron *engineering rigour* y *the platform*, no el
  vendor.
- No decir que hacemos verificación de seguros ni facturación. Eso es Prosper.
  Nosotros hacemos citas, y las reglas de plan × especialidad × centro que
  impiden una cita. Punto.
- No decir que ClinicReflow ya reorganiza la clínica entera. Hay interfaz de
  cola, herramientas de voz, y un optimizador en otro hilo. El inbound está
  construido; el reflow se enseña como tesis + costura.
- No leer ids ni teléfonos en la demo, ni en broma.
- No abrir `.env`, logs crudos, ni una transcripción con PII de un caso privado.
- No prometer outbound de marketing, CRM, ni cuentas de usuario.
- No pelearos con el cascade vs Gemini en escenario. Si preguntan: audio-a-audio
  con Gemini Live, cascada Deepgram + LLM + ElevenLabs como rollback, una sola
  por socket, elegida al descolgar.

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

> We're Kermit. ClinicReflow is a scheduling voice agent plus the desk that
> watches the call.
>
> You wrote the brief: a speech-to-speech model does not know which María García
> is on the line, and it will invent an answer. The interesting work is the
> system around the model. That is what we built.
>
> The model talks. The system decides. Tools only accept ids the clinic already
> returned. Relative dates are Europe/Madrid, not the LLM. Every call submits a
> closed verb within thirty seconds of hang-up — including a correct refusal.
> We never read a national id or a phone number aloud.
>
> This is FrontDesk. It is not on the telephony socket. It reads the call
> record, so you can answer *why did it say that?* without opening a log.
> If a doctor drops out, an optimizer proposes legal alternatives and the voice
> agent negotiates; it never promises a slot it has not seen.
>
> If you take one thing: do not let the model write. Questions welcome.

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
