import { MOCK_APPOINTMENTS } from "@/lib/mock-data";
import { outcomeFromAction, REASON_LABELS } from "@/lib/outcomes";
import { CALL_CAPACITY, type LiveCall, type ReceptionOutcome } from "@/lib/types";

export type HourlyPoint = {
  hour: string;
  sockets: number;
  submissions: number;
};

/** Concurrent sockets vs POSTs in the 30s window — mock of a Saturday Run All. */
export const HOURLY_LOAD: HourlyPoint[] = [
  { hour: "08", sockets: 1, submissions: 1 },
  { hour: "09", sockets: 2, submissions: 2 },
  { hour: "10", sockets: 4, submissions: 3 },
  { hour: "11", sockets: 8, submissions: 8 },
  { hour: "12", sockets: 10, submissions: 9 },
  { hour: "13", sockets: 7, submissions: 7 },
  { hour: "14", sockets: 5, submissions: 5 },
  { hour: "15", sockets: 6, submissions: 6 },
  { hour: "16", sockets: 9, submissions: 8 },
  { hour: "17", sockets: 4, submissions: 4 },
  { hour: "18", sockets: 3, submissions: 3 },
  { hour: "19", sockets: 2, submissions: 2 },
];

export const FLUSH_WITHIN_WINDOW = 0.94;
export const FLUSH_P50_SECONDS = 4.2;

export function outcomeMix(appointments = MOCK_APPOINTMENTS) {
  const counts: Record<ReceptionOutcome, number> = {
    BOOKED: 0,
    CANCELLED: 0,
    REFUSED: 0,
    DIVERTED: 0,
  };
  for (const item of appointments) {
    counts[outcomeFromAction(item.action)] += 1;
  }
  const total = Object.values(counts).reduce((sum, value) => sum + value, 0) || 1;
  return (Object.keys(counts) as ReceptionOutcome[]).map((key) => ({
    key,
    count: counts[key],
    share: counts[key] / total,
  }));
}

export function refusalReasons(appointments = MOCK_APPOINTMENTS) {
  const counts = new Map<string, number>();
  for (const item of appointments) {
    if (item.action !== "NO_ACTION" || !item.reason) {
      continue;
    }
    counts.set(item.reason, (counts.get(item.reason) ?? 0) + 1);
  }
  return [...counts.entries()].map(([reason, count]) => ({
    reason,
    label: REASON_LABELS[reason as keyof typeof REASON_LABELS] ?? reason,
    count,
  }));
}

export function bargeInCount(calls: LiveCall[]): number {
  return calls.filter((call) => call.turn === "barge-in" && call.status === "active")
    .length;
}

export function capacityShare(activeCount: number): number {
  return activeCount / CALL_CAPACITY;
}
