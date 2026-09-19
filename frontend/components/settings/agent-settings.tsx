"use client";

import { useEffect, useState } from "react";

import { LiveAgentReport } from "@/components/settings/live-agent-report";

import { useFrontdesk } from "@/components/frontdesk-provider";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { isValidTunnelUrl } from "@/lib/dni";
import type { AgentSettings, KnowledgeKind, VoicePipeline } from "@/lib/types";

export function AgentSettingsForm() {
  const { settings, saveSettings, addKnowledgeSource, demo } = useFrontdesk();
  const [draft, setDraft] = useState<AgentSettings>(settings);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sql, setSql] = useState("");
  const [apiUrl, setApiUrl] = useState("");

  useEffect(() => {
    queueMicrotask(() => {
      setDraft((current) => ({
        ...current,
        tunnelUrl: settings.tunnelUrl,
        authHeaders: settings.authHeaders,
        voicePipeline: settings.voicePipeline,
        behaviourPrompt: settings.behaviourPrompt,
      }));
    });
  }, [
    settings.authHeaders,
    settings.behaviourPrompt,
    settings.tunnelUrl,
    settings.voicePipeline,
  ]);

  const tunnelOk = !draft.tunnelUrl.trim() || isValidTunnelUrl(draft.tunnelUrl);

  if (!demo) {
    return (
      <div>
        <PageHeader kicker="Settings" title="Wired agent">
          This is what the agent is running right now, read from the process itself.
        </PageHeader>
        <LiveAgentReport />
      </div>
    );
  }

  function persist(next: AgentSettings) {
    const result = saveSettings(next);
    if (!result.ok) {
      setError(result.error);
      setMessage(null);
      return;
    }
    setDraft(next);
    setError(null);
    setMessage("Settings saved.");
  }

  return (
    <div>
      <PageHeader kicker="Connection and voice" title="Agent settings">
        Public tunnel, Pipecat voice, and knowledge sources. None of this
        mutates the EHR.
      </PageHeader>

      <section
        data-reveal=""
        data-delay="1"
        className="mb-[var(--section-gap)] rounded-[18px] border border-mist bg-ash/70 p-[var(--card-padding)] shadow-[var(--shadow-sm)]"
      >
        <h2 className="font-heading text-[clamp(1.65rem,4vw,2.25rem)] text-graphite">
          Tunnel and connection
        </h2>
        <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-steel sm:text-[16px]">
          The public URL the harness dials in Settings → Integration. It must
          be WebSocket.
        </p>
        <div className="mt-8 max-w-2xl space-y-5">
          <div className="space-y-2">
            <Label htmlFor="tunnel" className="font-heading text-[13px] text-quiet">
              Endpoint
            </Label>
            <Input
              id="tunnel"
              value={draft.tunnelUrl}
              placeholder="wss://a1b2c3d4.ngrok-free.app/ws"
              aria-invalid={!tunnelOk}
              className="border-mist bg-canvas-white"
              onChange={(event) =>
                setDraft((current) => ({ ...current, tunnelUrl: event.target.value }))
              }
            />
            {!tunnelOk ? (
              <p className="text-[13px] text-ember-orange">
                Rejected: the value must start with wss:// or ws://
              </p>
            ) : (
              <p className="text-[13px] text-quiet">
                Include the /ws path. https:// is not valid.
              </p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="headers" className="font-heading text-[13px] text-quiet">
              Auth headers
            </Label>
            <Textarea
              id="headers"
              rows={3}
              value={draft.authHeaders}
              placeholder={"X-Api-Key: pk-…"}
              className="border-mist bg-canvas-white"
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  authHeaders: event.target.value,
                }))
              }
            />
          </div>
          <Button onClick={() => persist(draft)} disabled={!tunnelOk}>
            Save connection
          </Button>
        </div>
      </section>

      <section data-reveal="" className="mb-[var(--section-gap)]">
        <h2 className="font-heading text-[clamp(1.65rem,4vw,2.25rem)] text-graphite">
          Personality and voice
        </h2>
        <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-steel sm:text-[16px]">
          Pipecat pipeline presets. The brain is still Helmcode glm5.3.
        </p>
        <div className="mt-8 max-w-2xl space-y-5">
          <div className="space-y-2">
            <Label className="font-heading text-[13px] text-quiet">
              Voice provider
            </Label>
            <Select
              value={draft.voicePipeline}
              onValueChange={(value) =>
                setDraft((current) => ({
                  ...current,
                  voicePipeline: value as VoicePipeline,
                }))
              }
            >
              <SelectTrigger className="w-full border-mist">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="elevenlabs">
                  Pipecat · ElevenLabs turbo v2.5
                </SelectItem>
                <SelectItem value="cartesia">
                  Pipecat · Cartesia sonic (fallback)
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="prompt" className="font-heading text-[13px] text-quiet">
              Behaviour prompt
            </Label>
            <Textarea
              id="prompt"
              rows={7}
              value={draft.behaviourPrompt}
              className="border-mist"
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  behaviourPrompt: event.target.value,
                }))
              }
            />
          </div>
          <Button
            variant="outline"
            onClick={() => persist({ ...settings, ...draft })}
          >
            Save voice and prompt
          </Button>
        </div>
      </section>

      <section
        data-reveal=""
        className="surface rounded-[18px] p-[var(--card-padding)]"
      >
        <h2 className="font-heading text-[clamp(1.65rem,4vw,2.25rem)] text-graphite">
          Data context
        </h2>
        <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-steel sm:text-[16px]">
          CSV, SQL string, or clinic API sync. Only the source is recorded;
          there is no write to the EHR.
        </p>
        <ul className="mt-8 space-y-4">
          {settings.knowledgeSources.map((source) => (
            <li
              key={source.id}
              className="animate-in fade-in slide-in-from-bottom-1 flex flex-col items-start justify-between gap-3 border-t border-mist pt-4 duration-300 sm:flex-row sm:items-center"
            >
              <div>
                <p className="font-heading text-[16px] text-graphite">
                  {source.label}
                </p>
                <p className="mt-1 break-all font-mono text-[12px] text-quiet">
                  {source.detail}
                </p>
              </div>
              <Badge variant="outline" className="border-0 bg-ivory text-brass">
                {source.kind.toUpperCase()}
              </Badge>
            </li>
          ))}
        </ul>
        <div className="mt-8 grid gap-6 md:grid-cols-3">
          <div className="space-y-2">
            <Label htmlFor="csv" className="font-heading text-[13px] text-quiet">
              CSV
            </Label>
            <Input
              id="csv"
              type="file"
              accept=".csv"
              className="border-mist bg-canvas-white"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (!file) {
                  return;
                }
                addKnowledgeSource({
                  kind: "csv" satisfies KnowledgeKind,
                  label: file.name,
                  detail: `${Math.round(file.size / 1024)} KB loaded at reception`,
                  syncedAt: new Date().toISOString(),
                });
                event.target.value = "";
              }}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="sql" className="font-heading text-[13px] text-quiet">
              SQL
            </Label>
            <Input
              id="sql"
              value={sql}
              placeholder="postgres://clinica/ehr"
              className="border-mist bg-canvas-white"
              onChange={(event) => setSql(event.target.value)}
            />
            <Button
              variant="outline"
              disabled={!sql.trim()}
              onClick={() => {
                addKnowledgeSource({
                  kind: "sql",
                  label: "SQL connection",
                  detail: sql.trim(),
                  syncedAt: null,
                });
                setSql("");
              }}
            >
              Register
            </Button>
          </div>
          <div className="space-y-2">
            <Label htmlFor="api" className="font-heading text-[13px] text-quiet">
              Clinic API
            </Label>
            <Input
              id="api"
              value={apiUrl}
              placeholder="https://host/api/v1/directory"
              className="border-mist bg-canvas-white"
              onChange={(event) => setApiUrl(event.target.value)}
            />
            <Button
              variant="outline"
              disabled={!apiUrl.trim()}
              onClick={() => {
                addKnowledgeSource({
                  kind: "api",
                  label: "API sync",
                  detail: apiUrl.trim(),
                  syncedAt: new Date().toISOString(),
                });
                setApiUrl("");
              }}
            >
              Sync
            </Button>
          </div>
        </div>
        <p className="mt-10 text-[13px] text-quiet">
          Sources are stored in this browser. There is no write to the EHR.
        </p>
        {error ? (
          <p className="animate-in fade-in slide-in-from-bottom-1 mt-3 text-ember-orange duration-200">
            {error}
          </p>
        ) : null}
        {message ? (
          <p className="animate-in fade-in slide-in-from-bottom-1 mt-3 text-brass duration-200">
            {message}
          </p>
        ) : null}
      </section>
    </div>
  );
}
