/**
 * The clinic graph: the contract served by `GET /ops/api/live/graph`, plus the
 * only thing a drawing needs that the backend does not send — where to put
 * things.
 *
 * The layout here is arithmetic, not a simulation. The graph is layered by
 * construction (`layer` 0-3) and the two views it feeds are both bipartite
 * fans, so a force solver would only add jitter, a dependency and a different
 * picture on every reload. A panel that is going to be projected has to look
 * the same every time somebody opens it.
 *
 * This module is imported from client components. It must stay pure: no
 * `process.env`, no `fetch`. The one network call lives in the page.
 */

export type GraphKind = "role" | "specialty" | "provider" | "site" | "reason";
export type GraphTone = "human" | "discipline" | "person" | "place" | "failure";
export type Urgency = "now" | "today" | "queue";
export type EdgeKind = "works_at" | "covers" | "escalates_to";

export type GraphNode = {
  id: string;
  kind: GraphKind;
  label: string;
  detail: string;
  available: boolean;
  meta: {
    languages?: string[];
    specialty_id?: string;
    urgency?: Urgency;
    reason?: string;
  };
  layer: number;
  tone: GraphTone;
  title?: string;
};

export type GraphEdge = {
  source: string;
  target: string;
  kind: EdgeKind;
  label: string;
};

export type Escalation = {
  reason: string;
  target: string;
  urgency: Urgency;
  detail: string;
};

export type ClinicGraph = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  escalations: Escalation[];
  warm: boolean;
  legend: {
    kinds: Record<string, { layer: number; tone: string; title: string }>;
    urgency: Record<Urgency, string>;
  };
};

/* ------------------------------------------------------------------ colour */

/** One colour per tone, named by the backend. A component never picks its own. */
export const TONE: Record<GraphTone, { ink: string; label: string }> = {
  human: { ink: "#1d211f", label: "Personas de la clínica" },
  discipline: { ink: "#4c534e", label: "Especialidad" },
  person: { ink: "#1d211f", label: "Profesional" },
  place: { ink: "#806b36", label: "Sede" },
  failure: { ink: "#e76432", label: "Final sin cita" },
};

/**
 * How loud each ending is. Colour is never the only signal: every urgency also
 * has its own stroke weight, its own dash and its own word on screen, so the
 * screen still reads on a washed-out projector or to a colour-blind jury.
 */
export const URGENCY: Record<
  Urgency,
  { ink: string; word: string; width: number; dash?: string; order: number }
> = {
  now: { ink: "#d92d20", word: "Ahora", width: 2.6, order: 0 },
  today: { ink: "#806b36", word: "Hoy", width: 1.7, order: 1 },
  queue: { ink: "#8d948e", word: "En cola", width: 1.2, dash: "5 5", order: 2 },
};

export const EDGE_INK: Record<EdgeKind, string> = {
  works_at: "#806b36",
  covers: "#4c534e",
  escalates_to: "#e76432",
};

export const EDGE_WORD: Record<EdgeKind, string> = {
  works_at: "pasa consulta en",
  covers: "cubre",
  escalates_to: "avisa a",
};

/* ------------------------------------------------------------------- words */

/**
 * The catalogue names specialties in English because the challenge's API does.
 * The id is what travels; this is only what a Spanish-speaking jury reads, and
 * an unknown specialty falls back to the catalogue's own label rather than
 * disappearing.
 */
const SPECIALTY_ES: Record<string, string> = {
  general_practice: "Medicina general",
  paediatrics: "Pediatría",
  dermatology: "Dermatología",
  orthopaedics: "Traumatología",
  gynaecology: "Ginecología",
  physiotherapy: "Fisioterapia",
};

export function specialtyLabel(node: GraphNode): string {
  return SPECIALTY_ES[node.id.replace(/^sp:/, "")] ?? node.label;
}

export function specialtyLabelById(specialtyId: string, fallback: string): string {
  return SPECIALTY_ES[specialtyId] ?? fallback;
}

const LANGUAGE_ES: Record<string, string> = {
  es: "Español",
  en: "Inglés",
  ca: "Catalán",
  gl: "Gallego",
  eu: "Euskera",
};

export function languageName(code: string): string {
  return LANGUAGE_ES[code] ?? code.toUpperCase();
}

/* ------------------------------------------------------------------ layout */

export const CANVAS_WIDTH = 1100;

export type Box = { x: number; y: number; w: number; h: number };
export type PlacedNode = Box & { node: GraphNode };
export type PlacedEdge = {
  id: string;
  source: string;
  target: string;
  kind: EdgeKind;
  urgency?: Urgency;
  d: string;
};

export type Column = { id: string; title: string; note: string; x: number; w: number };

/** A flat horizontal bezier. Both views read left to right, so both use it. */
function curve(x1: number, y1: number, x2: number, y2: number): string {
  const pull = Math.max(48, Math.abs(x2 - x1) * 0.42);
  return `M ${x1} ${y1} C ${x1 + pull} ${y1}, ${x2 - pull} ${y2}, ${x2} ${y2}`;
}

function centreY(box: Box): number {
  return box.y + box.h / 2;
}

/** Evenly spaced boxes inside a band: n items centred on their own n-th slice. */
function spread(count: number, top: number, band: number, height: number): number[] {
  if (count === 0) return [];
  const slice = band / count;
  return Array.from({ length: count }, (_, i) => top + slice * (i + 0.5) - height / 2);
}

/* -- the catalogue: sedes ← profesionales → especialidades ----------------- */

const CAT_COL_W = 236;
const CAT_TOP = 38;
const PROVIDER_H = 42;
const PROVIDER_PITCH = 48;
const SITE_H = 62;
const SPECIALTY_H = 46;

export type CatalogueLayout = {
  width: number;
  height: number;
  columns: Column[];
  nodes: PlacedNode[];
  edges: PlacedEdge[];
};

/**
 * Sites on the left, doctors in the middle, disciplines on the right.
 *
 * Doctors are ordered by the specialty they cover and the specialties keep the
 * catalogue's own order, so the `covers` edges come out as a tidy fan instead
 * of a hairball. Nothing about the data is changed to get that — only the
 * order the rows are drawn in.
 */
export function layoutCatalogue(graph: ClinicGraph): CatalogueLayout {
  const sites = graph.nodes.filter((n) => n.kind === "site");
  const specialties = graph.nodes.filter((n) => n.kind === "specialty");
  const specialtyRank = new Map(specialties.map((n, i) => [n.id, i]));
  const providers = graph.nodes
    .filter((n) => n.kind === "provider")
    .slice()
    .sort((a, b) => {
      const ra = specialtyRank.get(`sp:${a.meta.specialty_id ?? ""}`) ?? 99;
      const rb = specialtyRank.get(`sp:${b.meta.specialty_id ?? ""}`) ?? 99;
      return ra - rb || a.id.localeCompare(b.id);
    });

  const band = Math.max(
    providers.length * PROVIDER_PITCH,
    sites.length * 96,
    specialties.length * 62,
  );
  const height = CAT_TOP + band + 14;

  const xSites = 0;
  const xProviders = Math.round((CANVAS_WIDTH - CAT_COL_W) / 2);
  const xSpecialties = CANVAS_WIDTH - CAT_COL_W;

  const placed = new Map<string, PlacedNode>();
  const providerTop = CAT_TOP + (band - providers.length * PROVIDER_PITCH) / 2;
  providers.forEach((node, i) => {
    placed.set(node.id, {
      node,
      x: xProviders,
      y: providerTop + i * PROVIDER_PITCH,
      w: CAT_COL_W,
      h: PROVIDER_H,
    });
  });
  spread(sites.length, CAT_TOP, band, SITE_H).forEach((y, i) => {
    placed.set(sites[i].id, { node: sites[i], x: xSites, y, w: CAT_COL_W, h: SITE_H });
  });
  spread(specialties.length, CAT_TOP, band, SPECIALTY_H).forEach((y, i) => {
    placed.set(specialties[i].id, {
      node: specialties[i],
      x: xSpecialties,
      y,
      w: CAT_COL_W,
      h: SPECIALTY_H,
    });
  });

  const edges: PlacedEdge[] = [];
  for (const edge of graph.edges) {
    const from = placed.get(edge.source);
    const to = placed.get(edge.target);
    if (!from || !to) continue;
    // `works_at` points doctor → site, which on this canvas runs right to left.
    // Drawing it from the site keeps every stroke flowing the same way.
    const [a, b] = edge.kind === "works_at" ? [to, from] : [from, to];
    edges.push({
      id: `${edge.source}->${edge.target}:${edge.kind}`,
      source: edge.source,
      target: edge.target,
      kind: edge.kind,
      d: curve(a.x + a.w, centreY(a), b.x, centreY(b)),
    });
  }

  return {
    width: CANVAS_WIDTH,
    height,
    columns: [
      { id: "site", title: "Sedes", note: `${sites.length} centros`, x: xSites, w: CAT_COL_W },
      {
        id: "provider",
        title: "Profesionales",
        note: `${providers.length} médicos`,
        x: xProviders,
        w: CAT_COL_W,
      },
      {
        id: "specialty",
        title: "Especialidades",
        note: `${specialties.length} disciplinas`,
        x: xSpecialties,
        w: CAT_COL_W,
      },
    ],
    nodes: [...placed.values()],
    edges,
  };
}

/* -- the eighteen endings: razón → quién se entera ------------------------- */

const REASON_W = 330;
const REASON_H = 36;
const REASON_PITCH = 42;
const ROLE_W = 286;
const ROLE_H = 88;
const ROLE_GAP = 16;
const ROUTE_TOP = 38;

export type RoutingLayout = {
  width: number;
  height: number;
  reasons: (Box & { node: GraphNode; escalation: Escalation })[];
  roles: (Box & { node: GraphNode; incoming: Escalation[] })[];
  edges: PlacedEdge[];
};

/**
 * Eighteen ways a call ends without an appointment, and who hears about each.
 *
 * Reasons are sorted by urgency first and by the person they reach second,
 * which is what makes the picture legible: the three urgencies come out as
 * three horizontal bands, and each listener's routes arrive as one contiguous
 * bundle. A role nobody escalates to still gets drawn — a declared person with
 * no route is a fact about the clinic, not an empty slot to hide.
 */
export function layoutRouting(graph: ClinicGraph, visible: Set<Urgency>): RoutingLayout {
  const roleNodes = graph.nodes.filter((n) => n.kind === "role");
  const declared = new Map(roleNodes.map((n, i) => [n.id, i]));
  const reasonNodes = new Map(
    graph.nodes.filter((n) => n.kind === "reason").map((n) => [n.meta.reason ?? n.id, n]),
  );

  // Listeners are ranked by the loudest route that reaches them, so 112 sits at
  // the top and the front desk at the bottom. Rows then group by listener,
  // which is what removes the crossings: every listener's routes arrive as one
  // contiguous bundle, and the urgencies still read as bands inside it.
  const loudest = new Map<string, number>();
  for (const escalation of graph.escalations) {
    const order = URGENCY[escalation.urgency].order;
    const current = loudest.get(escalation.target);
    if (current === undefined || order < current) loudest.set(escalation.target, order);
  }
  const roleRank = (id: string) => (loudest.get(id) ?? 9) * 100 + (declared.get(id) ?? 99);

  const shown = graph.escalations
    .filter((e) => visible.has(e.urgency))
    .slice()
    .sort(
      (a, b) =>
        roleRank(a.target) - roleRank(b.target) ||
        URGENCY[a.urgency].order - URGENCY[b.urgency].order ||
        a.reason.localeCompare(b.reason),
    );

  const band = Math.max(
    shown.length * REASON_PITCH,
    roleNodes.length * (ROLE_H + ROLE_GAP),
    REASON_PITCH * 8,
  );
  const height = ROUTE_TOP + band + 14;
  const xRoles = CANVAS_WIDTH - ROLE_W;

  const reasonTop = ROUTE_TOP + (band - shown.length * REASON_PITCH) / 2;
  const reasons = shown.map((escalation, i) => {
    const node =
      reasonNodes.get(escalation.reason) ??
      ({
        id: `reason:${escalation.reason}`,
        kind: "reason",
        label: escalation.reason,
        detail: escalation.detail,
        available: true,
        meta: { reason: escalation.reason, urgency: escalation.urgency },
        layer: 0,
        tone: "failure",
      } satisfies GraphNode);
    return { node, escalation, x: 0, y: reasonTop + i * REASON_PITCH, w: REASON_W, h: REASON_H };
  });

  // Each listener sits level with the routes that reach them; the ones nobody
  // escalates to settle at the bottom rather than piling up at y = 0.
  const seats = roleNodes.map((node) => {
    const incoming = shown.filter((e) => e.target === node.id);
    const ys = incoming.map((e) => {
      const row = reasons.find((r) => r.escalation.reason === e.reason);
      return row ? centreY(row) : 0;
    });
    const anchor = ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : Number.POSITIVE_INFINITY;
    return { node, incoming, anchor };
  });

  const ordered = seats
    .slice()
    .sort((a, b) => a.anchor - b.anchor || roleRank(a.node.id) - roleRank(b.node.id));
  let cursor = ROUTE_TOP;
  const rolePos = new Map<string, number>();
  for (const seat of ordered) {
    const wanted = Number.isFinite(seat.anchor) ? seat.anchor - ROLE_H / 2 : cursor;
    const y = Math.max(cursor, wanted);
    rolePos.set(seat.node.id, y);
    cursor = y + ROLE_H + ROLE_GAP;
  }
  // If the stack overflowed the band, slide the whole column back up as one.
  const overflow = cursor - ROLE_GAP - (ROUTE_TOP + band);
  if (overflow > 0) {
    for (const [id, y] of rolePos) rolePos.set(id, y - overflow);
  }

  const roles = seats.map((seat) => ({
    node: seat.node,
    incoming: seat.incoming,
    x: xRoles,
    y: rolePos.get(seat.node.id) ?? ROUTE_TOP,
    w: ROLE_W,
    h: ROLE_H,
  }));

  const edges: PlacedEdge[] = [];
  for (const row of reasons) {
    const role = roles.find((r) => r.node.id === row.escalation.target);
    if (!role) continue;
    edges.push({
      id: `reason:${row.escalation.reason}->${role.node.id}`,
      source: `reason:${row.escalation.reason}`,
      target: role.node.id,
      kind: "escalates_to",
      urgency: row.escalation.urgency,
      d: curve(row.x + row.w, centreY(row), role.x, centreY(role)),
    });
  }

  return { width: CANVAS_WIDTH, height, reasons, roles, edges };
}

/* ----------------------------------------------------------- neighbourhood */

/**
 * Every node one hop from `id`, including itself. `null` means "light it all",
 * which is the resting state of both canvases.
 */
export function neighbourhood(
  edges: { source: string; target: string }[],
  id: string | null,
): Set<string> | null {
  if (!id) return null;
  const lit = new Set<string>([id]);
  for (const edge of edges) {
    if (edge.source === id) lit.add(edge.target);
    if (edge.target === id) lit.add(edge.source);
  }
  return lit;
}

/* ----------------------------------------------------------------- tallies */

export type GraphTally = {
  providers: number;
  onLeave: GraphNode[];
  sites: number;
  specialties: number;
  roles: number;
  reasons: number;
  urgency: Record<Urgency, number>;
  /** works_at + covers: the edges nobody typed, straight off the catalogue. */
  catalogueEdges: number;
  edges: number;
};

export function tally(graph: ClinicGraph): GraphTally {
  const providers = graph.nodes.filter((n) => n.kind === "provider");
  const urgency: Record<Urgency, number> = { now: 0, today: 0, queue: 0 };
  for (const escalation of graph.escalations) {
    if (escalation.urgency in urgency) urgency[escalation.urgency] += 1;
  }
  return {
    providers: providers.length,
    onLeave: providers.filter((n) => !n.available),
    sites: graph.nodes.filter((n) => n.kind === "site").length,
    specialties: graph.nodes.filter((n) => n.kind === "specialty").length,
    roles: graph.nodes.filter((n) => n.kind === "role").length,
    reasons: graph.escalations.length,
    urgency,
    catalogueEdges: graph.edges.filter((e) => e.kind !== "escalates_to").length,
    edges: graph.edges.length,
  };
}

/** "1 profesional" / "12 profesionales", without a ternary at every call site. */
export function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}
