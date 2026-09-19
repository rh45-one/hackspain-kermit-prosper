import { voiceWsUrlFromRequest } from "@/lib/voice-origin";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  return Response.json(
    { wsUrl: voiceWsUrlFromRequest(request) },
    { headers: { "Cache-Control": "no-store" } },
  );
}
