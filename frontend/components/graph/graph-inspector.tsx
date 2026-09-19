"use client";

import {
  languageName,
  plural,
  specialtyLabelById,
  URGENCY,
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
}: {
  graph: ClinicGraph;
  node: GraphNode | null;
  onPick: (id: string) => void;
}) {
  if (!node) {
    return (
      <div className="rounded-[14px] border border-dashed border-mist bg-fog/70 px-5 py-4">
        <p className="text-[13px] leading-[1.6] text-quiet">
          Pasa por encima de cualquier nodo para encenderle los vecinos, o pincha uno para
          dejarlo fijo y leer aquí de dónde sale cada dato.
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
            De baja
          </span>
        ) : null}
      </div>

      <dl className="mt-3 divide-y divide-mist/70">
        {node.kind === "provider" ? (
          <>
            <Row term="Especialidad">
              {specialtyLabelById(node.meta.specialty_id ?? "", node.detail || "—")}
            </Row>
            <Row term="Pasa consulta">{names(graph, sites)}</Row>
            <Row term="Idiomas">
              {(node.meta.languages ?? []).map(languageName).join(", ") || "—"}
            </Row>
            <Row term="Se le puede citar">
              {node.available ? (
                "Sí."
              ) : (
                <>
                  No: está de baja, así que ninguna petición puede acabar en él.{" "}
                  <button
                    type="button"
                    onClick={() => onPick("reason:provider_on_leave")}
                    className="ember-underline cursor-pointer text-ember-orange"
                  >
                    Ver a quién se avisa
                  </button>
                </>
              )}
            </Row>
          </>
        ) : null}

        {node.kind === "site" ? (
          <>
            <Row term="Dirección">{node.detail || "—"}</Row>
            <Row term="Profesionales">{names(graph, workedBy)}</Row>
          </>
        ) : null}

        {node.kind === "specialty" ? (
          <>
            <Row term="La cubren">{names(graph, workedBy)}</Row>
            <Row term="Nombre API">
              <span className="font-mono text-[12px]">{node.label}</span>
            </Row>
          </>
        ) : null}

        {node.kind === "role" ? (
          <>
            <Row term="Qué hace">{node.detail || "—"}</Row>
            <Row term="Qué le llega">
              {listens.length === 0 ? (
                "Nada. Está declarado en el grafo y hoy no hay ninguna razón enrutada a él."
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
            <Row term="Qué ha pasado">{escalation.detail}</Row>
            <Row term="Quién se entera">
              <button
                type="button"
                onClick={() => onPick(escalation.target)}
                className="ember-underline cursor-pointer"
              >
                {graph.nodes.find((n) => n.id === escalation.target)?.label ?? escalation.target}
              </button>
            </Row>
            <Row term="Con qué prisa">
              {graph.legend.urgency[escalation.urgency] ?? escalation.urgency}
            </Row>
            {escalation.reason === "provider_on_leave" ? (
              <Row term="Hoy afecta a">
                {away.length === 0
                  ? "A nadie: todos los médicos del catálogo están disponibles."
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
            <Row term="Id del reto">
              <span className="font-mono text-[12px]">{escalation.reason}</span>
            </Row>
          </>
        ) : null}
      </dl>

      {node.kind === "role" && listens.length > 0 ? (
        <p className="mt-3 text-[12px] leading-[1.5] text-quiet">
          {plural(listens.length, "razón", "razones")} de las {graph.escalations.length} acaban
          aquí.
        </p>
      ) : null}
    </div>
  );
}
