/**
 * Abrir incidencias y moverlas de estado, desde el panel.
 *
 * Copia deliberada del proxy de `/api/live`: aquél es de sólo lectura por
 * construcción y guarda las transcripciones, y darle un POST para que dos
 * pantallas compartan un fichero es exactamente cómo una puerta de sólo
 * lectura deja de serlo.
 *
 * Tres formas, y ninguna más: lanzar una falsa, abrir una a mano, y cambiar
 * el estado de una que existe. El `OPS_TOKEN` nunca baja al navegador: se
 * añade aquí, en el servidor, que es la razón de que este fichero exista.
 */
const AGENT = (process.env.AGENT_HTTP_BASE_URL ?? "http://127.0.0.1:7861").replace(/\/$/, "");
const ID = /^[A-Za-z0-9._-]{1,128}$/;

type Body = {
  action?: string;
  id?: string;
  status?: string;
  note?: string;
  reason?: string;
  summary?: string;
};

function headers(): Record<string, string> {
  const out: Record<string, string> = { "Content-Type": "application/json" };
  const token = process.env.OPS_TOKEN;
  if (token) out["X-Ops-Token"] = token;
  return out;
}

export async function POST(request: Request) {
  let body: Body;
  try {
    body = (await request.json()) as Body;
  } catch {
    return Response.json({ detail: "Petición no válida" }, { status: 400 });
  }

  let path = "";
  let payload: unknown = {};
  if (body.action === "simulate") {
    path = "/ops/api/live/incidents/simulate";
  } else if (body.action === "status") {
    if (!body.id || !ID.test(body.id)) {
      return Response.json({ detail: "Identificador no válido" }, { status: 400 });
    }
    path = `/ops/api/live/incidents/${body.id}/status`;
    payload = { status: body.status, note: body.note ?? "" };
  } else if (body.action === "open") {
    path = "/ops/api/live/incidents";
    payload = { reason: body.reason, summary: body.summary ?? "" };
  } else {
    return Response.json({ detail: "Acción desconocida" }, { status: 404 });
  }

  try {
    const upstream = await fetch(`${AGENT}${path}`, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify(payload),
      cache: "no-store",
      signal: AbortSignal.timeout(15000),
    });
    return Response.json(await upstream.json().catch(() => ({})), {
      status: upstream.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ detail: "No se puede hablar con el agente." }, { status: 502 });
  }
}
