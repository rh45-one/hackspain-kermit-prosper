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

export function FrontdeskProvider({ children }: { children: React.ReactNode }) {
  const [settings, setSettings] = useState<AgentSettings>(DEFAULT_SETTINGS);
  const [hydrated, setHydrated] = useState(false);
  const [calls, setCalls] = useState<LiveCall[]>(() => cloneLiveCalls());

  useEffect(() => {
    queueMicrotask(() => {
      setSettings(loadSettings());
      setHydrated(true);
    });
  }, []);

  useEffect(() => {
    if (!hydrated) {
      return;
    }
    window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  }, [hydrated, settings]);

  useEffect(() => {
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
  }, []);

  const saveSettings = useCallback((next: AgentSettings) => {
    const url = next.tunnelUrl.trim();
    if (url && !isValidTunnelUrl(url)) {
      return {
        ok: false as const,
        error: "El túnel debe empezar por wss:// o ws://",
      };
    }
    setSettings({ ...next, tunnelUrl: url });
    return { ok: true as const };
  }, []);

  const addKnowledgeSource = useCallback((source: Omit<KnowledgeSource, "id">) => {
    setSettings((current) => ({
      ...current,
      knowledgeSources: [
        ...current.knowledgeSources,
        { ...source, id: `ks-${crypto.randomUUID()}` },
      ],
    }));
  }, []);

  const takeControl = useCallback((callId: string) => {
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
  }, []);

  const activeCount = calls.filter((call) => call.status === "active").length;

  const value = useMemo<FrontdeskContextValue>(
    () => ({
      settings,
      saveSettings,
      addKnowledgeSource,
      calls,
      activeCount,
      capacityLabel: `${activeCount}/${CALL_CAPACITY} llamadas activas`,
      tunnelConfigured: isValidTunnelUrl(settings.tunnelUrl),
      takeControl,
      patients: MOCK_PATIENTS,
      appointments: MOCK_APPOINTMENTS,
    }),
    [activeCount, addKnowledgeSource, calls, saveSettings, settings, takeControl],
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
