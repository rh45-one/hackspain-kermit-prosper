"use client";

import { useEffect, useState } from "react";

import { useFrontdesk } from "@/components/frontdesk-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
    setDraft((current) => ({
      ...current,
      tunnelUrl: settings.tunnelUrl,
      authHeaders: settings.authHeaders,
      voicePipeline: settings.voicePipeline,
      behaviourPrompt: settings.behaviourPrompt,
    }));
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
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold tracking-tight text-slate-900">
          Configuración del agente
        </h2>
        <p className="text-sm text-slate-500">
          Túnel público, voz Pipecat y orígenes de conocimiento. Nada de esto
          muta el EHR.
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Túnel y conexión</CardTitle>
          <CardDescription>
            La URL pública que el harness marca en Settings → Integration. Debe
            ser WebSocket.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="tunnel">Endpoint</Label>
            <Input
              id="tunnel"
              value={draft.tunnelUrl}
              placeholder="wss://a1b2c3d4.ngrok-free.app/ws"
              aria-invalid={!tunnelOk}
              onChange={(event) =>
                setDraft((current) => ({ ...current, tunnelUrl: event.target.value }))
              }
            />
            {!tunnelOk ? (
              <p className="text-xs text-red-700">
                Rechazado: el valor tiene que empezar por wss:// o ws://
              </p>
            ) : (
              <p className="text-xs text-slate-500">
                Incluye la ruta /ws. https:// no es válido.
              </p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="headers">Cabeceras de autorización</Label>
            <Textarea
              id="headers"
              rows={3}
              value={draft.authHeaders}
              placeholder={'X-Api-Key: pk-…'}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  authHeaders: event.target.value,
                }))
              }
            />
          </div>
          <Button
            onClick={() => persist(draft)}
            disabled={!tunnelOk}
          >
            Guardar conexión
          </Button>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Personalidad y voz</CardTitle>
          <CardDescription>
            Presets del pipeline Pipecat. El cerebro sigue siendo Helmcode glm5.3.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>Proveedor de voz</Label>
            <Select
              value={draft.voicePipeline}
              onValueChange={(value) =>
                setDraft((current) => ({
                  ...current,
                  voicePipeline: value as VoicePipeline,
                }))
              }
            >
              <SelectTrigger>
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
            <Label htmlFor="prompt">Prompt de comportamiento</Label>
            <Textarea
              id="prompt"
              rows={7}
              value={draft.behaviourPrompt}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  behaviourPrompt: event.target.value,
                }))
              }
            />
          </div>
          <Button
            variant="secondary"
            onClick={() => persist({ ...settings, ...draft })}
          >
            Guardar voz y prompt
          </Button>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Contexto de datos</CardTitle>
          <CardDescription>
            CSV, cadena SQL o sincronización con la API de la clínica. Solo se
            registra el origen; no hay escritura al EHR.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <ul className="space-y-2">
            {settings.knowledgeSources.map((source) => (
              <li
                key={source.id}
                className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm"
              >
                <div>
                  <p className="font-medium">{source.label}</p>
                  <p className="font-mono text-xs text-slate-500">{source.detail}</p>
                </div>
                <Badge variant="outline">{source.kind.toUpperCase()}</Badge>
              </li>
            ))}
          </ul>
          <div className="grid gap-4 md:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="csv">CSV</Label>
              <Input
                id="csv"
                type="file"
                accept=".csv"
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
              <Label htmlFor="sql">SQL</Label>
              <Input
                id="sql"
                value={sql}
                placeholder="postgres://clinica/ehr"
                onChange={(event) => setSql(event.target.value)}
              />
              <Button
                size="sm"
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
              <Label htmlFor="api">API clínica</Label>
              <Input
                id="api"
                value={apiUrl}
                placeholder="https://host/api/v1/directory"
                onChange={(event) => setApiUrl(event.target.value)}
              />
              <Button
                size="sm"
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
          <p className="text-xs text-slate-400">
            Los orígenes se guardan en este navegador. No hay escritura al EHR.
          </p>
          {error ? <p className="text-sm text-red-700">{error}</p> : null}
          {message ? <p className="text-sm text-emerald-700">{message}</p> : null}
        </CardContent>
      </Card>
    </div>
  );
}
