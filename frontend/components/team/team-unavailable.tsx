"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { FAULTS, type Fault } from "@/lib/team";

/**
 * What the screen says when the agent will not hand over the directory.
 *
 * It names the exact failure instead of "algo ha ido mal". The likeliest one
 * today is `session`: these routes want a signed-in person and there is not a
 * single account yet, so a 401 here is the system working, not a bug, and the
 * screen says so rather than sending somebody to read logs.
 */
export function TeamUnavailable({
  fault,
  detail,
  onRetry,
}: {
  fault: Fault;
  detail: string;
  onRetry: () => void;
}) {
  const said = FAULTS[fault] ?? FAULTS.upstream;
  const expected = fault === "session";

  return (
    <div>
      <PageHeader kicker="Clínica Arenal" title="Quién responde, y cómo se le habla">
        Aquí se edita a quién llama el agente cuando una llamada no acaba en cita, y qué se le
        dice a cada persona cuando descuelga. Ahora mismo el agente no lo está sirviendo.
      </PageHeader>

      <div
        className={`max-w-[48rem] rounded-[16px] border px-5 py-5 ${
          expected ? "border-mist bg-ash/60" : "border-ember-orange/30 bg-ivory"
        }`}
      >
        <p className="flex items-center gap-2 font-heading text-[15px] text-graphite">
          <AlertTriangle className={`size-4 ${expected ? "text-brass" : "text-ember-orange"}`} />
          {said.title}
        </p>
        <p className="mt-2 text-[13.5px] leading-[1.6] text-steel">{said.hint}</p>
        {detail && detail !== said.title ? (
          <p className="mt-3 border-t border-mist pt-3 font-mono text-[12px] leading-[1.6] text-quiet">
            El agente ha dicho, literal: {detail}
          </p>
        ) : null}
        <Button variant="outline" size="sm" className="mt-4" onClick={onRetry}>
          <RefreshCw /> Volver a preguntar
        </Button>
      </div>
    </div>
  );
}
