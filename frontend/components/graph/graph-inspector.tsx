"use client";

import { CallButton } from "@/components/graph/call-qr";
import {
  languageName,
  plural,
  specialtyLabelById,
  URGENCY,
  type CallSubject,
  type ClinicGraph,
  type GraphNode,
} from "@/lib/graph";
import { cn } from "@/lib/utils";

/**
 * What the selected node actually is, in words.
 *
 * The picture shows the shape; this shows the facts behind it, including the
 * technical id the challenge uses, so nobody has to trust that the drawing and
 * the backend agree.
 */

function Row({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3 py-1.5">
      <dt className="w-28 shrink-0 font-heading text-[11px] leading-[1.5] tracking-[0.06em] text-quiet uppercase">
        {term}
      </dt>
      <dd className="min-w-0 flex-1 text-[13px] leading-[1.5] text-steel">{children}</dd>
    </div>
  );
}

function names(graph: ClinicGraph, ids: string[]): string {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const found = ids.map((id) => byId.get(id)?.label ?? id);
  return found.length ? found.join(", ") : "—";
}

export function GraphInspector({
  graph,
  node,
  onPick,
  subject,
  onCall,
}: {
  graph: ClinicGraph;
  node: GraphNode | null;
  onPick: (id: string) => void;
  /** Who this node means calling, when it means calling anyone. */
  subject?: CallSubject | null;
  onCall?: () => void;
}) {
  if (!node) {
    return (
      <div className="rounded-[14px] border border-dashed border-mist bg-fog/70 px-5 py-4">
        <p className="text-[13px] leading-[1.6] text-quiet">
          Hover any node to light its neighbours, or click one to pin it and
          read here where each fact comes from.
        </p>
      </div>
    );
  }

  const sites = graph.edges
    .filter((e) => e.kind === "works_at" && e.source === node.id)
    .map((e) => e.target);
  const workedBy = graph.edges
    .filter((e) => (e.kind === "works_at" || e.kind === "covers") && e.target === node.id)
    .map((e) => e.source);
  const escalation = graph.escalations.find((e) => `reason:${e.reason}` === node.id);
  const listens = graph.escalations.filter((e) => e.target === node.id);
  const away = graph.nodes.filter((n) => n.kind === "provider" && !n.available);
  const urgency = escalation ? URGENCY[escalation.urgency] : null;

  return (
    <div
      className={cn(
        "rounded-[14px] border bg-canvas-white px-5 py-4 shadow-[var(--shadow-sm)]",
        node.available ? "border-mist" : "border-dashed border-ember-orange/40",
      )}
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="font-heading text-[17px] leading-tight text-graphite">{node.label}</h3>
        <span className="font-mono text-[11px] text-quiet">
          {node.meta.reason ?? node.id}
        </span>
        {urgency ? (
          <span
            className="rounded-full px-2 py-0.5 font-heading text-[10px] tracking-[0.06em] uppercase"
            style={{ background: `${urgency.ink}16`, color: urgency.ink }}
          >
            {urgency.word}
          </span>
        ) : null}
        {node.kind === "provider" && !node.available ? (
          <span className="rounded-full bg-ember-orange/12 px-2 py-0.5 font-heading text-[10px] tracking-[0.06em] text-ember-orange uppercase">
            On leave
          </span>
        ) : null}
      </div>

      {subject && onCall ? <CallButton subject={subject} onClick={onCall} /> : null}

      <dl className="mt-3 divide-y divide-mist/70">
        {node.kind === "provider" ? (
          <>
            <Row term="Specialty">
              {specialtyLabelById(node.meta.specialty_id ?? "", node.detail || "—")}
            </Row>
            <Row term="Sees patients at">{names(graph, sites)}</Row>
            <Row term="Languages">
              {(node.meta.languages ?? []).map(languageName).join(", ") || "—"}
            </Row>
            <Row term="Can be booked">
              {node.available ? (
                "Yes."
              ) : (
                <>
                  No: they are on leave, so no request can end with them.{" "}
                  <button
                    type="button"
                    onClick={() => onPick("reason:provider_on_leave")}
                    className="ember-underline cursor-pointer text-ember-orange"
                  >
                    See who is alerted
                  </button>
                </>
              )}
            </Row>
          </>
        ) : null}

        {node.kind === "site" ? (
          <>
            <Row term="Address">{node.detail || "—"}</Row>
            <Row term="Clinicians">{names(graph, workedBy)}</Row>
          </>
        ) : null}

        {node.kind === "specialty" ? (
          <>
            <Row term="Covered by">{names(graph, workedBy)}</Row>
            <Row term="API name">
              <span className="font-mono text-[12px]">{node.label}</span>
            </Row>
          </>
        ) : null}

        {node.kind === "role" ? (
          <>
            <Row term="What they do">{node.detail || "—"}</Row>
            <Row term="What reaches them">
              {listens.length === 0 ? (
                "Nothing. They are declared on the graph and today no reason is routed to them."
              ) : (
                <ul className="space-y-1">
                  {listens.map((item) => {
                    const ink = URGENCY[item.urgency].ink;
                    const label =
                      graph.nodes.find((n) => n.meta.reason === item.reason)?.label ?? item.reason;
                    return (
                      <li key={item.reason} className="flex items-start gap-2">
                        <span
                          aria-hidden
                          className="mt-[7px] size-1.5 shrink-0 rounded-full"
                          style={{ background: ink }}
                        />
                        <button
                          type="button"
                          onClick={() => onPick(`reason:${item.reason}`)}
                          className="cursor-pointer text-left hover:text-graphite"
                        >
                          {label}{" "}
                          <span className="text-quiet">— {item.detail}</span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </Row>
          </>
        ) : null}

        {escalation ? (
          <>
            <Row term="What happened">{escalation.detail}</Row>
            <Row term="Who hears">
              <button
                type="button"
                onClick={() => onPick(escalation.target)}
                className="ember-underline cursor-pointer"
              >
                {graph.nodes.find((n) => n.id === escalation.target)?.label ?? escalation.target}
              </button>
            </Row>
            <Row term="How fast">
              {graph.legend.urgency[escalation.urgency] ?? escalation.urgency}
            </Row>
            {escalation.reason === "provider_on_leave" ? (
              <Row term="Affects today">
                {away.length === 0
                  ? "Nobody: every clinician in the catalogue is available."
                  : away.map((doctor, index) => (
                      <span key={doctor.id}>
                        {index > 0 ? ", " : ""}
                        <button
                          type="button"
                          onClick={() => onPick(doctor.id)}
                          className="ember-underline cursor-pointer"
                        >
                          {doctor.label}
                        </button>
                      </span>
                    ))}
              </Row>
            ) : null}
            <Row term="Challenge id">
              <span className="font-mono text-[12px]">{escalation.reason}</span>
            </Row>
          </>
        ) : null}
      </dl>

      {node.kind === "role" && listens.length > 0 ? (
        <p className="mt-3 text-[12px] leading-[1.5] text-quiet">
          {plural(listens.length, "reason", "reasons")} of {graph.escalations.length} end
          here.
        </p>
      ) : null}
    </div>
  );
}
