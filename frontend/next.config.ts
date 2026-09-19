import type { NextConfig } from "next";

/**
 * The agent's own pages, served under this domain.
 *
 * A session cookie belongs to the host that set it. Logging in at
 * `prosper-clinicreflow.fly.dev/ops/login` gives the browser a cookie for
 * that host, and this panel lives on another one, so the browser never sends
 * it here and `/equipo` asks you to sign in forever — while the very same
 * account works fine if you open the agent directly. Two hosts, one session,
 * and no way to join them from the client.
 *
 * Proxying the agent's login under this domain is what joins them: the
 * `Set-Cookie` comes back through this origin, so the cookie is first-party
 * here, and the server-side proxies in `app/api/*` forward it onwards.
 *
 * `/ws` is deliberately NOT here. A WebSocket through a rewrite adds a hop to
 * a three-minute phone call for nothing, and the browser call page already
 * resolves the agent's own host.
 */
const AGENT =
  process.env.AGENT_HTTP_BASE_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:7861";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/ops/login", destination: `${AGENT}/ops/login` },
      { source: "/ops/logout", destination: `${AGENT}/ops/logout` },
      { source: "/ops/api/session", destination: `${AGENT}/ops/api/session` },
      { source: "/ops/api/session/:path*", destination: `${AGENT}/ops/api/session/:path*` },
    ];
  },
};

export default nextConfig;
