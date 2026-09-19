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
export type EdgeKind = "works_at" | "covers" | "escalates_to" | "covers_for";

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
  human: { ink: "#1d211f", label: "Clinic people" },
  discipline: { ink: "#4c534e", label: "Specialty" },
  person: { ink: "#1d211f", label: "Clinician" },
  place: { ink: "#806b36", label: "Site" },
  failure: { ink: "#e76432", label: "No-booking ending" },
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
  now: { ink: "#d92d20", word: "Now", width: 2.6, order: 0 },
  today: { ink: "#806b36", word: "Today", width: 1.7, order: 1 },
  queue: { ink: "#8d948e", word: "Queued", width: 1.2, dash: "5 5", order: 2 },
};

export const EDGE_INK: Record<EdgeKind, string> = {
  works_at: "#806b36",
  covers: "#4c534e",
  escalates_to: "#e76432",
  covers_for: "#4c8c78",
};

export const EDGE_WORD: Record<EdgeKind, string> = {
  works_at: "sees patients at",
  covers: "covers",
  escalates_to: "alerts",
  covers_for: "covers for",
};

/* ------------------------------------------------------------------- words */

/**
 * The catalogue names specialties in English because the challenge's API does.
 * The id is what travels; this is only what a Spanish-speaking jury reads, and
 * an unknown specialty falls back to the catalogue's own label rather than
 * disappearing.
 */
const SPECIALTY_EN: Record<string, string> = {
  general_practice: "General practice",
  paediatrics: "Paediatrics",
  dermatology: "Dermatology",
  orthopaedics: "Orthopaedics",
  gynaecology: "Gynaecology",
  physiotherapy: "Physiotherapy",
};

export function specialtyLabel(node: GraphNode): string {
  return SPECIALTY_EN[node.id.replace(/^sp:/, "")] ?? node.label;
}

export function specialtyLabelById(specialtyId: string, fallback: string): string {
  return SPECIALTY_EN[specialtyId] ?? fallback;
}

const LANGUAGE_EN: Record<string, string> = {
  es: "Spanish",
  en: "English",
  ca: "Catalan",
  gl: "Galician",
  eu: "Basque",
};

export function languageName(code: string): string {
  return LANGUAGE_EN[code] ?? code.toUpperCase();
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
      { id: "site", title: "Sites", note: `${sites.length} centres`, x: xSites, w: CAT_COL_W },
      {
        id: "provider",
        title: "Clinicians",
        note: `${providers.length} doctors`,
        x: xProviders,
        w: CAT_COL_W,
      },
      {
        id: "specialty",
        title: "Specialties",
        note: `${specialties.length} disciplines`,
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
// A person in a cover chain draws smaller than a person a route reaches: the
// column is a chain of substitutes, not a list of listeners, and at the same
// size forty-three boxes read as forty-three equals.
const CHAIN_W = 208;
const CHAIN_H = 64;
const CHAIN_GAP_X = 26;
const CHAIN_GAP_Y = 10;

export type RoutingLayout = {
  width: number;
  height: number;
  reasons: (Box & { node: GraphNode; escalation: Escalation })[];
  roles: (Box & { node: GraphNode; incoming: Escalation[] })[];
  /** Everybody else: the cover chains, hanging off the person they step in for. */
  chain: (Box & { node: GraphNode })[];
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
  const everyone = graph.nodes.filter((n) => n.kind === "role");

  /**
   * Who substitutes for whom. Read first, because it is what splits this
   * column in two.
   *
   * With forty-three people the old rule — one big box each, anchored to the
   * routes that reach them — drew a four-thousand-pixel ladder in which the
   * eight people a route actually reaches were indistinguishable from the
   * thirty-five who step in when one of those eight cannot. Same size, same
   * column, no order. The information was all there and none of it was
   * legible.
   *
   * So the column keeps the listeners, and everybody else hangs off the
   * person they cover, to the right and smaller. The shape of the picture
   * then says the thing the data says: a route reaches somebody, and behind
   * that somebody there is a chain.
   */
  const parentOf = new Map<string, string>();
  for (const edge of graph.edges) {
    if (edge.kind === "covers_for" && edge.source !== edge.target) {
      parentOf.set(edge.source, edge.target);
    }
  }
  const roleNodes = everyone.filter((n) => !parentOf.has(n.id));
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

  /**
   * And then the rest of the clinic, hanging off the people the routes reach.
   *
   * This column used to be only the listeners, so the graph knew who hears
   * about a problem and had nothing to say about who actually steps in — the
   * team was a different screen. A rota is a chain: the route reaches the
   * head of gynaecology, the head is off, and the question is who is next.
   * Drawn here, next to the person they cover, the answer is on the same
   * picture as the question.
   *
   * Each hop of a chain is a narrower column to the right, and a chain's own
   * column keeps its own cursor, so two chains of different lengths never
   * land on top of each other.
   */
  const children = new Map<string, GraphNode[]>();
  for (const node of everyone) {
    const parent = parentOf.get(node.id);
    if (parent === undefined || parent === node.id) continue;
    const list = children.get(parent);
    if (list) list.push(node);
    else children.set(parent, [node]);
  }

  const seated = new Set(roles.map((r) => r.node.id));
  const chain: RoutingLayout["chain"] = [];
  // One cursor per depth: a column packs downwards and never overlaps itself.
  const cursors = new Map<number, number>();
  const placed = new Map<string, Box>();

  const walk = (id: string, anchor: Box, depth: number) => {
    for (const child of children.get(id) ?? []) {
      // A cycle in the data — two people covering each other — would walk
      // forever. Seating each person once is the whole guard needed.
      if (seated.has(child.id) || depth > 4) continue;
      seated.add(child.id);
      // El primer salto arranca DESPUÉS de la caja de oyente, que es más
      // ancha que las de cadena. Multiplicar por `CHAIN_W` desde el principio
      // lo metía 52 px dentro de la columna anterior, y lo que se veía eran
      // las fichas montadas unas encima de otras.
      const x =
        xRoles + ROLE_W + CHAIN_GAP_X + (depth - 1) * (CHAIN_W + CHAIN_GAP_X);
      const floor = cursors.get(depth) ?? ROUTE_TOP;
      const y = Math.max(floor, centreY(anchor) - CHAIN_H / 2);
      cursors.set(depth, y + CHAIN_H + CHAIN_GAP_Y);
      const box = { x, y, w: CHAIN_W, h: CHAIN_H };
      placed.set(child.id, box);
      chain.push({ node: child, ...box });
      edges.push({
        id: `covers:${child.id}->${id}`,
        source: child.id,
        target: id,
        kind: "covers_for",
        d: curve(x, y + CHAIN_H / 2, anchor.x + anchor.w, centreY(anchor)),
      });
      walk(child.id, box, depth + 1);
    }
  };
  // Roots first, in the order the listener column already settled on, so a
  // chain starts level with the person it belongs to.
  for (const seat of roles) walk(seat.node.id, seat, 1);
  // Anybody left covers somebody who is not on the picture — a chain whose
  // root was deleted, or one that loops. They are still staff and still have
  // to be drawn; a person who vanishes because their row is odd is worse than
  // a person sitting slightly out of place.
  for (const node of everyone) {
    if (seated.has(node.id)) continue;
    seated.add(node.id);
    const floor = cursors.get(1) ?? ROUTE_TOP;
    const box = { x: xRoles + ROLE_W + CHAIN_GAP_X, y: floor, w: CHAIN_W, h: CHAIN_H };
    cursors.set(1, floor + CHAIN_H + CHAIN_GAP_Y);
    placed.set(node.id, box);
    chain.push({ node, ...box });
    walk(node.id, box, 2);
  }

  const deepest = chain.reduce((m, c) => Math.max(m, c.x + c.w), CANVAS_WIDTH);
  const lowest = chain.reduce((m, c) => Math.max(m, c.y + c.h), height);
  return {
    width: deepest + 8,
    height: Math.max(height, lowest + 14),
    reasons,
    roles,
    chain,
    edges,
  };
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

/* -------------------------------------------------------------- the call */

/**
 * Who a pinned node means calling, and why.
 *
 * The routing map has two sides and the "Llamar" button has to work from
 * either. Pin a reason and the person is the one that reason escalates to.
 * Pin a person and the reason is the loudest route that reaches them — the one
 * that would make the phone ring first — with the rest counted, not hidden.
 *
 * Returns `null` for anything that is not a call: a doctor, a site, or a
 * declared person nobody escalates to. A button that opens a call about
 * nothing would be the panel inventing a story the graph does not tell.
 */
export type CallSubject = {
  /** The declared person who picks up. */
  role: GraphNode;
  /** The ending that puts the call through to them. */
  escalation: Escalation;
  /** What that ending is called on screen, in Spanish. */
  reasonLabel: string;
  /** How many other endings also reach this person. */
  otherRoutes: number;
};

export function callSubject(graph: ClinicGraph, node: GraphNode): CallSubject | null {
  const label = (reason: string) =>
    graph.nodes.find((n) => n.meta.reason === reason)?.label ?? reason;

  if (node.kind === "reason" || node.meta.reason) {
    const reason = node.meta.reason ?? node.id.replace(/^reason:/, "");
    const escalation = graph.escalations.find((e) => e.reason === reason);
    if (!escalation) return null;
    const role = graph.nodes.find((n) => n.id === escalation.target);
    if (!role) return null;
    return { role, escalation, reasonLabel: label(escalation.reason), otherRoutes: 0 };
  }

  if (node.kind === "role") {
    const incoming = graph.escalations
      .filter((e) => e.target === node.id)
      .slice()
      .sort(
        (a, b) =>
          URGENCY[a.urgency].order - URGENCY[b.urgency].order || a.reason.localeCompare(b.reason),
      );
    const escalation = incoming[0];
    if (!escalation) return null;
    return {
      role: node,
      escalation,
      reasonLabel: label(escalation.reason),
      otherRoutes: incoming.length - 1,
    };
  }

  return null;
}
