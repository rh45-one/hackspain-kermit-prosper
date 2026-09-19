# Add Prosper Voice Scheduling Agent

## Why

The Prosper track scores an inbound clinic voice agent using Twilio Media
Streams and requiring submissions within 30 seconds. The tested baseline
includes the Twilio wire, clinic layer, deterministic core, guarded tools,
recorder and ops console. The approved next step adds selectable Gemini 3.8
Live audio with a TypeSafe Jev decision sidecar while retaining the existing
cascade as rollback.

## What Changes

- Run one isolated Twilio Media Streams pipeline per socket for 10–20 calls.
- Cache the EHR catalogue and query directory, availability and appointments
  with strict identification.
- Keep Europe/Madrid date resolution, rules and appointment selection fully
  deterministic.
- Select `gemini_live` (`gemini-3.8-live`) or default `cascade` with
  `VOICE_ENGINE`; bridge 8kHz µ-law to Gemini PCM using bounded buffers.
- Pin Jev `1.13.0`; expose only locally redacted finalized context, enforce a
  300ms timeout and abstain on low confidence or failure. Jev never controls
  turn-taking, accesses raw identifiers, or authorizes writes.
- Route Gemini function calls through the registry-validated `ToolBox`.
- Submit each scored action exactly once within 30 seconds, retrying
  idempotently and treating 409 as success.
- Serve `/call` with `/ws/demo` for same-origin microphone calls using the same
  wire format, audio playback and no Prosper submission.
- Record per-call model, audio, TTFT, tool, Jev and cost metrics.

## Non-goals

- No ClinicReflow engine, outbound calling, CRM or fine-tuning.
- No auth beyond the harness header, and no persisted browser identity.

## Capabilities

### prosper-voice-agent
- Answers the camelCase, string-metadata, 8kHz µ-law call contract.
- Runs the Gemini Live host or cascade per socket, chosen by `VOICE_ENGINE`.
- Identifies callers and books, reschedules, cancels, registers, refuses or
  escalates through deterministic tools.
- Handles 10+ concurrent sockets with zero shared conversation state.
- Provides a non-submitting browser simulator for local and jury use.

## Impact

- Adds Gemini/Jev under `backend/src/agent` and the simulator under
  `backend/serverwebsock`; the deterministic core remains unchanged.
