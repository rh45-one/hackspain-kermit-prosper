"use client";

import { useEffect, useState } from "react";

/**
 * What the agent is actually running, read from the process that runs it.
 *
 * This replaced three paragraphs of instructions, two of which had stopped
 * being true: it told you to set VOICE_ENGINE to cascade — which cannot start,
 * its Helmcode key is a placeholder and the API answers 401 — and it said the
 * configuration had no API months after `/ops/api/live/agent` grew one.
 *
 * Read-only on purpose. What runs is decided when the process boots, and a
 * screen with editable-looking controls over something it cannot change is
 * worse than a screen that says so.
 */
type AgentReport = {
  engine: {
    running: string;
    model: string | null;
    voice: string | null;
    language: string;
    configured: boolean;
    alternatives: Record<string, { usable: boolean; why_not: string | null }>;
  };
  prompt: { version: string };
  clinic: {
    organisation: string;
    catalogue_warm: boolean;
    providers: number;
    api_configured: boolean;
  };
  sidecars: Record<string, { configured: boolean; model: string | null; advisory_only?: boolean }>;
  limits: { call_minutes: number | null; submit_window_seconds: number | null };
  read_only: string[];
};

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-6 border-b border-[color:var(--hairline,#e6e2dc)] py-3 last:border-0">
      <span className="text-sm text-steel">{label}</span>
      <span className="text-right font-medium tabular-nums">{children}</span>
    </div>
  );
}

function Yes({ on, yes = "sí", no = "no" }: { on: boolean; yes?: string; no?: string }) {
  return <span className={on ? "text-emerald-700" : "text-amber-700"}>{on ? yes : no}</span>;
}

export function LiveAgentReport() {
  const [report, setReport] = useState<AgentReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetch("/api/live/agent", { cache: "no-store" })
      .then(async (response) => {
        const body = await response.json();
        if (!alive) return;
        if (!response.ok) {
          setError(body?.detail ?? `El agente respondió ${response.status}.`);
          return;
        }
        setReport(body as AgentReport);
      })
      .catch(() => alive && setError("No se pudo hablar con el agente."));
    return () => {
      alive = false;
    };
  }, []);

  if (error) {
    return (
      <section className="surface rounded-[18px] p-[var(--card-padding)] text-steel">
        <p className="font-medium text-amber-800">{error}</p>
        <p className="mt-2 text-sm">
          Este panel lee del agente por <code>AGENT_HTTP_BASE_URL</code> con{" "}
          <code>OPS_TOKEN</code>. Si falta alguno de los dos, esto es lo que se ve.
        </p>
      </section>
    );
  }

  if (!report) {
    return (
      <section className="surface rounded-[18px] p-[var(--card-padding)] text-steel">
        Leyendo del agente…
      </section>
    );
  }

  const cascade = report.engine.alternatives?.cascade;

  return (
    <div className="grid gap-4">
      <section className="surface rounded-[18px] p-[var(--card-padding)]">
        <h2 className="mb-1 text-xs uppercase tracking-[0.08em] text-steel">Voz</h2>
        <Row label="Motor">{report.engine.running}</Row>
        <Row label="Modelo">{report.engine.model ?? "—"}</Row>
        <Row label="Voz">{report.engine.voice ?? "—"}</Row>
        <Row label="Idioma">{report.engine.language}</Row>
        <Row label="Credencial">
          <Yes on={report.engine.configured} yes="configurada" no="ausente" />
        </Row>
        {cascade && !cascade.usable ? (
          <p className="mt-3 text-sm text-steel">
            <b>cascade</b> no es una alternativa hoy: {cascade.why_not}.
          </p>
        ) : null}
      </section>

      <section className="surface rounded-[18px] p-[var(--card-padding)]">
        <h2 className="mb-1 text-xs uppercase tracking-[0.08em] text-steel">Instrucciones</h2>
        <Row label="Versión del prompt">{report.prompt.version}</Row>
        <Row label="Duración máxima">
          {report.limits.call_minutes ? `${report.limits.call_minutes} min` : "—"}
        </Row>
        <Row label="Ventana de envío">
          {report.limits.submit_window_seconds ? `${report.limits.submit_window_seconds} s` : "—"}
        </Row>
      </section>

      <section className="surface rounded-[18px] p-[var(--card-padding)]">
        <h2 className="mb-1 text-xs uppercase tracking-[0.08em] text-steel">Clínica</h2>
        <Row label="Organización">{report.clinic.organisation}</Row>
        <Row label="Catálogo">
          <Yes on={report.clinic.catalogue_warm} yes="cargado" no="frío" />
        </Row>
        <Row label="Profesionales">{report.clinic.providers}</Row>
        <Row label="API de la clínica">
          <Yes on={report.clinic.api_configured} yes="configurada" no="ausente" />
        </Row>
      </section>

      {Object.entries(report.sidecars ?? {}).map(([name, side]) => (
        <section key={name} className="surface rounded-[18px] p-[var(--card-padding)]">
          <h2 className="mb-1 text-xs uppercase tracking-[0.08em] text-steel">{name}</h2>
          <Row label="Modelo">{side.model ?? "—"}</Row>
          <Row label="Estado">
            <Yes on={side.configured} yes="configurado" no="ausente" />
          </Row>
          {side.advisory_only ? (
            <p className="mt-3 text-sm text-steel">
              Solo aconseja: nunca decide por sí mismo lo que se reserva.
            </p>
          ) : null}
        </section>
      ))}

      <section className="surface rounded-[18px] p-[var(--card-padding)] text-sm text-steel">
        {report.read_only.map((line) => (
          <p key={line} className="mb-2 last:mb-0">
            {line}
          </p>
        ))}
      </section>
    </div>
  );
}
