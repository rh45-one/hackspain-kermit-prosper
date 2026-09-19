import { ClinicGraphBoard } from "@/components/graph/clinic-graph";
import { GraphUnavailable } from "@/components/graph/graph-unavailable";
import type { ClinicGraph } from "@/lib/graph";

/**
 * The clinic graph, fetched on the server and drawn on the client.
 *
 * The ops token stays in this process: it is read from the environment here
 * and never reaches the browser, which is also why it must never be named
 * NEXT_PUBLIC_*. The graph is the shape of the clinic, not patient data, but
 * the door it comes through is the same one that guards the transcripts.
 *
 * Fetched server-side rather than polled: the catalogue is immutable for the
 * whole event, so there is nothing to poll for, and a server fetch means the
 * picture is already on screen when the page paints instead of flashing a
 * spinner in front of a jury.
 */

export const dynamic = "force-dynamic";

export const metadata = {
  title: "El grafo de la clínica · Clínica Arenal",
  description:
    "Quién existe, quién cubre qué, quién está dónde y las dieciocho formas en que una llamada puede acabar sin cita.",
};

/**
 * Public address of the agent's own browser call page (`/call`, which talks to
 * `/ws/demo`: the production pipeline with the submit switched off).
 *
 * Read here, on the server, and handed down as a prop — it is not a secret,
 * but it is the deployment's address and the client has no business guessing
 * it. `AGENT_HTTP_BASE_URL` already points at the deployed agent in Vercel, so
 * the common case needs no new configuration; `VOICE_PUBLIC_BASE_URL` exists
 * for the day the panel reads the ops process over a private address while the
 * phone in the room needs a public one.
 */
function callPageUrl(): string {
  const base = (
    process.env.VOICE_PUBLIC_BASE_URL ??
    process.env.AGENT_HTTP_BASE_URL ??
    "http://127.0.0.1:7860"
  ).replace(/\/$/, "");
  return `${base}/call/`;
}

type Loaded =
  | { ok: true; graph: ClinicGraph }
  | { ok: false; detail: string; hint: string };

async function loadGraph(): Promise<Loaded> {
  const base = (process.env.AGENT_HTTP_BASE_URL ?? "http://127.0.0.1:7861").replace(/\/$/, "");
  const token = process.env.OPS_TOKEN;
  const headers: Record<string, string> = {};
  if (token) {
    headers["X-Ops-Token"] = token;
  }

  let response: Response;
  try {
    response = await fetch(`${base}/ops/api/live/graph`, {
      cache: "no-store",
      headers,
      signal: AbortSignal.timeout(15000),
    });
  } catch {
    return {
      ok: false,
      detail: "No se puede hablar con el agente.",
      hint: `El panel ha intentado ${base}/ops/api/live/graph y no ha contestado nadie. Revisa AGENT_HTTP_BASE_URL.`,
    };
  }

  if (response.status === 401 || response.status === 403) {
    return {
      ok: false,
      detail: "El agente ha contestado, pero no nos deja entrar.",
      hint: "La consola de operaciones exige la cabecera X-Ops-Token. Revisa que OPS_TOKEN en el panel sea el mismo secreto que el del despliegue.",
    };
  }
  if (response.status === 404) {
    return {
      ok: false,
      detail: "Ese agente todavía no sirve el grafo.",
      hint: "GET /ops/api/live/graph devuelve 404, así que el despliegue al que apunta el panel es anterior a esa ruta. Vuelve a desplegar el backend o apunta AGENT_HTTP_BASE_URL a uno que ya la tenga.",
    };
  }
  if (!response.ok) {
    return {
      ok: false,
      detail: `El agente ha respondido ${response.status}.`,
      hint: "La ruta existe pero ha fallado al construir el grafo. Mira los logs del backend.",
    };
  }

  try {
    const graph = (await response.json()) as ClinicGraph;
    if (!Array.isArray(graph?.nodes) || !Array.isArray(graph?.escalations)) {
      throw new Error("forma inesperada");
    }
    return { ok: true, graph };
  } catch {
    return {
      ok: false,
      detail: "El agente ha respondido algo que no es un grafo.",
      hint: "Se esperaban `nodes`, `edges`, `escalations` y `legend`. El contrato lo define el backend en agent/ops/graph.py.",
    };
  }
}

export default async function GrafoPage() {
  const loaded = await loadGraph();
  if (!loaded.ok) {
    return <GraphUnavailable detail={loaded.detail} hint={loaded.hint} />;
  }
  return <ClinicGraphBoard graph={loaded.graph} callUrl={callPageUrl()} />;
}
