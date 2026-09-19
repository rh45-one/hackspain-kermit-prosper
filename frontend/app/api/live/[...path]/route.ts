/**
 * Server-side proxy to the ops live view.
 *
 * The ops token never reaches the browser: this handler runs on the Next
 * server, reads OPS_TOKEN from its own environment and adds the header here.
 * That is also why the variable must never be named NEXT_PUBLIC_*, which
 * would inline it into the client bundle.
 *
 * Read-only by construction: only GET is exported.
 */
const ALLOWED = new Set(["calls", "clinic"]);

export async function GET(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  // Only the two shapes the panel actually uses: calls, calls/<id>.
  if (!path?.length || !ALLOWED.has(path[0]) || path.length > 2) {
    return Response.json({ detail: "Recurso desconocido" }, { status: 404 });
  }
  if (path.length === 2) {
    // Only `calls` has a second segment, and only ever a call id.
    if (path[0] !== "calls" || !/^[A-Za-z0-9._-]{1,128}$/.test(path[1])) {
      return Response.json({ detail: "Identificador no válido" }, { status: 400 });
    }
  }

  const base = (process.env.AGENT_HTTP_BASE_URL ?? "http://127.0.0.1:7861").replace(/\/$/, "");
  const token = process.env.OPS_TOKEN;
  const headers: Record<string, string> = {};
  if (token) {
    headers["X-Ops-Token"] = token;
  }

  try {
    const upstream = await fetch(`${base}/ops/api/live/${path.join("/")}`, {
      cache: "no-store",
      headers,
      signal: AbortSignal.timeout(15000),
    });
    if (upstream.status === 401 || upstream.status === 403) {
      return Response.json(
        { detail: "El panel no tiene acceso al agente. Revisa OPS_TOKEN." },
        { status: 502, headers: { "Cache-Control": "no-store" } },
      );
    }
    return Response.json(await upstream.json(), {
      status: upstream.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json(
      { detail: "No se puede hablar con el agente. Revisa AGENT_HTTP_BASE_URL." },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}
