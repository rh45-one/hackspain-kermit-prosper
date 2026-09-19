import { Badge } from "@/components/ui/badge";
import { displayCode } from "@/lib/arena-business";
import type { TriageLevel } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

const TRIAGE_BADGE: Record<TriageLevel, string> = {
  LEVEL_I: "border-0 bg-destructive/12 text-destructive",
  LEVEL_II: "border-0 bg-ember-orange/15 text-ember-orange",
  LEVEL_III: "border-0 bg-brass/15 text-brass",
  LEVEL_IV: "border-0 bg-[#1f6b4a]/12 text-[#1f6b4a]",
  LEVEL_V: "border-0 bg-[#2f5f8a]/12 text-[#2f5f8a]",
};

export function TriageLevelBadge({ level }: { level: TriageLevel }) {
  return (
    <Badge variant="secondary" className={cn(TRIAGE_BADGE[level])}>
      {displayCode(level)}
    </Badge>
  );
}
