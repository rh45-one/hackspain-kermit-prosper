import { voiceHttpBase } from "@/lib/voice-origin";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const upstream = await fetch(`${voiceHttpBase()}/healthz`, {
      cache: "no-store",
      signal: AbortSignal.timeout(2500),
    });
    if (!upstream.ok) {
      return Response.json({ ok: false }, { status: 503, headers: { "Cache-Control": "no-store" } });
    }
    return Response.json({ ok: true }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ ok: false }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
