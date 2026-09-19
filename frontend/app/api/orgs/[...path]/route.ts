/**
 * Server-side proxy to the ops directory: `/ops/api/orgs/{org}/*`.
 *
 * A copy of `app/api/live/[...path]/route.ts` and deliberately a copy: that
 * one is read-only by construction and guards the transcripts, and giving it
 * a PUT and a DELETE so two screens could share a file is how a read-only
 * door stops being read-only. Same token handling, different allow-list,
 * different verbs.
 *
 * Three things it does that the live proxy does not:
 *
 * 1. **It names the organisation.** The browser never says which clinic it is
 *    editing: this process does, from `ORG_ID`. A path segment the client
 *    controls would be a path segment the client can walk.
 * 2. **It forwards the session cookie.** These routes want a *person*, not
 *    just the service token — a phone number and an email are behind them.
 *    The ops session cookie belongs to the agent's origin, so it only ever
 *    arrives here if somebody put it on this one; forwarded rather than
 *    dropped so the day an account exists, this works.
 * 3. **It reports which failure it was.** `fault` separates "the panel has no
 *    token" from "nobody is signed in" from "the host did not answer",
 *    because the three have three different fixes and the person reading the
 *    screen is the one who has to apply one.
 */

/** Only the shapes the screen actually calls. Everything else is a 404 here. */
const SLUG = /^[a-z0-9][a-z0-9_-]{0,62}$/;
const ORG_ID = /^[a-z0-9][a-z0-9_-]{0,62}$/;

type Fault =
  | "token"
  | "session"
  | "membership"
  | "role"
  | "host"
  | "route"
  | "upstream"
  | "request";

function orgId(): string {
  const raw = (process.env.ORG_ID ?? "clinica-arenal").trim().toLowerCase();
  return ORG_ID.test(raw) ? raw : "clinica-arenal";
}

/** `people`, `routes`, `people/<slug>`, `routes/<reason>`, `people/<slug>/call-profile`. */
function resolve(path: string[] | undefined, method: "GET" | "PUT" | "DELETE"): string | null {
  if (!path?.length || path.length > 3) {
    return null;
  }
  const [head, key, tail] = path;
  if (head !== "people" && head !== "routes") {
    return null;
  }
  if (path.length === 1) {
    return method === "GET" ? head : null;
  }
  if (!SLUG.test(key)) {
    return null;
  }
  if (path.length === 2) {
    return method === "GET" ? null : `${head}/${key}`;
  }
  // The preview, and only the preview.
  if (head === "people" && tail === "call-profile" && method === "GET") {
    return `people/${key}/call-profile`;
  }
  return null;
}

function fail(fault: Fault, detail: string, status: number): Response {
  return Response.json({ detail, fault }, { status, headers: { "Cache-Control": "no-store" } });
}

async function forward(request: Request, path: string[] | undefined, method: "GET" | "PUT" | "DELETE") {
  const suffix = resolve(path, method);
  if (suffix === null) {
    return fail("request", "Recurso desconocido en el directorio de la clínica.", 404);
  }

  const base = (process.env.AGENT_HTTP_BASE_URL ?? "http://127.0.0.1:7861").replace(/\/$/, "");
  const token = process.env.OPS_TOKEN;
  const headers: Record<string, string> = {};
  if (token) {
    headers["X-Ops-Token"] = token;
  }
  // If the person signed in against this origin, carry them through. If not,
  // nothing is sent and the agent answers 401 — which is the honest answer.
  const cookie = request.headers.get("cookie");
  if (cookie) {
    headers["cookie"] = cookie;
  }

  let body: string | undefined;
  if (method === "PUT") {
    body = await request.text();
    headers["content-type"] = "application/json";
  }

  const url = new URL(request.url);
  const reason = url.searchParams.get("reason") ?? "";
  const query = suffix.endsWith("/call-profile") && reason ? `?reason=${encodeURIComponent(reason)}` : "";

  let upstream: Response;
  try {
    upstream = await fetch(`${base}/ops/api/orgs/${orgId()}/${suffix}${query}`, {
      method,
      cache: "no-store",
      headers,
      body,
      signal: AbortSignal.timeout(15000),
    });
  } catch {
    return fail(
      "host",
      `El panel ha llamado a ${base} y no ha contestado nadie. Revisa AGENT_HTTP_BASE_URL.`,
      502,
    );
  }

  let payload: unknown = null;
  try {
    payload = await upstream.json();
  } catch {
    payload = null;
  }
  const detail =
    typeof payload === "object" && payload !== null && "detail" in payload
      ? String((payload as { detail?: unknown }).detail ?? "")
      : "";

  if (upstream.status === 401) {
    // The two 401s are not the same problem. The ops door answers "ops token
    // required"; the membership check answers "hace falta iniciar sesión".
    if (!token || /ops token/i.test(detail)) {
      return fail(
        "token",
        "El agente exige la cabecera X-Ops-Token y el panel no la lleva. Falta OPS_TOKEN en el entorno del panel.",
        401,
      );
    }
    return fail("session", detail || "Hace falta iniciar sesión.", 401);
  }
  if (upstream.status === 403) {
    return fail(/admin/i.test(detail) ? "role" : "membership", detail || "Sin permiso.", 403);
  }
  if (upstream.status === 404 && (suffix === "people" || suffix === "routes")) {
    return fail(
      "route",
      "Ese despliegue del agente no sirve todavía el directorio de la clínica. Vuelve a desplegar el backend.",
      404,
    );
  }

  return Response.json(payload ?? { detail: "Respuesta vacía del agente." }, {
    status: upstream.status,
    headers: { "Cache-Control": "no-store" },
  });
}

export async function GET(request: Request, context: { params: Promise<{ path: string[] }> }) {
  return forward(request, (await context.params).path, "GET");
}

export async function PUT(request: Request, context: { params: Promise<{ path: string[] }> }) {
  return forward(request, (await context.params).path, "PUT");
}

export async function DELETE(request: Request, context: { params: Promise<{ path: string[] }> }) {
  return forward(request, (await context.params).path, "DELETE");
}
