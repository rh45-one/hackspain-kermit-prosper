import { cn } from "@/lib/utils";
import { URGENCY, type Source, type Urgency } from "@/lib/team";

/**
 * The one distinction this whole screen exists to make visible.
 *
 * A value nobody has touched and a value somebody wrote are different facts,
 * and a panel that draws them the same way is a panel that lets a clinic
 * believe it configured something it never configured. Colour is not the only
 * signal: the default is also dashed, also lighter, and also says the word.
 */
export function SourceBadge({ source, className }: { source: Source; className?: string }) {
  const configured = source === "configured";
  return (
    <span
      className={cn(
        "inline-flex h-[22px] shrink-0 items-center rounded-full px-2.5 font-heading text-[10.5px] tracking-[0.04em] uppercase",
        configured
          ? "bg-graphite text-canvas-white"
          : "border border-dashed border-mist bg-transparent text-quiet",
        className,
      )}
      title={
        configured
          ? "Lo ha escrito alguien de la clínica. Se puede devolver al valor por defecto."
          : "Nadie lo ha tocado: es lo que trae el sistema. Se puede escribir encima."
      }
    >
      {configured ? "Escrito aquí" : "Por defecto"}
    </span>
  );
}

/** How loud an ending is. Word first, colour second, so it reads on a projector. */
export function UrgencyChip({ urgency, className }: { urgency: Urgency; className?: string }) {
  const said = URGENCY[urgency];
  return (
    <span
      className={cn(
        "inline-flex h-[22px] shrink-0 items-center rounded-full px-2.5 font-heading text-[11px]",
        said.chip,
        className,
      )}
      title={said.gloss}
    >
      {said.word}
    </span>
  );
}
