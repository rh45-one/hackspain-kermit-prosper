const LOOPBACK = new Set(["127.0.0.1", "::1", "localhost", "0.0.0.0"]);

function isLoopback(hostname: string): boolean {
  return LOOPBACK.has(hostname);
}

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

  // Borrowing the hostname from the incoming request only makes sense when the
  // voice process answers on the same host as this page — local development,
  // or one tunnel in front of both. Deployed they are two hosts: the panel is
  // on Vercel and the agent is on Fly, and the request host is Vercel, which
  // serves no /ws/demo. That is why "Tu línea" could not place a call in
  // production while the health check went green: the health check goes
  // through this server's proxy and the socket does not.
  const remote = !isLoopback(voice.hostname);
  if (remote) {
    const votePort = voice.port && voice.port !== "80" && voice.port !== "443"
      ? `:${voice.port}`
      : "";
    const secure = voice.protocol === "https:" ? "wss:" : "ws:";
    return `${secure}//${voice.hostname}${votePort}/ws/demo`;
  }

  const port = voice.port;
  const host = port && port !== "80" && port !== "443" ? `${hostname}:${port}` : hostname;
  return `${proto}//${host}/ws/demo`;
}
