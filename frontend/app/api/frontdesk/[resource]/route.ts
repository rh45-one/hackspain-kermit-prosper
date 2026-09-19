export async function GET(
  _request: Request,
  context: RouteContext<"/api/frontdesk/[resource]">,
) {
  const { resource } = await context.params;
  if (resource !== "calls" && resource !== "clinic") {
    return Response.json({ detail: "Recurso desconocido" }, { status: 404 });
  }
  const base = process.env.AGENT_HTTP_BASE_URL ?? "http://127.0.0.1:7860";
  try {
    const upstream = await fetch(
      `${base.replace(/\/$/, "")}/ops/api/frontdesk/${resource}`,
      { cache: "no-store", signal: AbortSignal.timeout(30000) },
    );
    return Response.json(await upstream.json(), {
      status: upstream.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json(
      { detail: "Backend no disponible. Comprueba AGENT_HTTP_BASE_URL y agent.serve." },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}
