# Design: prosper-voice-agent

## Context

Hackathon build (Fri 18 → Sun 20 Sep 2026), checkpoints Saturday 11:00 and
22:00 Europe/Madrid. The agent must answer Prosper harness calls on a Twilio
Media Streams WebSocket, decide scheduling actions, and POST them within 30s
of socket close. The baseline (Twilio wire, clinic layer, deterministic
scheduling core, guarded `ToolBox`, submission recorder, ops console) is built
and covered by the backend test suite. This change records the **approved next
architecture step**: a selectable Google Gemini 3.8 Live audio-to-audio host
with a TypeSafe Jev structured-decision sidecar, keeping the current Deepgram →
OpenAI-compatible LLM → ElevenLabs cascade as the rollback path. Multi-agent
build via Orca: this session coordinates; workers own isolated directories.

## Goals / Non-Goals

- Goals: pass problems 1–18 on the leaderboard; survive 20 concurrent sockets
  (10 is the scored design point); offer a selectable audio host; keep the
  deterministic core as the only authority for scheduling actions; deployable =
  one `make run` (from `backend/`) + ngrok static domain EU.
- Non-Goals: outbound telephony, real writes to an EHR, user accounts;
  replacing or weakening the deterministic scheduling core; changing the
  Prosper call contract.

## Decisions

### D1. pipecat pipeline, hand-tightened
Organisers recommend pipecat and it ships `TwilioFrameSerializer` +
`WebsocketServerTransport`. We pin `pipecat-ai` and run one worker per socket
(one `CallContext`, one `ToolBox`, one pipeline, one submission) so concurrency
is structurally safe. Barge-in via Silero VAD + pipecat interruption frames on
the cascade path; `clear` is best-effort since the harness ignores it.

### D2. Voice engine selection: `gemini_live` primary, `cascade` rollback
A `VOICE_ENGINE` feature flag selects exactly one audio host per socket:

- `gemini_live` — Gemini 3.8 Live (`gemini-3.8-live`) audio-to-audio host plus
  the Jev sidecar (D3, D5).
- `cascade` — the current Deepgram STT → OpenAI-compatible LLM → ElevenLabs TTS
  cascade with Silero VAD (D10). Default until the live evaluation gate (D14)
  passes.

Selection is per process and resolved once at socket start; the chosen engine
is recorded in the per-call audit. There is **no hidden fallback**: a rollback
from `gemini_live` to `cascade` is an explicit, configured, logged event, and
the runtime never silently swaps the model or provider mid-turn.

### D3. Gemini 3.8 Live as audio-to-audio host
On the Gemini path the host does speech in and speech out directly, so Deepgram
STT and ElevenLabs TTS are not in the pipeline. Gemini emits function calls
that are executed by the existing registry-validated `ToolBox` (D6), plus the
zero-argument `assess_current_turn` Jev tool (D5). One Gemini session and one
Jev state object are created per socket and are never shared across sockets or
calls.

### D4. Twilio ↔ Gemini audio bridge with bounded buffering
Twilio carries 8kHz µ-law in 20ms frames; Gemini takes 16kHz PCM input and
emits 24kHz PCM output. The bridge converts both directions:

- Input: µ-law → PCM16 @ 8kHz → resample to 16kHz PCM → Gemini.
- Output: Gemini 24kHz PCM → resample to 8kHz → PCM16 → µ-law → Twilio.

Buffering is bounded on both sides: fixed-capacity ring buffers sized in
milliseconds, a high-water mark, and a stated overflow policy (drop-oldest on
the output side, with a counter) so a slow upstream can never grow memory
without limit. Frames stay aligned to the 20ms telephony cadence; every buffer
overflow, underrun, resample and drop is counted for D11.

### D5. Jev structured-decision sidecar (`jev-1.13.0`)
TypeSafe Jev is pinned at `jev-1.13.0` and runs beside the audio host as a fast
structured-decision sidecar:

- **Exposure.** Jev is exposed to Gemini as a **zero-argument internal function
tool**, `assess_current_turn`. The tool handler reads the latest finalized
caller transcript and state from the per-socket `CallContext`, redacts locally,
then calls Jev and returns a typed assessment (`intent`, `emergency`,
`clarification`, `confidence`) or an abstention. The transcript and state are
never model-supplied arguments: because the tool takes no arguments, Gemini
cannot inject or paraphrase the text Jev sees.
- **Redaction.** Phone number, national id, date of birth and raw record fields
are stripped locally before the sidecar is called.
- **Timeout and abstention.** Hard timeout: **300ms**. On timeout, low
confidence, or any error, `assess_current_turn` returns an abstention result
and the turn proceeds exactly as if Jev were absent; Jev never blocks the safe
path, the fallback, or the call.
- **Authority.** Jev never handles VAD or barge-in, never authorizes or
performs a write, and never calls the clinic API directly. It only annotates a
decision that the deterministic tools already permit (D6).
- **Policy.** The prompt requires `assess_current_turn` before high-risk/write
tools, but every tool still authorizes independently: a missing, abstaining or
low-confidence Jev result cannot unlock a tool and cannot be the thing that
permits a submission.

### D6. Deterministic rules and tools are the source of truth
Every scheduling fact and action still comes from `clinic/` + `scheduling/`
behind the registry-validated `ToolBox`: tools accept only ids, slots, tokens
and appointment types previously returned by a clinic lookup, so neither Gemini
nor Jev can invent one. Gemini function calls are dispatched to that same
`ToolBox`. Jev output can annotate or abstain; it can never create, mutate or
submit an action.

### D7. Deterministic scheduling core (pure Python, fully unit-tested)
`clinic/` (API client + immutable catalogue cache warmed from `/clinic` at
startup) and `scheduling/` (Europe/Madrid date resolver with closure days and
site hours; rules engine mapping plan/specialty/provider/age/site to the closed
reason vocabulary; slot matcher). No LLM in this layer, on either engine.

### D8. Submission recorder: 30s window, exactly once
Per-call `ActionRecorder` collects validated intents; a single owner flushes
POSTs on `stop`/socket close with bounded retries, treats 409 as success, and
guarantees exactly one submission per action (no double-POST on a teardown
race). Flush starts the moment the call ends, well inside the window.

### D9. Cancellation and interruption
The Gemini path uses the host's interruption signalling plus a per-socket
cancel token: pending model work is cancelled, queued audio is not emitted
after a cancel, and the buffer is reset. The cascade path keeps Silero
VAD-driven barge-in. Cancellation never suppresses the submission, which is
driven by the call record rather than by the audio path.

### D10. Language strategy (rollback cascade)
On `cascade`, STT is Deepgram nova-3 `multi` (es/en) with a Helmcode `whisper`
transcription fallback if nova quality fails problem 11 practice; TTS is
ElevenLabs turbo v2.5 (multilingual incl. Catalan) with Cartesia sonic as
fallback. On `gemini_live` the host handles speech directly and the prompt
still requires replying in the caller's language. The cascade LLM is the
existing OpenAI-compatible service selected by `AGENT_MODEL` (currently
Helmcode); it is rollback, never the primary host.

### D11. Structured metrics for model, audio, latency and cost
Every call writes structured records to `backend/data/calls/<call_id>.jsonl`
and the ops console reads them. Required fields: engine and pinned model id;
audio conversion counters (frames, resampler, buffer high-water, drops,
underruns); per-turn TTFT; tool calls with arguments and results; Jev latency,
confidence and abstention counts; token/audio usage and estimated cost.

### D12. Explicit timeouts, retries and no hidden fallback
Every provider call has explicit connect, read and first-token timeouts;
retries are bounded with exponential backoff and honour `Retry-After` on 429;
4xx contract errors are not retried. A rollback from `gemini_live` to `cascade`
is an explicit configuration decision recorded in the audit — never an
invisible model swap.

### D13. Observability first-class from hour one
Every call writes JSONL (frames timeline, tool calls, actions, errors) to
`backend/data/calls/<call_id>.jsonl` + a FastAPI ops console (`/ops`) reading it
— this is the jury-facing platform and the debug loop.

### D14. Concurrency and the evaluation gate
10 concurrent scored calls is the design point (Run All opens ten). A 20-socket
burst is the diagnostic. The offline suite must pass for both engines and the
audio bridge; the live practice/eval gate (one practice case, then a scored
Run All) decides whether `gemini_live` becomes the default in place of
`cascade`.

### D15. Same-origin browser call simulator
FastAPI serves a dependency-free browser client at `/call` and a dedicated
`/ws/demo` WebSocket. The demo endpoint builds the same per-socket pipeline and
uses the same Twilio Media Streams serializer as `/ws`, but its `CallContext`
is marked non-submitting so synthetic browser call ids never POST to Prosper.
The scored `/ws` path and its exactly-once submission behavior are unchanged.

Microphone access starts only from the call-button user gesture. An
`AudioWorklet` downsamples device PCM to 8kHz, encodes G.711 mu-law and emits
canonical 20ms Twilio media messages. Agent media is decoded and played through
Web Audio; `clear` immediately discards queued playback. The client bounds
network and playback queues, derives `ws`/`wss` from the page origin, and tears
down every media track, audio node and socket on hangup or failure.

The page follows the ClinicReflow visual system: a light editorial operations
surface with warm paper, graphite controls, brass metadata and ember reserved
for active/error states. It uses a sticky clinic header, Spanish operational
copy, a kicker/title/lead page header, an ash well containing the call document,
and accessible brass focus rings. The interface remains dependency-free and
uses reduced-motion-safe section reveals.

## Risks / Trade-offs

- [pipecat version churn] → pin exact version, smoke-test with wscat before
  every Run All.
- [LLM drift on ids] → tool-layer validation makes wrong ids structurally
  impossible; model and sidecar only narrate/annotate.
- [Audio conversion drift] → bounded ring buffers with counters and an
  alignment test at 20ms; overflow is visible, never silent.
- [Jev on the critical path] → 300ms hard timeout with abstention; the sidecar
  is optional by construction.
- [Single local host] → ngrok static domain, launchd keepalive, wscat health
  check in Makefile.

## Migration Plan

Empty repo → scaffold → config-flag rollout. `cascade` stays the default until
the live gate passes; then `VOICE_ENGINE=gemini_live` becomes the default and
`cascade` remains the one-setting rollback. No data migration.

## Open Questions

- Gemini 3.8 Live session limits and exact pricing for the 20-socket burst.
- Resampler choice and whether to reuse the existing soxr path.
- Jev 300ms budget under 20 concurrent sockets.
- Exact Deepgram model for Catalan once problem 11 opens (practice will tell).
