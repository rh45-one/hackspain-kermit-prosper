export async function GET(
  request: Request,
  context: RouteContext<"/api/frontdesk/[resource]">,
) {
  const { resource } = await context.params;
  if (resource !== "calls" && resource !== "clinic") {
    return Response.json({ detail: "Unknown resource" }, { status: 404 });
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
    // The ops routes refuse anything without this, and the token stays in the
    // server's environment: never NEXT_PUBLIC_, never in the browser bundle.
    // The live proxy next door already did this; this one did not, so every
    // page hanging off it answered 401 the moment the door went on.
    const headers: Record<string, string> = { "Cache-Control": "no-store" };
    const token = process.env.OPS_TOKEN;
    if (token) headers["X-Ops-Token"] = token;
    const upstream = await fetch(
      `${base.replace(/\/$/, "")}/ops/api/frontdesk/${resource}?${query}`,
      { cache: "no-store", headers, signal: AbortSignal.timeout(30000) },
    );
    if (upstream.status === 401 || upstream.status === 403) {
      return Response.json(
        { detail: "The desk cannot reach the agent. Check OPS_TOKEN." },
        { status: upstream.status, headers: { "Cache-Control": "no-store" } },
      );
    }
    return Response.json(await upstream.json(), {
      status: upstream.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json(
      { detail: "Backend unavailable. Check AGENT_HTTP_BASE_URL and agent.serve." },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}
