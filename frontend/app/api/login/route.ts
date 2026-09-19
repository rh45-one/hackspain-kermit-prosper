/**
 * El login de verdad, detrás de la pantalla bonita.
 *
 * Hasta ahora `/login` no hablaba con nadie: aceptaba cualquier correo y
 * cualquier contraseña, escribía una bandera en `sessionStorage` que no lee
 * nadie, y te mandaba a `/calls` a los 700 ms. Por eso `/equipo` seguía sin
 * ver al equipo — nunca hubo sesión que enseñar.
 *
 * Quien comprueba la contraseña es el agente, porque es quien tiene la base de
 * datos, el hash y la tabla de sesiones. Este handler es el intermediario que
 * hacía falta por una razón concreta: **la cookie pertenece al host que la
 * pone**. Si el navegador se autenticara contra el agente directamente, la
 * cookie sería del dominio del agente y este panel, que vive en otro, no la
 * mandaría nunca. Al pasar por aquí, el `Set-Cookie` vuelve por este origen y
 * es de primera parte; los proxies de `app/api/*` la reenvían hacia el agente
 * en cada petición.
 *
 * Lo que sí cambia respecto a la ruta del agente es a dónde se va después. El
 * agente redirige a su propia consola en `/ops`, que en este dominio no
 * existe. Así que aquí no se redirige: se contesta JSON y es el cliente quien
 * navega, que además es lo que permite enseñar el error sin perder lo escrito.
 *
 * El `OPS_TOKEN` no entra en esta ruta a propósito. Es la credencial de
 * *servicio* del panel y sirve para leer; una persona que se identifica es
 * otra cosa, y mezclarlas convertiría el login en un adorno: entrarías igual
 * escribieras lo que escribieras, que es exactamente de lo que venimos.
 */
const AGENT = (process.env.AGENT_HTTP_BASE_URL ?? "http://127.0.0.1:7861").replace(/\/$/, "");

/** Nombre de la cookie de sesión del agente. Debe coincidir con `ops/auth.py`. */
const COOKIE = "ops_session";

type Body = { email?: unknown; password?: unknown };

export async function POST(request: Request) {
  let body: Body;
  try {
    body = (await request.json()) as Body;
  } catch {
    return Response.json({ ok: false, detail: "Petición no válida." }, { status: 400 });
  }

  const email = typeof body.email === "string" ? body.email.trim() : "";
  const password = typeof body.password === "string" ? body.password : "";
  if (!email || !password) {
    return Response.json({ ok: false, detail: "Introduce correo y contraseña." }, { status: 400 });
  }

  const form = new URLSearchParams({ email, password });

  let upstream: Response;
  try {
    upstream = await fetch(`${AGENT}/ops/login`, {
      method: "POST",
      body: form,
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      // Sin esto, `fetch` sigue el 303 hasta `/ops` y se come el `Set-Cookie`
      // por el camino, que es justo lo único que hemos venido a buscar.
      redirect: "manual",
      cache: "no-store",
      // scrypt cuesta ~40 ms en el agente; diez segundos cubren eso y la red
      // con holgura, y dejan colgado el caso en que el host no contesta.
      signal: AbortSignal.timeout(10000),
    });
  } catch {
    return Response.json(
      { ok: false, detail: "No se puede hablar con el agente. Revisa AGENT_HTTP_BASE_URL." },
      { status: 502 },
    );
  }

  const cookie = upstream.headers.get("set-cookie") ?? "";
  const ok = (upstream.status === 303 || upstream.status === 302) && cookie.includes(COOKIE);

  if (!ok) {
    // El agente contesta la página de login con el error dentro cuando algo
    // va mal. Traducimos su código a una frase, en vez de reenviar su HTML a
    // una pantalla que no lo sabe pintar.
    const detail =
      upstream.status === 401
        ? "Correo o contraseña incorrectos."
        : upstream.status === 403
          ? "Esa cuenta no pertenece a ninguna organización."
          : upstream.status === 503
            ? "El agente no tiene base de datos en este host."
            : "No se ha podido iniciar sesión.";
    return Response.json({ ok: false, detail }, { status: upstream.status === 401 ? 401 : 502 });
  }

  const response = Response.json({ ok: true }, { headers: { "Cache-Control": "no-store" } });
  // Reenviada tal cual: `HttpOnly`, `SameSite=Lax`, `Path=/` y el `Max-Age`
  // los decide el agente, que es quien sabe cuánto dura su sesión. Lo único
  // que cambia al pasar por aquí es el host al que el navegador la asocia,
  // que es este, y que es el objetivo.
  response.headers.append("set-cookie", cookie);
  return response;
}
