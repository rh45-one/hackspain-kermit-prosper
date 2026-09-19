"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const OPEN_TIMEOUT_MS = 10000;
const MAX_SOCKET_BUFFER_BYTES = 256 * 1024;
const MAX_PLAYBACK_SECONDS = 3;
const PLAYBACK_LEAD_SECONDS = 0.035;
const HEALTH_POLL_MS = 4000;

export type CallPhase = "idle" | "requesting" | "connecting" | "active" | "stopping";
export type CallTone = "neutral" | "error" | "active";

type AudioContextCtor = typeof AudioContext;

function audioContextClass(): AudioContextCtor | undefined {
  if (typeof window === "undefined") {
    return undefined;
  }
  return window.AudioContext || (window as Window & { webkitAudioContext?: AudioContextCtor }).webkitAudioContext;
}

function newId(prefix: string): string {
  const randomPart = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${randomPart}`;
}

function permissionError(error: unknown): string {
  const name = error instanceof Error ? error.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "Microphone access was denied. Enable it in the browser and try again.";
  }
  if (name === "NotFoundError") {
    return "No microphone found. Plug one in and try again.";
  }
  if (name === "NotReadableError") {
    return "Another app is using the microphone.";
  }
  return "Could not start the call. Check the microphone and the connection.";
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return window.btoa(binary);
}

function base64ToBytes(value: string): Uint8Array {
  const binary = window.atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function decodeMuLaw(value: number): number {
  const encoded = (~value) & 0xff;
  let magnitude = ((encoded & 0x0f) << 3) + 0x84;
  magnitude <<= (encoded & 0x70) >> 4;
  const sample = (encoded & 0x80) ? 0x84 - magnitude : magnitude - 0x84;
  return Math.max(-1, Math.min(1, sample / 32768));
}

function waitForOpen(ws: WebSocket, isCurrent: () => boolean): Promise<void> {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      cleanup();
      reject(new Error("WebSocket connection timed out"));
    }, OPEN_TIMEOUT_MS);

    function cleanup() {
      window.clearTimeout(timeout);
      ws.removeEventListener("open", onOpen);
      ws.removeEventListener("error", onError);
      ws.removeEventListener("close", onClose);
    }
    function onOpen() {
      cleanup();
      if (isCurrent()) {
        resolve();
      } else {
        reject(new Error("Call cancelled"));
      }
    }
    function onError() {
      cleanup();
      reject(new Error("WebSocket connection failed"));
    }
    function onClose() {
      cleanup();
      reject(new Error("WebSocket closed before connecting"));
    }

    ws.addEventListener("open", onOpen);
    ws.addEventListener("error", onError);
    ws.addEventListener("close", onClose);
  });
}

export function useBrowserCall() {
  const [phase, setPhaseState] = useState<CallPhase>("idle");
  const [message, setMessage] = useState("Lista para llamar");
  const [tone, setTone] = useState<CallTone>("neutral");
  const [online, setOnline] = useState(false);

  const phaseRef = useRef<CallPhase>("idle");
  const sessionVersion = useRef(0);
  const intentionalClose = useRef(false);
  const socketRef = useRef<WebSocket | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const microphoneSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const captureNodeRef = useRef<AudioWorkletNode | null>(null);
  const silentGainRef = useRef<GainNode | null>(null);
  const playbackCursorRef = useRef(0);
  const playbackSourcesRef = useRef(new Set<AudioBufferSourceNode>());
  const callIdRef = useRef("");
  const streamSidRef = useRef("");
  const sequenceNumberRef = useRef(1);
  const mediaChunkRef = useRef(0);
  const startPromiseRef = useRef<Promise<void> | null>(null);

  const setPhase = useCallback((next: CallPhase, nextMessage: string, nextTone: CallTone = "neutral") => {
    phaseRef.current = next;
    setPhaseState(next);
    setMessage(nextMessage);
    setTone(nextTone);
    if (next !== "idle" && next !== "stopping") {
      setOnline(true);
    }
  }, []);

  const clearPlayback = useCallback(() => {
    for (const source of playbackSourcesRef.current) {
      source.onended = null;
      try {
        source.stop();
      } catch {
        // Already ended.
      }
      source.disconnect();
    }
    playbackSourcesRef.current.clear();
    const context = audioContextRef.current;
    playbackCursorRef.current = context ? context.currentTime + PLAYBACK_LEAD_SECONDS : 0;
  }, []);

  const playAgentAudio = useCallback((payload: string | undefined) => {
    const context = audioContextRef.current;
    if (!context || context.state === "closed" || !payload) {
      return;
    }
    let bytes: Uint8Array;
    try {
      bytes = base64ToBytes(payload);
    } catch {
      return;
    }
    if (bytes.length === 0) {
      return;
    }
    if (playbackCursorRef.current - context.currentTime > MAX_PLAYBACK_SECONDS) {
      clearPlayback();
    }
    const audioBuffer = context.createBuffer(1, bytes.length, 8000);
    const channel = audioBuffer.getChannelData(0);
    for (let index = 0; index < bytes.length; index += 1) {
      channel[index] = decodeMuLaw(bytes[index]);
    }
    const source = context.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(context.destination);
    const startsAt = Math.max(context.currentTime + PLAYBACK_LEAD_SECONDS, playbackCursorRef.current);
    playbackCursorRef.current = startsAt + audioBuffer.duration;
    playbackSourcesRef.current.add(source);
    source.onended = () => {
      playbackSourcesRef.current.delete(source);
      source.disconnect();
    };
    source.start(startsAt);
  }, [clearPlayback]);

  const sendStop = useCallback(() => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN || !callIdRef.current) {
      return;
    }
    sequenceNumberRef.current += 1;
    socket.send(JSON.stringify({
      event: "stop",
      sequenceNumber: String(sequenceNumberRef.current),
      streamSid: streamSidRef.current,
      stop: { accountSid: "AC-browser-demo", callSid: callIdRef.current },
    }));
  }, []);

  const releaseResources = useCallback(async () => {
    const captureNode = captureNodeRef.current;
    if (captureNode) {
      captureNode.port.onmessage = null;
      captureNode.disconnect();
      captureNodeRef.current = null;
    }
    microphoneSourceRef.current?.disconnect();
    microphoneSourceRef.current = null;
    silentGainRef.current?.disconnect();
    silentGainRef.current = null;

    if (mediaStreamRef.current) {
      for (const track of mediaStreamRef.current.getTracks()) {
        track.stop();
      }
      mediaStreamRef.current = null;
    }

    clearPlayback();
    const context = audioContextRef.current;
    audioContextRef.current = null;
    if (context && context.state !== "closed") {
      try {
        await context.close();
      } catch {
        // Best effort.
      }
    }

    const closingSocket = socketRef.current;
    socketRef.current = null;
    if (closingSocket && closingSocket.readyState < WebSocket.CLOSING) {
      closingSocket.close(1000, "Call ended");
    }

    callIdRef.current = "";
    streamSidRef.current = "";
    sequenceNumberRef.current = 1;
    mediaChunkRef.current = 0;
  }, [clearPlayback]);

  const endCall = useCallback(async (
    nextMessage = "Call ended. Line is free.",
    nextTone: CallTone = "neutral",
  ) => {
    if (phaseRef.current === "idle" || phaseRef.current === "stopping") {
      return;
    }
    sessionVersion.current += 1;
    intentionalClose.current = true;
    const pendingStart = startPromiseRef.current;
    setPhase("stopping", "Ending call");
    sendStop();
    await releaseResources();
    if (pendingStart) {
      await pendingStart;
    }
    setPhase("idle", nextMessage, nextTone);
  }, [releaseResources, sendStop, setPhase]);

  const sendMicrophoneFrame = useCallback((buffer: ArrayBuffer) => {
    const socket = socketRef.current;
    if (phaseRef.current !== "active" || !socket || socket.readyState !== WebSocket.OPEN) {
      return;
    }
    if (socket.bufferedAmount > MAX_SOCKET_BUFFER_BYTES) {
      void endCall("The connection is too slow. Try again.", "error");
      return;
    }
    mediaChunkRef.current += 1;
    sequenceNumberRef.current += 1;
    socket.send(JSON.stringify({
      event: "media",
      sequenceNumber: String(sequenceNumberRef.current),
      streamSid: streamSidRef.current,
      media: {
        track: "inbound",
        chunk: String(mediaChunkRef.current),
        timestamp: String((mediaChunkRef.current - 1) * 20),
        payload: bytesToBase64(new Uint8Array(buffer)),
      },
    }));
  }, [endCall]);

  const probeLink = useCallback(async () => {
    if (typeof navigator !== "undefined" && !navigator.onLine) {
      setOnline(false);
      return;
    }
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      setOnline(true);
      return;
    }
    try {
      const response = await fetch("/api/voice/health", { cache: "no-store" });
      setOnline(response.ok);
    } catch {
      setOnline(false);
    }
  }, []);

  const startCall = useCallback(async () => {
    if (phaseRef.current !== "idle") {
      return;
    }
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
      setPhase("idle", "Calls need HTTPS or localhost in a current browser.", "error");
      return;
    }

    const version = ++sessionVersion.current;
    intentionalClose.current = false;
    setPhase("requesting", "Allow the microphone to continue");

    try {
      const Ctor = audioContextClass();
      if (!Ctor) {
        throw new Error("AudioContext unavailable");
      }
      const audioContext = new Ctor({ latencyHint: "interactive" });
      audioContextRef.current = audioContext;
      await audioContext.resume();
      const mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });
      mediaStreamRef.current = mediaStream;
      if (version !== sessionVersion.current) {
        await releaseResources();
        return;
      }

      await audioContext.audioWorklet.addModule("/mic-worklet.js");
      const microphoneSource = audioContext.createMediaStreamSource(mediaStream);
      microphoneSourceRef.current = microphoneSource;
      const captureNode = new AudioWorkletNode(audioContext, "mulaw-capture", {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        outputChannelCount: [1],
        processorOptions: { targetSampleRate: 8000, frameSamples: 160 },
      });
      captureNodeRef.current = captureNode;
      const silentGain = audioContext.createGain();
      silentGain.gain.value = 0;
      silentGainRef.current = silentGain;
      captureNode.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        sendMicrophoneFrame(event.data);
      };
      microphoneSource.connect(captureNode);
      captureNode.connect(silentGain);
      silentGain.connect(audioContext.destination);

      setPhase("connecting", "Connecting to reception");
      const config = await fetch("/api/voice/config", { cache: "no-store" }).then((response) => {
        if (!response.ok) {
          throw new Error("Voice config unavailable");
        }
        return response.json() as Promise<{ wsUrl: string }>;
      });
      if (version !== sessionVersion.current) {
        await releaseResources();
        return;
      }

      const socket = new WebSocket(config.wsUrl);
      socketRef.current = socket;
      socket.addEventListener("message", (event) => {
        if (typeof event.data !== "string") {
          return;
        }
        let parsed: { event?: string; media?: { payload?: string } };
        try {
          parsed = JSON.parse(event.data) as { event?: string; media?: { payload?: string } };
        } catch {
          return;
        }
        if (parsed.event === "clear") {
          clearPlayback();
          return;
        }
        if (parsed.event === "media") {
          playAgentAudio(parsed.media?.payload);
        }
      });
      socket.addEventListener("close", () => {
        if (version !== sessionVersion.current || intentionalClose.current || phaseRef.current === "idle") {
          return;
        }
        sessionVersion.current += 1;
        intentionalClose.current = true;
        const pendingStart = startPromiseRef.current;
        setPhase("stopping", "The agent hung up");
        void releaseResources().then(async () => {
          if (pendingStart) {
            await pendingStart;
          }
          setPhase("idle", "The agent hung up. Line is free.");
        });
      });
      await waitForOpen(socket, () => version === sessionVersion.current);
      if (version !== sessionVersion.current) {
        await releaseResources();
        return;
      }

      callIdRef.current = newId("browser");
      streamSidRef.current = newId("SM-browser");
      socket.send(JSON.stringify({ event: "connected", protocol: "Call", version: "1.0.0" }));
      socket.send(JSON.stringify({
        event: "start",
        sequenceNumber: "1",
        streamSid: streamSidRef.current,
        start: {
          accountSid: "AC-browser-demo",
          streamSid: streamSidRef.current,
          callSid: callIdRef.current,
          tracks: ["inbound"],
          mediaFormat: { encoding: "audio/x-mulaw", sampleRate: 8000, channels: 1 },
          customParameters: { call_id: callIdRef.current, source: "browser_demo" },
        },
      }));
      playbackCursorRef.current = audioContext.currentTime + PLAYBACK_LEAD_SECONDS;
      setPhase("active", "On the line. You can talk now.", "active");
    } catch (error) {
      if (version !== sessionVersion.current) {
        return;
      }
      sessionVersion.current += 1;
      intentionalClose.current = true;
      await releaseResources();
      setPhase("idle", permissionError(error), "error");
    }
  }, [clearPlayback, playAgentAudio, releaseResources, sendMicrophoneFrame, setPhase]);

  const toggleCall = useCallback(() => {
    if (phaseRef.current === "idle") {
      startPromiseRef.current = startCall().finally(() => {
        startPromiseRef.current = null;
      });
    } else {
      void endCall();
    }
  }, [endCall, startCall]);

  useEffect(() => {
    void probeLink();
    const timer = window.setInterval(() => void probeLink(), HEALTH_POLL_MS);
    const onOnline = () => void probeLink();
    const onOffline = () => setOnline(false);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, [probeLink]);

  useEffect(() => {
    return () => {
      if (phaseRef.current !== "idle") {
        sessionVersion.current += 1;
        intentionalClose.current = true;
        sendStop();
        void releaseResources();
      }
    };
  }, [releaseResources, sendStop]);

  const inCall = phase !== "idle" && phase !== "stopping";

  return {
    phase,
    message,
    tone,
    online,
    inCall,
    busy: phase === "stopping",
    toggleCall,
  };
}
