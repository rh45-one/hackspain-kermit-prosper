# Add Prosper Voice Scheduling Agent

## Why

The Prosper track scores a voice agent that answers inbound clinic calls over
a Twilio-Media-Streams WebSocket and submits exact booking actions within 30
seconds of each call ending. Nothing exists in this repo yet. Checkpoints
start Saturday 11:00, so the first deliverable must answer calls and pass
problem 1 (simple booking) tonight.

## What Changes

- A WebSocket server speaking the Twilio Media Streams wire format, one fresh
  pipecat pipeline per connection (10–20 concurrent).
- A clinic layer that caches the immutable EHR catalogue at startup and
  queries directory / availability / appointments with strict identification.
- A deterministic scheduling brain: date resolver (Europe/Madrid, closure
  days, site hours, no same-day), rules engine (age, referral, plans, sites),
  and an appointment-type selector driven by the availability response.
- An LLM conversation layer (Helmcode glm5.3) with guarded tools; the model
  converses, the tools decide, nothing mutating is invented by the model.
- A submission recorder that POSTs every accepted action to
  /api/v1/submit/* inside the 30-second window, with retries and 409 tolerance.
- A per-call structured audit log (call_id, transcript, tool calls, actions)
  as the basis for the jury-facing live console later.
- Deployment runbook: ngrok static EU domain, backend `make run`, env template.

## Non-goals

- No ClinicReflow reflow engine in this change (separate change; optimiser is
  Germán's workstream; only the tool seam is stubbed here).
- No outbound calling, no CRM, no auth beyond the harness header.
- No fine-tuning; prompts stay versioned text.

## Capabilities

### prosper-voice-agent
- Answers calls per the call contract (connected/start/media/stop, camelCase,
  string-typed metadata fields, µ-law 8kHz).
- Identifies callers (phone hint, then name + second exact identifier).
- Books, reschedules, cancels, registers, refuses with the closed reason
  vocabulary, escalates red flags — and always submits an action.
- Handles 10+ concurrent sockets with zero shared conversation state.

## Impact

- New backend/src/agent package, backend/tests, backend/ops scripts, backend/.env.example, backend/Makefile.
- No existing code touched (repo is empty).
