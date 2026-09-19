/** Shapes served by /ops/api/live/*. The backend owns this contract. */

export type LiveStatus = "en curso" | "finalizada" | "sin cierre";

export type LiveCallRow = {
  call_id: string;
  status: LiveStatus;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  patient: string | null;
  /** The agent read a possible medical emergency somewhere in this call. */
  medical_emergency: boolean;
  headline: string;
  turns: number;
  submissions_ok: number;
  submissions_failed: number;
};

export type LiveEvent = { at: string; text: string };
export type LiveTurn = { speaker: "agente" | "paciente"; text: string };

export type LiveCallDetail = Omit<LiveCallRow, "headline" | "turns"> & {
  events: LiveEvent[];
  conversation: LiveTurn[];
};

export const STATUS_STYLES: Record<LiveStatus, string> = {
  "en curso": "bg-ember-orange/10 text-ember-orange",
  finalizada: "bg-mist text-graphite",
  "sin cierre": "bg-ash text-quiet",
};

/** "1 min 46 s", or a dash when the call never recorded a close. */
export function formatDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) {
    return "—";
  }
  if (seconds < 60) {
    return `${seconds} s`;
  }
  return `${Math.floor(seconds / 60)} min ${String(seconds % 60).padStart(2, "0")} s`;
}

/** Clock time in the clinic's own timezone; the panel hangs on a clinic wall. */
export function clockTime(iso: string): string {
  const parsed = Date.parse(iso);
  if (!Number.isFinite(parsed)) {
    return "—";
  }
  return new Intl.DateTimeFormat("es-ES", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Madrid",
  }).format(parsed);
}
