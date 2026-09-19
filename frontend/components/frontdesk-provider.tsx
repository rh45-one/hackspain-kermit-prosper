"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { isValidTunnelUrl } from "@/lib/dni";
import {
  cloneLiveCalls,
  DEFAULT_SETTINGS,
  MOCK_APPOINTMENTS,
  MOCK_PATIENTS,
} from "@/lib/mock-data";
import type {
  AgentSettings,
  Appointment,
  KnowledgeSource,
  LiveCall,
  Patient,
} from "@/lib/types";
import { CALL_CAPACITY } from "@/lib/types";

const SETTINGS_KEY = "frontdesk.settings";

type FrontdeskContextValue = {
  demo: boolean;
  connectionError: string | null;
  clinicError: string | null;
  loading: boolean;
  settings: AgentSettings;
  saveSettings: (next: AgentSettings) => { ok: true } | { ok: false; error: string };
  addKnowledgeSource: (source: Omit<KnowledgeSource, "id">) => void;
  calls: LiveCall[];
  activeCount: number;
  capacityLabel: string;
  tunnelConfigured: boolean;
  takeControl: (callId: string) => void;
  patients: Patient[];
  appointments: Appointment[];
};

const FrontdeskContext = createContext<FrontdeskContextValue | null>(null);

function loadSettings(): AgentSettings {
  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY);
    if (!raw) {
      return DEFAULT_SETTINGS;
    }
    return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function FrontdeskProvider({
  children, demo,
}: { children: React.ReactNode; demo: boolean }) {
  const [settings, setSettings] = useState<AgentSettings>(DEFAULT_SETTINGS);
  const [hydrated, setHydrated] = useState(false);
  const [calls, setCalls] = useState<LiveCall[]>(() => demo ? cloneLiveCalls() : []);
  const [patients, setPatients] = useState<Patient[]>(() => demo ? MOCK_PATIENTS : []);
  const [appointments, setAppointments] = useState<Appointment[]>(() => demo ? MOCK_APPOINTMENTS : []);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [clinicError, setClinicError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!demo);

  useEffect(() => {
    if (!demo) return;
    queueMicrotask(() => {
      setSettings(loadSettings());
      setHydrated(true);
    });
  }, [demo]);

  useEffect(() => {
    if (!demo) return;
    if (!hydrated) {
      return;
    }
    window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  }, [demo, hydrated, settings]);

  useEffect(() => {
    if (demo) return;
    const controller = new AbortController();
    const timers: Partial<Record<"calls" | "clinic", number>> = {};
    async function refresh(resource: "calls" | "clinic") {
      try {
        const response = await fetch(`/api/frontdesk/${resource}`, {
          cache: "no-store", signal: controller.signal,
        });
        if (!response.ok) {
          const error: { detail?: string } = await response.json();
          throw new Error(error.detail ?? `HTTP ${response.status}`);
        }
        if (resource === "calls") {
          const data: LiveCall[] = await response.json();
          if (controller.signal.aborted) return;
          setCalls(data);
          setConnectionError(null);
        } else {
          const data: { patients: Patient[]; appointments: Appointment[] } = await response.json();
          if (controller.signal.aborted) return;
          setPatients(data.patients);
          setAppointments(data.appointments);
          setClinicError(null);
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        const message = error instanceof Error ? error.message : "Error de conexión";
        if (resource === "calls") {
          setConnectionError(message);
          setCalls([]);
        } else {
          setClinicError(message);
          setPatients([]);
          setAppointments([]);
        }
      } finally {
        if (!controller.signal.aborted) {
          if (resource === "calls") setLoading(false);
          timers[resource] = window.setTimeout(
            () => void refresh(resource), resource === "calls" ? 3000 : 60000,
          );
        }
      }
    }
    void refresh("calls");
    void refresh("clinic");
    return () => {
      controller.abort();
      Object.values(timers).forEach(window.clearTimeout);
    };
  }, [demo]);

  useEffect(() => {
    if (!demo) return;
    const timer = window.setInterval(() => {
      setCalls((current) =>
        current.map((call) => {
          if (call.status !== "active") {
            return call;
          }
          const nextIndex = call.transcript.length;
          const nextLine = call.script[nextIndex];
          if (!nextLine) {
            return call;
          }
          return {
            ...call,
            transcript: [...call.transcript, nextLine],
            turn: nextLine.turn ?? call.turn,
            entities: { ...call.entities, ...nextLine.entities },
          };
        }),
      );
    }, 1600);
    return () => window.clearInterval(timer);
  }, [demo]);

  const saveSettings = useCallback((next: AgentSettings) => {
    if (!demo) return { ok: false as const, error: "Configura el agente mediante backend/.env" };
    const url = next.tunnelUrl.trim();
    if (url && !isValidTunnelUrl(url)) {
      return {
        ok: false as const,
        error: "El túnel debe empezar por wss:// o ws://",
      };
    }
    setSettings({ ...next, tunnelUrl: url });
    return { ok: true as const };
  }, [demo]);

  const addKnowledgeSource = useCallback((source: Omit<KnowledgeSource, "id">) => {
    if (!demo) return;
    setSettings((current) => ({
      ...current,
      knowledgeSources: [
        ...current.knowledgeSources,
        { ...source, id: `ks-${crypto.randomUUID()}` },
      ],
    }));
  }, [demo]);

  const takeControl = useCallback((callId: string) => {
    if (!demo) return;
    setCalls((current) =>
      current.map((call) =>
        call.callId === callId
          ? {
              ...call,
              status: "ended",
              turn: "listening",
              outcome: "DIVERTED",
              action: "ESCALATE",
              reason: "medical_emergency",
              transcript: [
                ...call.transcript,
                {
                  role: "agent",
                  text: "Le paso con recepción. Un momento.",
                  turn: "speaking",
                },
              ],
            }
          : call,
      ),
    );
  }, [demo]);

  const activeCount = calls.filter((call) => call.status === "active").length;

  const value = useMemo<FrontdeskContextValue>(
    () => ({
      demo,
      connectionError,
      clinicError,
      loading,
      settings,
      saveSettings,
      addKnowledgeSource,
      calls,
      activeCount,
      capacityLabel: demo ? `${activeCount}/${CALL_CAPACITY} llamadas activas` :
        `${activeCount} llamadas abiertas en el registro`,
      tunnelConfigured: isValidTunnelUrl(settings.tunnelUrl),
      takeControl,
      patients,
      appointments,
    }),
    [activeCount, addKnowledgeSource, calls, saveSettings, settings, takeControl,
      demo, connectionError, clinicError, loading, patients, appointments],
  );

  return (
    <FrontdeskContext.Provider value={value}>{children}</FrontdeskContext.Provider>
  );
}

export function useFrontdesk() {
  const value = useContext(FrontdeskContext);
  if (!value) {
    throw new Error("useFrontdesk must be used inside FrontdeskProvider");
  }
  return value;
}
