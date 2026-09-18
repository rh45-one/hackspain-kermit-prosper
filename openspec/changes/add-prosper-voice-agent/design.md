# Design: prosper-voice-agent

## Context

Hackathon build (Fri 18 → Sun 20 Sep 2026), checkpoints Saturday 11:00 and
22:00 Europe/Madrid. The agent must answer Prosper harness calls on a Twilio
Media Streams WebSocket, decide scheduling actions, and POST them within 30s
of socket close. Multi-agent build via Orca: this session coordinates; workers
own isolated directories.

## Goals / Non-Goals

- Goals: pass problems 1–18 on the leaderboard; survive 20 concurrent
  sockets; deployable = one `make run` (from `backend/`) + ngrok static domain EU.
- Non-Goals: outbound telephony, real writes to an EHR, user accounts.

## Decisions

### D1. pipecat pipeline, hand-tightened
Organisers recommend pipecat and it ships `TwilioFrameSerializer` +
`WebsocketServerTransport`. We pin `pipecat-ai[silero,deepgram,openai]` and
run one `PipelineTask` per socket (runner's per-connection handle) so
concurrency is structurally safe. Barge-in via Silero VAD + pipecat
interruption frames; `clear` is best-effort since the harness ignores it.

### D2. Brain = Helmcode glm5.3, tools decide
The LLM converses and calls tools; every scheduling decision is made by
deterministic code behind a tool. Tools accept only values previously
returned by clinic lookups (validated against a per-call registry), so the
model cannot invent ids, slots or types. Fallback chain: deepseek-v4-flash →
glm5.3-flash via env `AGENT_MODEL`.

### D3. Deterministic scheduling core (pure Python, fully unit-tested)
`clinic/` (API client + immutable catalogue cache warmed from `/clinic` at
startup) and `scheduling/` (Europe/Madrid date resolver with closure days and
site hours; rules engine mapping plan/specialty/provider/age/site to the
closed reason vocabulary; slot matcher). No LLM in this layer.

### D4. Submission recorder with 30s-window discipline
Per-call `ActionRecorder` collects validated intents; on `stop` (or socket
close) it flushes POSTs with bounded retries; 409 counts as accepted.
Flush starts the moment the call ends, well inside the window.

### D5. Language strategy
STT Deepgram nova-3 `multi` (es/en) primary; Catalan/Galician fallback path:
Helmcode `whisper` (transcription endpoint) if nova quality fails problem 11
practice. TTS ElevenLabs turbo v2.5 (multilingual incl. Catalan) primary,
Cartesia sonic fallback. Prompt instructs: reply in the caller's language.

### D6. Observability first-class from hour one
Every call writes JSONL (frames timeline, tool calls, actions, errors) to
`backend/data/calls/<call_id>.jsonl`. FastAPI `/ops` remains a JSON/HTML
fallback over that store. The staff-facing jury platform is the Next.js
FrontDesk in `frontend/` (D7).

### D7. FrontDesk is Next.js, mock-first
Clinic staff use a Next.js App Router + Tailwind + shadcn/ui app in
`frontend/`. Routes: `/calls` (live monitor), `/patients` (directory),
`/calendar` (week/day), `/settings` (tunnel, voice, knowledge sources).
Spanish UI, English code. Until `/ops/api/*` is wired, the UI runs on
typed mock data shaped like directory / appointments / call audit records.

The browser does **not** speak Twilio Media Streams. The header shows
whether the configured public `ws://` / `wss://` tunnel URL is set, plus
capacity `n/10` active cards (backend still accepts 10–20 sockets).

Calendar chips map closed action verbs to receptionist colours:
`BOOK`/`REGISTER`/`RESCHEDULE` → BOOKED (green), `CANCEL` → CANCELLED
(red), `NO_ACTION` → REFUSED (grey, reason shown), `ESCALATE` → DIVERTED
(orange). Patient "triaje" is a reception flag derived from the latest
agent action, not a clinical score. Handover is an ESCALATE seam in the UI.

## Risks / Trade-offs

- [pipecat version churn] → pin exact version, smoke-test with wscat before
  every Run All.
- [LLM drift on ids] → tool-layer validation makes wrong ids structurally
  impossible; model only narrates.
- [Single local host] → ngrok static domain, launchd keepalive, wscat health
  check in Makefile.

## Migration Plan

Empty repo → scaffold this change. No migration.

## Open Questions

- Exact Deepgram model for Catalan once problem 11 opens (practice will tell).
- When FrontDesk stops using mocks: poll `/ops/api/calls` vs a dedicated
  live WebSocket from the ops console (not the Twilio `/ws`).
