export async function GET(
  request: Request,
  context: RouteContext<"/api/frontdesk/[resource]">,
) {
  const { resource } = await context.params;
  if (resource !== "calls" && resource !== "clinic") {
    return Response.json({ detail: "Recurso desconocido" }, { status: 404 });
  }
  const base = process.env.AGENT_HTTP_BASE_URL ?? "http://127.0.0.1:7860";
  const query = new URLSearchParams();
  if (resource === "clinic") {
    const incoming = new URL(request.url).searchParams;
    for (const key of ["name", "national_id"]) {
      const value = incoming.get(key);
      if (value) query.set(key, value);
    }
  }
  try {
    const upstream = await fetch(
      `${base.replace(/\/$/, "")}/ops/api/frontdesk/${resource}?${query}`,
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
