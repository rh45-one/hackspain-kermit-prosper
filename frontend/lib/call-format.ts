export function formatElapsed(startedAt: string, nowMs: number): string {
  const start = Date.parse(startedAt);
  if (!Number.isFinite(start)) {
    return "—";
  }
  const elapsed = Math.max(0, Math.floor((nowMs - start) / 1000));
  const hours = Math.floor(elapsed / 3600);
  const minutes = Math.floor((elapsed % 3600) / 60);
  const seconds = elapsed % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function callDisplayName(name: string | undefined): string {
  const trimmed = name?.trim();
  return trimmed && trimmed.length > 0 ? trimmed : "Persona desconocida";
}

/** Human label for the phone line (hides socket ids like sock-04). */
export function callLineLabel(socketId: string): string {
  const digits = socketId.replace(/\D/g, "");
  if (digits.length > 0) {
    return `Línea ${Number.parseInt(digits, 10)}`;
  }
  return "Línea de recepción";
}

export function callCardElementId(callId: string): string {
  return `call-card-${callId}`;
}
