/**
 * The clinic's people and routes, as the panel sees them.
 *
 * The contract is the backend's (`agent/ops/directory.py`); this file only
 * mirrors it and adds the two things a screen needs and an API has no reason
 * to send: the Spanish words for what each field means, and a way to tell the
 * four ways this can fail apart from each other.
 *
 * Pure. Imported from client components: no `process.env`, and the one place
 * that talks to the network is `ask`, which only ever calls this origin's own
 * proxy (`/api/orgs/*`). The ops token lives in that proxy and never here.
 */

export type Source = "configured" | "default";
export type Urgency = "now" | "today" | "queue";

/** Everything the agent needs in order to ring one person. */
export type Person = {
  slug: string;
  name: string;
  role: string;
  detail: string;
  languages: string[];
  provider_id: string | null;
  phone: string;
  email: string;
  /** What to say when *this* person picks up. */
  opening: string;
  may_ask: string[];
  must_not_ask: string[];
  active: boolean;
  source: Source;
};

export type RouteRow = {
  reason: string;
  person_slug: string;
  urgency: Urgency;
  detail: string;
  source: Source;
  /** False means it points at somebody who no longer answers. */
  reachable: boolean;
};

/** The six-to-nine keys `cover_brief` emits. Empty ones are dropped upstream. */
export type Brief = Partial<
  Record<
    "reason" | "who" | "because" | "urgency" | "gap" | "speaks" | "opening" | "may_ask" | "must_not_ask",
    string
  >
>;

export type CallProfile = { person: Person; brief: Brief };

export const BRIEF_LABELS: Record<keyof Brief, string> = {
  reason: "Por qué se la llama",
  who: "A quién se llama",
  because: "Qué le decimos que pasa",
  urgency: "Con qué urgencia",
  gap: "Qué hueco hay en juego",
  speaks: "En qué idioma se abre",
  opening: "Cómo se abre con ella",
  may_ask: "Se le puede pedir",
  must_not_ask: "No se le pide",
};

/** The order the brief reads in. A prompt renders these keys in this order. */
export const BRIEF_ORDER: (keyof Brief)[] = [
  "who",
  "speaks",
  "opening",
  "reason",
  "because",
  "urgency",
  "gap",
  "may_ask",
  "must_not_ask",
];

/**
 * How loud each ending is, in the words somebody who does not read code uses.
 * Colour is never the only signal: each one also carries its own sentence.
 */
export const URGENCY: Record<Urgency, { word: string; gloss: string; chip: string }> = {
  now: {
    word: "Ahora",
    gloss: "Interrumpe a alguien. Suena aunque esté en consulta.",
    chip: "bg-ember-orange/12 text-ember-orange",
  },
  today: {
    word: "Hoy",
    gloss: "Le llega antes de que se vaya. No interrumpe.",
    chip: "bg-ivory text-brass",
  },
  queue: {
    word: "En cola",
    gloss: "Espera. Se mira cuando se mira la cola.",
    chip: "bg-mist text-steel",
  },
};

export const URGENCY_ORDER: Urgency[] = ["now", "today", "queue"];

/** The languages the catalogue returns, plus the two a Spanish clinic hires for. */
export const LANGUAGES: Record<string, string> = {
  es: "español",
  en: "inglés",
  ca: "català",
  gl: "galego",
  eu: "euskara",
};

export function saidLanguages(codes: string[]): string {
  return codes.map((code) => LANGUAGES[code] ?? code).join(", ");
}

/** The four roles `clinic/graph.py` declares by hand, said out loud. */
export const ROLE_LABELS: Record<string, string> = {
  front_desk: "Recepción",
  manager: "Coordinación",
  on_call: "Guardia",
  emergency: "Emergencias",
  provider: "Profesional",
  other: "Otro",
};

export const ROLE_OPTIONS = ["front_desk", "manager", "on_call", "emergency", "provider", "other"];

/**
 * The four slugs `clinic/graph.py` declares by hand. Used for **wording only**:
 * deleting one of these restores its default, deleting anything else removes
 * the person outright, and the two deserve different sentences on a button.
 * The truth is still the list the DELETE returns, which the screen re-reads.
 */
export const DECLARED_SLUGS = new Set(["front_desk", "manager", "on_call", "emergency"]);

/* ------------------------------------------------------------------ errors */

export type Fault =
  | "token"
  | "session"
  | "membership"
  | "role"
  | "host"
  | "route"
  | "upstream"
  | "request";

/**
 * What the screen says for each way this breaks, and what to do about it.
 * Never "algo ha ido mal": each of these has a different fix and a different
 * person who applies it.
 */
export const FAULTS: Record<Fault, { title: string; hint: string }> = {
  session: {
    title: "Hace falta iniciar sesión",
    hint: "Esta pantalla enseña teléfonos y correos del personal, así que el agente pide una persona con sesión abierta, no sólo el token de servicio del panel. Todavía no hay ninguna cuenta creada: se dan de alta con `python -m agent.accounts.bootstrap --email tu@clinica.es` en el host del agente, y después se entra en /ops/login.",
  },
  token: {
    title: "Al panel le falta el token de operaciones",
    hint: "El agente exige la cabecera X-Ops-Token y el proxy del panel no la lleva. Define OPS_TOKEN en el entorno del panel (en Vercel, o en .env.local si estás en local) con el mismo secreto que el despliegue. Nunca lo llames NEXT_PUBLIC_*: eso lo metería en el navegador.",
  },
  membership: {
    title: "Esa cuenta no pertenece a esta clínica",
    hint: "La sesión está abierta pero la persona no es miembro de la organización que el panel está pidiendo. Revisa ORG_ID en el entorno del panel, o añade la pertenencia con `--org`.",
  },
  role: {
    title: "Hace falta ser admin de la clínica",
    hint: "Cualquier miembro puede leer esta pantalla; escribir es de owner o admin. Pídele a quien administre la organización que te suba el rol.",
  },
  host: {
    title: "No se puede hablar con el agente",
    hint: "El panel ha llamado y no ha contestado nadie. Revisa AGENT_HTTP_BASE_URL y que el despliegue esté en pie.",
  },
  route: {
    title: "Ese agente todavía no sirve el directorio",
    hint: "El despliegue al que apunta el panel es anterior a /ops/api/orgs/{org}/people. Vuelve a desplegar el backend o apunta AGENT_HTTP_BASE_URL a uno que ya la tenga.",
  },
  upstream: {
    title: "El agente ha rechazado el cambio",
    hint: "La petición ha llegado y el backend la ha contestado con un error. El detalle de abajo es suyo, literal.",
  },
  request: {
    title: "El panel ha pedido algo que no existe",
    hint: "Es un fallo del propio panel, no del agente ni de la configuración.",
  },
};

export class TeamError extends Error {
  readonly fault: Fault;
  readonly status: number;

  constructor(fault: Fault, detail: string, status: number) {
    super(detail || FAULTS[fault].title);
    this.name = "TeamError";
    this.fault = fault;
    this.status = status;
  }
}

/** One call to this origin's proxy, with the failure already classified. */
export async function ask<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/orgs/${path}`, { cache: "no-store", ...init });
  } catch {
    throw new TeamError("host", "El panel no ha podido ni salir a la red.", 0);
  }

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  const record = (payload ?? {}) as { detail?: unknown; fault?: unknown };
  if (response.ok) {
    return payload as T;
  }
  const fault = typeof record.fault === "string" ? (record.fault as Fault) : "upstream";
  throw new TeamError(
    fault in FAULTS ? fault : "upstream",
    typeof record.detail === "string" ? record.detail : `El agente ha respondido ${response.status}.`,
    response.status,
  );
}

/* ------------------------------------------------------------------- drafts */

export type PersonDraft = Omit<Person, "source"> & { source?: Source };

export function draftOf(person: Person): PersonDraft {
  return { ...person, languages: [...person.languages], may_ask: [...person.may_ask], must_not_ask: [...person.must_not_ask] };
}

export function emptyDraft(): PersonDraft {
  return {
    slug: "",
    name: "",
    role: "other",
    detail: "",
    languages: [],
    provider_id: null,
    phone: "",
    email: "",
    opening: "",
    may_ask: [],
    must_not_ask: [],
    active: true,
  };
}

/** What `PUT /people/{slug}` accepts. The slug travels in the path, not here. */
export function personBody(draft: PersonDraft) {
  return {
    name: draft.name.trim(),
    role: draft.role,
    detail: draft.detail.trim(),
    languages: draft.languages,
    provider_id: draft.provider_id?.trim() ? draft.provider_id.trim() : null,
    phone: draft.phone.trim(),
    email: draft.email.trim(),
    opening: draft.opening.trim(),
    may_ask: draft.may_ask.map((item) => item.trim()).filter(Boolean),
    must_not_ask: draft.must_not_ask.map((item) => item.trim()).filter(Boolean),
    active: draft.active,
  };
}

/** True when the form no longer says what the agent has stored. */
export function isDirty(draft: PersonDraft, saved: Person | null): boolean {
  if (saved === null) {
    return true;
  }
  return JSON.stringify(personBody(draft)) !== JSON.stringify(personBody(draftOf(saved)));
}

/** A slug the backend will accept: lowercase, no dots, nothing that walks a path. */
export function slugify(raw: string): string {
  return raw
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63);
}

/** Free text, one item per line. The two ask-lists are edited this way. */
export function linesToList(raw: string): string[] {
  return raw.split("\n").map((line) => line.trim()).filter(Boolean);
}
