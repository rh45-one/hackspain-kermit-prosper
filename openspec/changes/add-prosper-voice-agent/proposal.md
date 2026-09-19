# Add Prosper Voice Scheduling Agent

## Why

The Prosper track scores a voice agent that answers inbound clinic calls over
a Twilio Media Streams WebSocket and submits booking actions within 30
seconds. The baseline — Twilio wire, clinic layer, deterministic core, guarded
tools, recorder, ops console — is built and covered by the offline suite. This
change reconciles the approved next step: a selectable Google Gemini 3.8 Live
audio-to-audio host with a TypeSafe Jev structured-decision sidecar, keeping
the Deepgram → OpenAI-compatible LLM → ElevenLabs cascade as rollback.

## What Changes

- A WebSocket server over the Twilio Media Streams wire format, one fresh
  pipeline per connection (10–20 concurrent).
- A clinic layer caching the EHR catalogue and querying directory,
  availability and appointments with strict identification.
- A deterministic scheduling brain (Europe/Madrid date resolver, rules engine,
  appointment-type selector), unchanged in authority.
- A selectable audio host. `VOICE_ENGINE=gemini_live` routes a socket through
  Gemini 3.8 Live (`gemini-3.8-live`), converting Twilio 8kHz µ-law to Gemini
  16kHz PCM input and Gemini 24kHz PCM output back to µ-law with bounded
  buffering. `VOICE_ENGINE=cascade` (default) keeps the Deepgram →
  OpenAI-compatible LLM → ElevenLabs cascade as rollback.
- A Jev sidecar, pinned `jev-1.13.0`, receiving only a redacted, finalized
  transcript and state; 300ms hard timeout; abstains on low confidence or
  failure. It never sees phone numbers, national ids, dates of birth or raw
  records, never handles VAD or barge-in, and never authorizes a write.
- Deterministic rules and tools stay the source of truth: Gemini function calls
  route through the existing registry-validated `ToolBox`.
- A submission recorder that POSTs each action to /api/v1/submit/* inside 30
  seconds, exactly once, retrying idempotently and treating 409 as success.
- Per-call structured audit and metrics (model, audio conversion, TTFT, tool
  calls, Jev latency/confidence/abstention, cost).
- A Next.js FrontDesk in `frontend/` for clinic staff: live call monitor,
  patient directory, Europe/Madrid calendar, and agent settings. Mock data
  first; later the same shapes as `/ops/api/*` and `/api/v1/directory`.
- Deployment runbook: ngrok static EU domain, backend `make run`, env template.

## Non-goals

- No ClinicReflow reflow engine here (separate change; only the tool seam).
- No outbound calling, CRM, or auth beyond the harness header.
- No fine-tuning; prompts remain versioned text.

## Capabilities

### prosper-voice-agent
- Answers calls per the call contract (camelCase, string-typed metadata, 8kHz µ-law).
- Runs the Gemini Live host or cascade per socket, chosen by `VOICE_ENGINE`.
- Identifies callers, books/reschedules/cancels/registers, refuses with the closed vocabulary, escalates red flags — always submitting an action.
- Handles 10+ concurrent sockets with zero shared conversation state.

### frontdesk-ops-console
- Staff dashboard in `frontend/`: up to 10 live call cards, patient search
  (name + DNI/NIE), appointment calendar in Europe/Madrid, read-only
  practice catalog at `/problems`, tunnel/voice settings. FastAPI `/ops`
  stays the JSON/HTML fallback.

## Impact

- Adds the Gemini/Jev path under backend/src/agent and backend/tests.
- New `frontend/` Next.js App Router app (operator UI). Root README points at it.
