/** HTTP origin of the voice process (`/healthz`, `/ws/demo`). Not a secret. */
export function voiceHttpBase(): string {
  return (
    process.env.VOICE_HTTP_BASE_URL ??
    process.env.AGENT_HTTP_BASE_URL ??
    "http://127.0.0.1:7860"
  ).replace(/\/$/, "");
}

export function voiceWsUrlFromRequest(request: Request): string {
  const voice = new URL(voiceHttpBase());
  const incoming = new URL(request.url);
  const forwardedHost = request.headers.get("x-forwarded-host");
  const hostHeader = forwardedHost ?? request.headers.get("host") ?? incoming.host;
  const hostname = hostHeader.split(":")[0] || voice.hostname;
  const forwardedProto = request.headers.get("x-forwarded-proto");
  const https =
    forwardedProto === "https" ||
    incoming.protocol === "https:" ||
    voice.protocol === "https:";
  const proto = https ? "wss:" : "ws:";

  if (process.env.VOICE_SAME_ORIGIN === "true") {
    return `${proto}//${hostHeader}/ws/demo`;
  }

  const port = voice.port;
  const host = port && port !== "80" && port !== "443" ? `${hostname}:${port}` : hostname;
  return `${proto}//${host}/ws/demo`;
}
