"use client";

import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { CallQrDialog } from "@/components/graph/call-qr";
import { CatalogueMap } from "@/components/graph/catalogue-map";
import { GraphInspector } from "@/components/graph/graph-inspector";
import { GraphKeyframes } from "@/components/graph/graph-canvas";
import { RoutingMap } from "@/components/graph/routing-map";
import { PageHeader } from "@/components/layout/page-header";
import {
  callSubject,
  EDGE_INK,
  EDGE_WORD,
  layoutCatalogue,
  layoutRouting,
  neighbourhood,
  plural,
  tally,
  TONE,
  URGENCY,
  type CallSubject,
  type ClinicGraph,
  type GraphTone,
  type Urgency,
} from "@/lib/graph";
import { cn } from "@/lib/utils";

const URGENCIES: Urgency[] = ["now", "today", "queue"];

function Stat({ value, label, note }: { value: string; label: string; note?: string }) {
  return (
    <div className="rounded-[14px] border border-mist bg-canvas-white px-4 py-3.5 shadow-[var(--shadow-sm)]">
      <p className="font-heading text-[26px] leading-none tracking-[-0.04em] text-graphite">
        {value}
      </p>
      <p className="mt-2 font-heading text-[11px] leading-none tracking-[0.07em] text-brass uppercase">
        {label}
      </p>
      {note ? <p className="mt-1.5 text-[12px] leading-[1.4] text-quiet">{note}</p> : null}
    </div>
  );
}

function SectionTitle({
  kicker,
  title,
  children,
}: {
  kicker: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-5">
      <p className="mb-2 flex items-center gap-2.5 font-heading text-[11px] leading-none tracking-[0.08em] text-brass uppercase">
        <span className="h-px w-5 bg-brass/70" />
        <span>{kicker}</span>
      </p>
      <h2 className="font-heading text-[clamp(1.35rem,2.4vw,1.85rem)] leading-tight tracking-[-0.035em] text-graphite">
        {title}
      </h2>
      <p className="mt-2 max-w-[46rem] text-[14px] leading-[1.6] text-steel">{children}</p>
    </div>
  );
}

/**
 * La dirección de la llamada, con el motivo dentro.
 *
 * El QR abría `/call/` a secas, así que la llamada que salía del grafo era
 * una llamada de recepcionista cualquiera: el agente descolgaba sin saber a
 * quién llamaba ni por qué. El contexto estaba en la pantalla y se quedaba
 * en la pantalla.
 *
 * Con `reason` y `person` el servidor resuelve el informe entero desde el
 * directorio de la clínica — qué hace esa persona, a quién sustituye, qué
 * puede y qué no se le puede pedir. Y `situation` lleva lo que alguien ha
 * escrito arriba con sus palabras, que vale más que la frase de catálogo de
 * un motivo: esa frase es cierta para todas las ausencias, y esta llamada va
 * de una.
 */
function callWithContext(base: string, subject: CallSubject, situation: string): string {
  const params = new URLSearchParams({
    reason: subject.escalation.reason,
    person: subject.escalation.target,
  });
  if (situation.trim()) params.set("situation", situation.trim());
  return `${base}${base.includes("?") ? "&" : "?"}${params}`;
}

export function ClinicGraphBoard({
  graph,
  callUrl,
  cover,
  highlight,
  situation = "",
}: {
  graph: ClinicGraph;
  /** Public address of the agent's browser call page, resolved on the server. */
  callUrl: string;
  /** The cover question, rendered on the server. Optional: the board predates it. */
  cover?: ReactNode;
  /**
   * Node to open pinned, which is how the suggestion reaches the drawing: the
   * page refreshes with an answer and the graph is already pointing at the
   * person, instead of naming somebody the reader then has to go and find.
   *
   * Initial state only, on purpose. Once the page is up the pin belongs to
   * whoever is clicking, and a prop that kept re-pinning would fight them.
   */
  highlight?: string | null;
  /** Lo que alguien escribió en la caja de cobertura, para que viaje a la llamada. */
  situation?: string;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(highlight ?? null);
  const [visible, setVisible] = useState<Set<Urgency>>(() => new Set(URGENCIES));
  const [calling, setCalling] = useState<CallSubject | null>(null);

  const active = hovered ?? pinned;
  const counts = useMemo(() => tally(graph), [graph]);
  const catalogue = useMemo(() => layoutCatalogue(graph), [graph]);
  const routing = useMemo(() => layoutRouting(graph, visible), [graph, visible]);

  const byId = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph.nodes]);
  const catalogueIds = useMemo(
    () => new Set(catalogue.nodes.map((p) => p.node.id)),
    [catalogue.nodes],
  );
  const routingIds = useMemo(
    () =>
      new Set([
        ...routing.reasons.map((r) => r.node.id),
        ...routing.roles.map((r) => r.node.id),
      ]),
    [routing.reasons, routing.roles],
  );

  /**
   * Each canvas only dims for a node it actually draws, so hovering a doctor
   * does not black out the escalation map. The one exception is deliberate and
   * comes straight from the data: "Médico de baja" lights the doctors whose
   * `available` is false, which is the whole point of keeping them drawn.
   */
  const catalogueLit = useMemo(() => {
    if (!active) return null;
    if (active === "reason:provider_on_leave") {
      const away = counts.onLeave.map((n) => n.id);
      return away.length ? new Set(away) : null;
    }
    return catalogueIds.has(active) ? neighbourhood(catalogue.edges, active) : null;
  }, [active, catalogue.edges, catalogueIds, counts.onLeave]);

  const routingLit = useMemo(
    () => (active && routingIds.has(active) ? neighbourhood(routing.edges, active) : null),
    [active, routing.edges, routingIds],
  );

  const pick = useCallback((id: string) => {
    setPinned((current) => (current === id ? null : id));
    setHovered(null);
  }, []);

  const toggleUrgency = useCallback((key: Urgency) => {
    setVisible((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      // Hiding everything leaves an empty canvas and no way back on a touch
      // screen, so the last urgency standing cannot be switched off.
      return next.size === 0 ? current : next;
    });
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // The dialog closes before the pin does, so Escape never wipes the
      // context out from under the person demoing it.
      if (calling) setCalling(null);
      else setPinned(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [calling]);

  const pinnedNode = pinned ? (byId.get(pinned) ?? null) : null;
  const pinnedCall = useMemo(
    () => (pinnedNode ? callSubject(graph, pinnedNode) : null),
    [graph, pinnedNode],
  );
  const filtered = visible.size < URGENCIES.length;

  return (
    <div className="pb-24">
      <GraphKeyframes />

      {cover ?? null}

      <PageHeader kicker="Clínica Arenal" title="El grafo de la clínica">
        Quién existe, quién cubre qué, quién está dónde — y las {counts.reasons} formas en que
        una llamada puede acabar sin cita, cada una con la persona a la que le llega. Todo lo
        que ves lo calcula el agente del catálogo que publica la clínica: el panel no inventa ni
        un nodo.
      </PageHeader>

      <div
        data-reveal=""
        className="mb-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
      >
        <Stat
          value={String(counts.providers)}
          label="Profesionales"
          note={
            counts.onLeave.length === 0
              ? "todos disponibles hoy"
              : `${plural(counts.onLeave.length, "de baja", "de baja")}: ${counts.onLeave
                  .map((n) => n.label)
                  .join(", ")}`
          }
        />
        <Stat
          value={`${counts.specialties} · ${counts.sites}`}
          label="Especialidades y sedes"
          note={`${counts.catalogueEdges} aristas calculadas del catálogo`}
        />
        <Stat
          value={String(counts.reasons)}
          label="Finales sin cita"
          note="vocabulario cerrado: uno más y falla un test"
        />
        <Stat
          value={`${counts.urgency.now} · ${counts.urgency.today} · ${counts.urgency.queue}`}
          label="Ahora · Hoy · En cola"
          note={`${counts.roles} personas en la plantilla`}
        />
      </div>

      {!graph.warm ? (
        <p className="mb-8 rounded-[12px] border border-brass/30 bg-ivory px-4 py-3 text-[13px] leading-[1.55] text-steel">
          El catálogo todavía no está caliente en el agente, así que este dibujo solo trae las
          personas declaradas y los finales cerrados. Los médicos, las sedes y las especialidades
          aparecerán en cuanto la clínica responda.
        </p>
      ) : null}

      <section data-reveal="" className="mb-14">
        <SectionTitle kicker="Capa 1 · el catálogo" title="La clínica entera de un vistazo">
          Cada médico está unido a las sedes donde pasa consulta y a la disciplina que cubre.
          Pasa por encima de uno para aislar su vecindario. Los que están{" "}
          <span className="text-graphite">de baja siguen dibujados, apagados</span>: borrarlos
          escondería justo el motivo por el que una petición no se puede atender.
        </SectionTitle>
        <div className="rounded-[18px] border border-mist bg-fog/45 p-4 sm:p-6">
          <CatalogueMap
            graph={graph}
            layout={catalogue}
            active={active}
            lit={catalogueLit}
            onHover={setHovered}
            onSelect={pick}
          />
          <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-mist/80 pt-4">
            {(["covers", "works_at"] as const).map((kind) => (
              <span key={kind} className="flex items-center gap-2 text-[12px] text-steel">
                <svg width="26" height="8" aria-hidden className="overflow-visible">
                  <path
                    d="M 0 4 C 9 4, 17 4, 26 4"
                    fill="none"
                    stroke={EDGE_INK[kind]}
                    strokeWidth={1.6}
                    strokeOpacity={0.6}
                  />
                </svg>
                {EDGE_WORD[kind]}
              </span>
            ))}
            {(["person", "place", "discipline"] as GraphTone[]).map((tone) => (
              <span key={tone} className="flex items-center gap-2 text-[12px] text-steel">
                <span
                  aria-hidden
                  className="size-1.5 rounded-full"
                  style={{ background: TONE[tone].ink }}
                />
                {TONE[tone].label}
              </span>
            ))}
            <span className="flex items-center gap-2 text-[12px] text-steel">
              <span
                aria-hidden
                className="h-3 w-5 rounded-[4px] border border-dashed border-quiet bg-fog"
              />
              De baja, no se le puede citar
            </span>
          </div>
        </div>
      </section>

      <section data-reveal="">
        <SectionTitle
          kicker="Capa 2 · el escalado"
          title={`Las ${counts.reasons} formas de acabar sin cita`}
        >
          Esto es lo que nadie más enseña: cuando el agente no puede citar, no se limita a
          colgar. Cada final tiene un destinatario y una prisa.{" "}
          <span className="text-graphite">Ahora</span> interrumpe a alguien,{" "}
          <span className="text-graphite">hoy</span> le llega antes de que se vaya, y{" "}
          <span className="text-graphite">en cola</span> espera a que alguien lo mire.
        </SectionTitle>

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <span className="mr-1 font-heading text-[11px] tracking-[0.07em] text-quiet uppercase">
            Filtrar por prisa
          </span>
          {URGENCIES.map((key) => {
            const on = visible.has(key);
            return (
              <button
                key={key}
                type="button"
                onClick={() => toggleUrgency(key)}
                aria-pressed={on}
                className={cn(
                  "cursor-pointer rounded-full border px-3 py-1.5 font-heading text-[12px] tracking-[0.02em] transition-colors duration-200",
                  on ? "text-canvas-white" : "border-mist bg-canvas-white text-quiet",
                )}
                style={
                  on
                    ? { background: URGENCY[key].ink, borderColor: URGENCY[key].ink }
                    : undefined
                }
              >
                {URGENCY[key].word}
                <span className={cn("ml-1.5", on ? "opacity-70" : "opacity-60")}>
                  {counts.urgency[key]}
                </span>
              </button>
            );
          })}
          {filtered ? (
            <button
              type="button"
              onClick={() => setVisible(new Set(URGENCIES))}
              className="cursor-pointer text-[12px] text-quiet underline underline-offset-4 hover:text-graphite"
            >
              ver las {counts.reasons}
            </button>
          ) : null}
        </div>

        <div className="rounded-[18px] border border-mist bg-fog/45 p-4 sm:p-6">
          <RoutingMap
            layout={routing}
            filtered={filtered}
            active={active}
            lit={routingLit}
            onHover={setHovered}
            onSelect={pick}
          />
          <dl className="mt-4 grid gap-3 border-t border-mist/80 pt-4 sm:grid-cols-3">
            {URGENCIES.map((key) => (
              <div key={key} className="flex items-start gap-2.5">
                <svg width="30" height="10" aria-hidden className="mt-1.5 shrink-0 overflow-visible">
                  <path
                    d="M 0 5 C 10 5, 20 5, 30 5"
                    fill="none"
                    stroke={URGENCY[key].ink}
                    strokeWidth={URGENCY[key].width}
                    strokeDasharray={URGENCY[key].dash}
                    strokeLinecap="round"
                  />
                </svg>
                <div>
                  <dt
                    className="font-heading text-[12px] tracking-[0.04em] uppercase"
                    style={{ color: URGENCY[key].ink }}
                  >
                    {URGENCY[key].word}
                  </dt>
                  <dd className="text-[12.5px] leading-[1.45] text-steel">
                    {graph.legend.urgency[key]}
                  </dd>
                </div>
              </div>
            ))}
          </dl>
        </div>
      </section>

      {pinnedNode ? (
        <div className="pointer-events-none fixed inset-x-0 bottom-0 z-40 flex justify-center px-[var(--page-gutter)] pb-5">
          <div className="pointer-events-auto w-full max-w-[680px]">
            <div className="relative">
              <button
                type="button"
                onClick={() => setPinned(null)}
                className="absolute -top-2.5 right-2 z-10 cursor-pointer rounded-full border border-mist bg-canvas-white px-2.5 py-1 font-heading text-[11px] tracking-[0.04em] text-quiet uppercase shadow-[var(--shadow-sm)] hover:text-graphite"
              >
                Cerrar
              </button>
              <div className="max-h-[56vh] overflow-y-auto rounded-[16px] shadow-[var(--shadow-md)]">
                <GraphInspector
                  graph={graph}
                  node={pinnedNode}
                  onPick={pick}
                  subject={pinnedCall}
                  onCall={pinnedCall ? () => setCalling(pinnedCall) : undefined}
                />
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {calling ? (
        <CallQrDialog
          subject={calling}
          url={callWithContext(callUrl, calling, situation)}
          urgencyNote={graph.legend.urgency[calling.escalation.urgency]}
          onClose={() => setCalling(null)}
        />
      ) : null}
    </div>
  );
}
