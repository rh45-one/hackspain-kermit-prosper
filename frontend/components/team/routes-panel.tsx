"use client";

import { useState } from "react";
import { Loader2, RotateCcw, TriangleAlert } from "lucide-react";

import { SourceBadge, UrgencyChip } from "@/components/team/marks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  TeamError,
  URGENCY,
  URGENCY_ORDER,
  ask,
  type Person,
  type RouteRow,
  type Urgency,
} from "@/lib/team";
import { REASON_LABELS } from "@/lib/outcomes";
import type { OutcomeReason } from "@/lib/types";
import { cn } from "@/lib/utils";

function reasonLabel(reason: string): string {
  return REASON_LABELS[reason as OutcomeReason] ?? reason;
}

/**
 * The eighteen ways a call can end without an appointment, and who hears about
 * each one.
 *
 * Sorted by urgency and not alphabetically: the question somebody opens this
 * with is "what wakes a person up", and the answer should be the first three
 * lines rather than something to hunt for. A route pointing at nobody is
 * pulled to the very top with its own banner — `reachable: false` is the one
 * state here that must never be discovered during an emergency.
 */
export function RoutesPanel({
  routes,
  people,
  onChanged,
  onFault,
}: {
  routes: RouteRow[];
  people: Person[];
  onChanged: () => void;
  onFault: (error: TeamError) => void;
}) {
  const broken = routes.filter((route) => !route.reachable);
  const sorted = [...routes].sort((a, b) => {
    if (a.reachable !== b.reachable) {
      return a.reachable ? 1 : -1;
    }
    const byUrgency = URGENCY_ORDER.indexOf(a.urgency) - URGENCY_ORDER.indexOf(b.urgency);
    return byUrgency !== 0 ? byUrgency : reasonLabel(a.reason).localeCompare(reasonLabel(b.reason), "es");
  });

  return (
    <div>
      <div className="mb-5 grid gap-3 sm:grid-cols-3">
        {URGENCY_ORDER.map((urgency) => (
          <div key={urgency} className="rounded-[12px] border border-mist bg-canvas-white px-3.5 py-3">
            <UrgencyChip urgency={urgency} />
            <p className="mt-2 text-[12.5px] leading-[1.5] text-steel">{URGENCY[urgency].gloss}</p>
            <p className="mt-1.5 font-heading text-[12px] text-quiet">
              {routes.filter((route) => route.urgency === urgency).length} de {routes.length} razones
            </p>
          </div>
        ))}
      </div>

      {broken.length > 0 ? (
        <div className="mb-5 rounded-[14px] border border-ember-orange/35 bg-ivory px-4 py-3.5">
          <p className="flex items-center gap-2 font-heading text-[14px] text-graphite">
            <TriangleAlert className="size-4 text-ember-orange" />
            {broken.length === 1
              ? "Una razón apunta a alguien que ya no existe"
              : `${broken.length} razones apuntan a alguien que ya no existe`}
          </p>
          <p className="mt-1.5 text-[13px] leading-[1.55] text-steel">
            Cuando una llamada acabe así, el agente no tendrá a quién avisar. Están las primeras de
            la lista, marcadas en naranja.
          </p>
        </div>
      ) : null}

      <div className="overflow-hidden rounded-[16px] border border-mist bg-canvas-white">
        {sorted.map((route, index) => (
          <RouteLine
            // Keyed by the saved values, not just the reason: when a save comes
            // back the line remounts and its draft is the agent's answer again,
            // which is one remount instead of an effect that copies props into
            // state and can disagree with them.
            key={`${route.reason}|${route.person_slug}|${route.urgency}|${route.detail}|${route.source}`}
            route={route}
            people={people}
            first={index === 0}
            onChanged={onChanged}
            onFault={onFault}
          />
        ))}
      </div>
    </div>
  );
}

function RouteLine({
  route,
  people,
  first,
  onChanged,
  onFault,
}: {
  route: RouteRow;
  people: Person[];
  first: boolean;
  onChanged: () => void;
  onFault: (error: TeamError) => void;
}) {
  const [target, setTarget] = useState(route.person_slug);
  const [urgency, setUrgency] = useState<Urgency>(route.urgency);
  const [detail, setDetail] = useState(route.detail);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dirty =
    target !== route.person_slug || urgency !== route.urgency || detail !== route.detail;
  const who = people.find((person) => person.slug === route.person_slug);

  async function run(work: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await work();
      onChanged();
    } catch (caught) {
      const failure = caught as TeamError;
      if (failure.fault === "upstream" || failure.status === 400 || failure.status === 404) {
        setError(failure.message);
      } else {
        onFault(failure);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className={cn(
        "grid gap-3 px-4 py-3.5 lg:grid-cols-[minmax(0,15rem)_minmax(0,11rem)_minmax(0,9rem)_minmax(0,1fr)_auto] lg:items-center",
        !first && "border-t border-mist",
        !route.reachable && "bg-ivory",
      )}
    >
      <div className="min-w-0">
        <p className="flex items-center gap-2 font-heading text-[14px] text-graphite">
          {!route.reachable ? <TriangleAlert className="size-3.5 shrink-0 text-ember-orange" /> : null}
          <span className="truncate">{reasonLabel(route.reason)}</span>
        </p>
        <p className="mt-0.5 truncate font-mono text-[11px] text-quiet">{route.reason}</p>
      </div>

      <div className="min-w-0">
        <select
          aria-label={`A quién le llega «${reasonLabel(route.reason)}»`}
          value={target}
          onChange={(event) => setTarget(event.target.value)}
          className={cn(
            "h-9 w-full rounded-[10px] border bg-canvas-white px-2.5 font-heading text-[13px] text-graphite outline-none focus-visible:ring-2 focus-visible:ring-brass/35",
            route.reachable ? "border-mist" : "border-ember-orange/50",
          )}
        >
          {!route.reachable ? (
            <option value={route.person_slug}>{route.person_slug} · ya no existe</option>
          ) : null}
          {people.map((person) => (
            <option key={person.slug} value={person.slug}>
              {person.name}
              {person.active ? "" : " · no se le llama"}
            </option>
          ))}
        </select>
      </div>

      <div className="min-w-0">
        <select
          aria-label={`Con qué urgencia le llega «${reasonLabel(route.reason)}»`}
          value={urgency}
          onChange={(event) => setUrgency(event.target.value as Urgency)}
          className="h-9 w-full rounded-[10px] border border-mist bg-canvas-white px-2.5 font-heading text-[13px] text-graphite outline-none focus-visible:ring-2 focus-visible:ring-brass/35"
          title={URGENCY[urgency].gloss}
        >
          {URGENCY_ORDER.map((value) => (
            <option key={value} value={value}>
              {URGENCY[value].word}
            </option>
          ))}
        </select>
      </div>

      <div className="min-w-0">
        <Input
          aria-label={`Qué se le dice sobre «${reasonLabel(route.reason)}»`}
          value={detail}
          className="h-9 border-mist bg-canvas-white text-[13px]"
          placeholder="Qué se le cuenta cuando descuelgue"
          onChange={(event) => setDetail(event.target.value)}
        />
        {error ? <p className="mt-1.5 text-[12px] leading-[1.45] text-ember-orange">{error}</p> : null}
        {!error && who && !who.active ? (
          <p className="mt-1.5 text-[12px] leading-[1.45] text-brass">
            {who.name} está marcada como «no se le llama».
          </p>
        ) : null}
      </div>

      <div className="flex shrink-0 items-center gap-2 justify-self-start lg:justify-self-end">
        {dirty ? (
          <>
            <Button
              size="sm"
              disabled={busy}
              onClick={() =>
                void run(() =>
                  ask(`routes/${route.reason}`, {
                    method: "PUT",
                    headers: { "content-type": "application/json" },
                    body: JSON.stringify({ person_slug: target, urgency, detail }),
                  }),
                )
              }
            >
              {busy ? <Loader2 className="animate-spin" /> : null}
              Guardar
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => {
                setTarget(route.person_slug);
                setUrgency(route.urgency);
                setDetail(route.detail);
                setError(null);
              }}
            >
              Deshacer
            </Button>
          </>
        ) : (
          <>
            <UrgencyChip urgency={route.urgency} />
            <SourceBadge source={route.source} />
            {route.source === "configured" ? (
              <Button
                size="icon-sm"
                variant="ghost"
                disabled={busy}
                title="Volver a la ruta declarada por la clínica"
                aria-label={`Volver a la ruta declarada para «${reasonLabel(route.reason)}»`}
                onClick={() => void run(() => ask(`routes/${route.reason}`, { method: "DELETE" }))}
              >
                {busy ? <Loader2 className="animate-spin" /> : <RotateCcw />}
              </Button>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
