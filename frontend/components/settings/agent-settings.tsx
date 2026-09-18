"use client";

import { useEffect, useState } from "react";

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
  const { settings, saveSettings, addKnowledgeSource } = useFrontdesk();
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

  function persist(next: AgentSettings) {
    const result = saveSettings(next);
    if (!result.ok) {
      setError(result.error);
      setMessage(null);
      return;
    }
    setDraft(next);
    setError(null);
    setMessage("Configuración guardada.");
  }

  return (
    <div>
      <PageHeader kicker="Conexión y voz" title="Configuración del agente">
        Túnel público, voz Pipecat y orígenes de conocimiento. Nada de esto
        muta el EHR.
      </PageHeader>

      <section
        data-reveal=""
        data-delay="1"
        className="mb-[var(--section-gap)] rounded-[18px] border border-mist bg-ash/70 p-[var(--card-padding)] shadow-[var(--shadow-sm)]"
      >
        <h2 className="font-heading text-[clamp(1.65rem,4vw,2.25rem)] text-graphite">
          Túnel y conexión
        </h2>
        <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-steel sm:text-[16px]">
          La URL pública que el harness marca en Settings → Integration. Debe
          ser WebSocket.
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
                Rechazado: el valor tiene que empezar por wss:// o ws://
              </p>
            ) : (
              <p className="text-[13px] text-quiet">
                Incluye la ruta /ws. https:// no es válido.
              </p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="headers" className="font-heading text-[13px] text-quiet">
              Cabeceras de autorización
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
            Guardar conexión
          </Button>
        </div>
      </section>

      <section data-reveal="" className="mb-[var(--section-gap)]">
        <h2 className="font-heading text-[clamp(1.65rem,4vw,2.25rem)] text-graphite">
          Personalidad y voz
        </h2>
        <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-steel sm:text-[16px]">
          Presets del pipeline Pipecat. El cerebro sigue siendo Helmcode glm5.3.
        </p>
        <div className="mt-8 max-w-2xl space-y-5">
          <div className="space-y-2">
            <Label className="font-heading text-[13px] text-quiet">
              Proveedor de voz
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
              Prompt de comportamiento
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
            Guardar voz y prompt
          </Button>
        </div>
      </section>

      <section
        data-reveal=""
        className="surface rounded-[18px] p-[var(--card-padding)]"
      >
        <h2 className="font-heading text-[clamp(1.65rem,4vw,2.25rem)] text-graphite">
          Contexto de datos
        </h2>
        <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-steel sm:text-[16px]">
          CSV, cadena SQL o sincronización con la API de la clínica. Solo se
          registra el origen; no hay escritura al EHR.
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
                  detail: `${Math.round(file.size / 1024)} KB cargados en recepción`,
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
                  label: "Conexión SQL",
                  detail: sql.trim(),
                  syncedAt: null,
                });
                setSql("");
              }}
            >
              Registrar
            </Button>
          </div>
          <div className="space-y-2">
            <Label htmlFor="api" className="font-heading text-[13px] text-quiet">
              API clínica
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
                  label: "Sincronización API",
                  detail: apiUrl.trim(),
                  syncedAt: new Date().toISOString(),
                });
                setApiUrl("");
              }}
            >
              Sincronizar
            </Button>
          </div>
        </div>
        <p className="mt-10 text-[13px] text-quiet">
          Los orígenes se guardan en este navegador. No hay escritura al EHR.
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
