"use strict";

const OPEN_TIMEOUT_MS = 10000;
const MAX_SOCKET_BUFFER_BYTES = 256 * 1024;
const MAX_PLAYBACK_SECONDS = 3;
const PLAYBACK_LEAD_SECONDS = 0.035;

const button = document.querySelector("#call-button");
const label = document.querySelector("#call-label");
const status = document.querySelector("#call-status");

let phase = "idle";
let sessionVersion = 0;
let intentionalClose = false;
let socket = null;
let mediaStream = null;
let audioContext = null;
let microphoneSource = null;
let captureNode = null;
let silentGain = null;
let playbackCursor = 0;
let playbackSources = new Set();
let callId = "";
let streamSid = "";
let sequenceNumber = 1;
let mediaChunk = 0;
let startPromise = null;

function setPhase(nextPhase, message, tone = "neutral") {
  phase = nextPhase;
  const inCall = !["idle", "stopping"].includes(nextPhase);
  button.setAttribute("aria-pressed", String(inCall));
  button.disabled = nextPhase === "stopping";
  label.textContent = inCall ? "Colgar" : "Iniciar llamada";
  status.textContent = message;
  status.dataset.tone = tone;
}

function newId(prefix) {
  const randomPart = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${randomPart}`;
}

function websocketUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/demo`;
}

function permissionError(error) {
  if (error?.name === "NotAllowedError" || error?.name === "SecurityError") {
    return "Se denegó el micrófono. Actívalo en el navegador e inténtalo de nuevo.";
  }
  if (error?.name === "NotFoundError") {
    return "No se detectó ningún micrófono. Conecta uno e inténtalo de nuevo.";
  }
  if (error?.name === "NotReadableError") {
    return "Otra aplicación está usando el micrófono.";
  }
  return "No se pudo iniciar la llamada. Comprueba el micrófono y la conexión.";
}

function bytesToBase64(bytes) {
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return window.btoa(binary);
}

function base64ToBytes(value) {
  const binary = window.atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function decodeMuLaw(value) {
  const encoded = (~value) & 0xff;
  let magnitude = ((encoded & 0x0f) << 3) + 0x84;
  magnitude <<= (encoded & 0x70) >> 4;
  const sample = (encoded & 0x80) ? 0x84 - magnitude : magnitude - 0x84;
  return Math.max(-1, Math.min(1, sample / 32768));
}

function clearPlayback() {
  for (const source of playbackSources) {
    source.onended = null;
    try {
      source.stop();
    } catch {
      // A source that already ended needs no further cleanup.
    }
    source.disconnect();
  }
  playbackSources.clear();
  playbackCursor = audioContext ? audioContext.currentTime + PLAYBACK_LEAD_SECONDS : 0;
}

function playAgentAudio(payload) {
  if (!audioContext || audioContext.state === "closed" || !payload) {
    return;
  }

  let bytes;
  try {
    bytes = base64ToBytes(payload);
  } catch {
    return;
  }
  if (bytes.length === 0) {
    return;
  }

  if (playbackCursor - audioContext.currentTime > MAX_PLAYBACK_SECONDS) {
    clearPlayback();
  }

  const audioBuffer = audioContext.createBuffer(1, bytes.length, 8000);
  const channel = audioBuffer.getChannelData(0);
  for (let index = 0; index < bytes.length; index += 1) {
    channel[index] = decodeMuLaw(bytes[index]);
  }

  const source = audioContext.createBufferSource();
  source.buffer = audioBuffer;
  source.connect(audioContext.destination);
  const startsAt = Math.max(audioContext.currentTime + PLAYBACK_LEAD_SECONDS, playbackCursor);
  playbackCursor = startsAt + audioBuffer.duration;
  playbackSources.add(source);
  source.onended = () => {
    playbackSources.delete(source);
    source.disconnect();
  };
  source.start(startsAt);
}

function sendMicrophoneFrame(buffer) {
  if (phase !== "active" || !socket || socket.readyState !== WebSocket.OPEN) {
    return;
  }
  if (socket.bufferedAmount > MAX_SOCKET_BUFFER_BYTES) {
    void endCall("La conexión es demasiado lenta. Vuelve a intentarlo.", "error");
    return;
  }

  mediaChunk += 1;
  sequenceNumber += 1;
  socket.send(JSON.stringify({
    event: "media",
    sequenceNumber: String(sequenceNumber),
    streamSid,
    media: {
      track: "inbound",
      chunk: String(mediaChunk),
      timestamp: String((mediaChunk - 1) * 20),
      payload: bytesToBase64(new Uint8Array(buffer)),
    },
  }));
}

function handleSocketMessage(event) {
  if (typeof event.data !== "string") {
    return;
  }
  let message;
  try {
    message = JSON.parse(event.data);
  } catch {
    return;
  }
  if (message.event === "clear") {
    clearPlayback();
    return;
  }
  if (message.event === "media") {
    playAgentAudio(message.media?.payload);
  }
}

function waitForOpen(ws, version) {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      cleanupListeners();
      reject(new Error("WebSocket connection timed out"));
    }, OPEN_TIMEOUT_MS);

    function cleanupListeners() {
      window.clearTimeout(timeout);
      ws.removeEventListener("open", onOpen);
      ws.removeEventListener("error", onError);
      ws.removeEventListener("close", onClose);
    }
    function onOpen() {
      cleanupListeners();
      if (version === sessionVersion) {
        resolve();
      } else {
        reject(new Error("Call cancelled"));
      }
    }
    function onError() {
      cleanupListeners();
      reject(new Error("WebSocket connection failed"));
    }
    function onClose() {
      cleanupListeners();
      reject(new Error("WebSocket closed before connecting"));
    }

    ws.addEventListener("open", onOpen);
    ws.addEventListener("error", onError);
    ws.addEventListener("close", onClose);
  });
}

function sendStart() {
  socket.send(JSON.stringify({event: "connected", protocol: "Call", version: "1.0.0"}));
  socket.send(JSON.stringify({
    event: "start",
    sequenceNumber: "1",
    streamSid,
    start: {
      accountSid: "AC-browser-demo",
      streamSid,
      callSid: callId,
      tracks: ["inbound"],
      mediaFormat: {encoding: "audio/x-mulaw", sampleRate: 8000, channels: 1},
      customParameters: {call_id: callId, source: "browser_demo"},
    },
  }));
}

function sendStop() {
  if (!socket || socket.readyState !== WebSocket.OPEN || !callId) {
    return;
  }
  sequenceNumber += 1;
  socket.send(JSON.stringify({
    event: "stop",
    sequenceNumber: String(sequenceNumber),
    streamSid,
    stop: {accountSid: "AC-browser-demo", callSid: callId},
  }));
}

async function releaseResources() {
  if (captureNode) {
    captureNode.port.onmessage = null;
    captureNode.disconnect();
    captureNode = null;
  }
  microphoneSource?.disconnect();
  microphoneSource = null;
  silentGain?.disconnect();
  silentGain = null;

  if (mediaStream) {
    for (const track of mediaStream.getTracks()) {
      track.stop();
    }
    mediaStream = null;
  }

  clearPlayback();
  const context = audioContext;
  audioContext = null;
  if (context && context.state !== "closed") {
    try {
      await context.close();
    } catch {
      // Closing is best effort during browser/page teardown.
    }
  }

  const closingSocket = socket;
  socket = null;
  if (closingSocket && closingSocket.readyState < WebSocket.CLOSING) {
    closingSocket.close(1000, "Call ended");
  }

  callId = "";
  streamSid = "";
  sequenceNumber = 1;
  mediaChunk = 0;
}

async function handleRemoteClose(version) {
  if (version !== sessionVersion || intentionalClose || phase === "idle") {
    return;
  }
  sessionVersion += 1;
  intentionalClose = true;
  const pendingStart = startPromise;
  setPhase("stopping", "El agente ha cerrado la llamada");
  await releaseResources();
  if (pendingStart) {
    await pendingStart;
  }
  setPhase("idle", "El agente ha cerrado la llamada. Línea disponible.");
}

async function startCall() {
  if (phase !== "idle") {
    return;
  }
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
    setPhase("idle", "Las llamadas requieren HTTPS o localhost en un navegador actualizado.", "error");
    return;
  }

  const version = ++sessionVersion;
  intentionalClose = false;
  setPhase("requesting", "Autoriza el micrófono para continuar");

  try {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    audioContext = new AudioContextClass({latencyHint: "interactive"});
    await audioContext.resume();
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    });
    if (version !== sessionVersion) {
      await releaseResources();
      return;
    }

    await audioContext.audioWorklet.addModule("./mic-worklet.js");
    microphoneSource = audioContext.createMediaStreamSource(mediaStream);
    captureNode = new AudioWorkletNode(audioContext, "mulaw-capture", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      outputChannelCount: [1],
      processorOptions: {targetSampleRate: 8000, frameSamples: 160},
    });
    silentGain = audioContext.createGain();
    silentGain.gain.value = 0;
    captureNode.port.onmessage = (event) => sendMicrophoneFrame(event.data);
    microphoneSource.connect(captureNode);
    captureNode.connect(silentGain);
    silentGain.connect(audioContext.destination);

    setPhase("connecting", "Conectando con recepción");
    socket = new WebSocket(websocketUrl());
    socket.addEventListener("message", handleSocketMessage);
    socket.addEventListener("close", () => void handleRemoteClose(version));
    await waitForOpen(socket, version);
    if (version !== sessionVersion) {
      await releaseResources();
      return;
    }

    callId = newId("browser");
    streamSid = newId("SM-browser");
    sendStart();
    playbackCursor = audioContext.currentTime + PLAYBACK_LEAD_SECONDS;
    setPhase("active", "En línea. Ya puedes hablar.", "active");
  } catch (error) {
    if (version !== sessionVersion) {
      return;
    }
    sessionVersion += 1;
    intentionalClose = true;
    await releaseResources();
    setPhase("idle", permissionError(error), "error");
  }
}

async function endCall(message = "Llamada finalizada. Línea disponible.", tone = "neutral") {
  if (phase === "idle" || phase === "stopping") {
    return;
  }
  sessionVersion += 1;
  intentionalClose = true;
  const pendingStart = startPromise;
  setPhase("stopping", "Finalizando llamada");
  sendStop();
  await releaseResources();
  if (pendingStart) {
    await pendingStart;
  }
  setPhase("idle", message, tone);
}

button.addEventListener("click", () => {
  if (phase === "idle") {
    startPromise = startCall().finally(() => {
      startPromise = null;
    });
  } else {
    void endCall();
  }
});

window.addEventListener("pagehide", () => {
  if (phase !== "idle") {
    sessionVersion += 1;
    intentionalClose = true;
    sendStop();
    void releaseResources();
  }
});
