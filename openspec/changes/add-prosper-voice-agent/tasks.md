# Tasks: add-prosper-voice-agent

Baseline evidence (2026-09-19): `uv run --project backend pytest -q` collects
**345 tests**; 344 pass and 1 skips (the factory dependency-guard test is
unreachable now that `pipecat-ai[google]` is installed). The date-dependent
closure-day test is fixed with a frozen-clock fixture. Checkboxes below are
marked `[x]` only where backed by the offline suite or a present, wired
module; live-gate items stay unchecked.

## 1. Scaffold (coordinator)

- [x] 1.1 uv project, pinned deps, package layout, .env.example, Makefile, runbook README
- [x] 1.2 OpenAPI schema vendored at docs/prosper/openapi.json
- [x] 1.3 Config + structured logging + paths

## 2. Clinic layer (worker A — owns backend/src/agent/clinic/, backend/tests/test_clinic*)

- [x] 2.1 httpx client: directory, availability, appointments, catalogue, health; X-Api-Key; 422/404 typed errors
- [x] 2.2 CatalogueCache: warm /clinic at startup; provider/specialty/type/plan/site lookups; nearest-site haversine
- [x] 2.3 Unit tests against vendored schema fixtures (no network)

## 3. Scheduling core (worker B — owns backend/src/agent/scheduling/, backend/tests/test_scheduling*)

- [x] 3.1 Date resolver: fixed problem-5 vocabulary, Europe/Madrid, closure days, site hours, no same-day, part-of-day
- [x] 3.2 Rules engine: age window, referral, plan×specialty×site×provider matrix → closed reason vocabulary
- [x] 3.3 Slot matcher: earliest-from-tomorrow, tie-break load spreading, filters (site/provider/part-of-day/language)
- [x] 3.4 Submission recorder: action dataclasses, normalization per scoring doc, POST client, 409-as-success, bounded retry
- [x] 3.5 Unit tests incl. Fiesta Nacional 12 Oct, Friday-lunch Sur, second-policy flow

## 4. Voice pipeline (coordinator — owns backend/src/agent/voice/, backend/src/agent/brain/)

- [x] 4.1 pipecat WebsocketServerTransport + TwilioFrameSerializer server on /ws
- [x] 4.2 Per-socket PipelineTask wiring STT→LLM(tools)→TTS with Silero barge-in
- [x] 4.3 Guarded tool set over clinic+scheduling (registry-validated ids) — 38/39 brain-tool tests pass; the one red test is the date-dependent closure case noted above
- [x] 4.4 System prompt v1 (multilingual, refusal discipline, no-id-speech)
- [x] 4.5 Local audio simulator: script a public case, dial own WS without the harness

## 5. Integration & rehearsal

- [ ] 5.1 Practice problem 1 end-to-end via harness (needs team pk- key + ngrok) — live, not offline-provable
- [x] 5.2 Concurrency soak: 20 local WS clients (`test_twenty_concurrent_handshakes`, `CONCURRENT_SOCKETS = 20`)
- [ ] 5.3 Problem 3 (doctor/site) + problem 4 (register) rehearsal — live harness
- [ ] 5.4 Run All #1, read verdicts, fix fields — live harness

## 6. Jury platform / FrontDesk (worker C)

- [x] 6.1 FastAPI `/ops` HTML+JSON fallback over `data/calls/*.jsonl`
- [x] 6.2 Next.js FrontDesk scaffold in `frontend/` (App Router, Tailwind, shadcn/ui, lucide, date-fns, Europe/Madrid)
- [x] 6.3 Dashboard shell: sidebar (Calls, Calendar, Patients, Settings) + header (tunnel status, n/10 capacity)
- [x] 6.4 `/calls` live monitor: 10-card grid, ≥2 mock concurrent calls, transcript, barge-in, live entities, handover
- [x] 6.5 `/patients` directory: name + DNI/NIE filters (control letter), detail with history and derived triage
- [x] 6.6 `/calendar` week/day view in Europe/Madrid with BOOKED / CANCELLED / REFUSED / DIVERTED colours
- [x] 6.7 `/settings`: tunnel URL (`ws://`/`wss://` only), voice/prompt, knowledge-source uploads (CSV / SQL / API)
- [ ] 6.8 ClinicReflow demo seam: "doctor unavailable" → affected list → negotiation call → plan delta
- [x] 6.9 Observatory metrics on `/calls`: capacity ring, hourly load/submissions, closed outcome mix (mock-first)

## 7. Gemini Live audio host (new)

- [x] 7.1 `VOICE_ENGINE` setting and per-socket engine resolution; record the chosen engine in the call audit — settings validator + `resolve_voice_engine` fail fast; `engine_selected` audited per socket (`test_integration_engine.py`)
- [x] 7.2 Gemini Live service adapter for `gemini-3.8-live`: one session per socket, streaming, function-call frames — pinned factory + per-socket instances verified with a fake service class
- [x] 7.3 Twilio ↔ Gemini audio bridge: µ-law↔PCM16 decode/encode and 8kHz↔16kHz / 24kHz resampling at 20ms alignment — split into direction-explicit `GeminiInputBridge`/`GeminiOutputBridge` with an end-to-end frame-direction test
- [x] 7.4 Bounded ring buffers for both directions with high-water mark, overflow policy and drop/underrun counters — `audio/buffers.py` + converter counters audited at teardown
- [x] 7.5 Dispatch Gemini function calls into the existing registry-validated `ToolBox`; reject unregistered arguments — toolbox.tools() handed to the service; registry guards unchanged and tested
- [x] 7.6 Cancellation/barge-in token on the Gemini path; clear queued audio and reset buffers on interrupt — InterruptionFrame resets the shared converter; ctx.cancel_token set on stop

## 8. Jev structured-decision sidecar (new)

- [x] 8.1 Pin `jev-1.13.0`; client plus one Jev state object per socket — `jev_model` default in Settings; ToolBox builds one client per socket and closes it at teardown
- [x] 8.2 Expose Jev to Gemini only as the zero-argument `assess_current_turn` internal function tool; the handler reads the finalized transcript and state from `CallContext`, and any model-supplied arguments are rejected — registered only for `gemini_live`; snapshot comes from `ctx.latest_caller_turn` only
- [x] 8.3 Redaction layer: strip phone, national id, date of birth and raw record fields locally before Jev is called — known patient names scrubbed locally, then core regex redaction in-tool and again in the client
- [x] 8.4 Return a typed assessment (intent, emergency, clarification, confidence) with a 300ms hard timeout and abstention on timeout, low confidence or error — typed `TurnDecision`; toolbox additionally converts an unexpected sidecar crash into an abstention
- [x] 8.5 Prompt policy requiring `assess_current_turn` before high-risk/write tools, with every tool still authorizing independently — SYSTEM_PROMPT carries the advisory-only policy, safe for cascade where the tool is absent
- [x] 8.6 Enforce the annotate-only contract (no writes, no VAD/barge-in, no clinic API) with tests proving Jev cannot submit an action, a Jev timeout cannot block the safe path or the fallback, and the transcript is never model-supplied — PII-free result/audit assertions in `test_brain_tools.py`

## 9. Engine integration, rollback and semantics (new)

- [x] 9.1 Pipeline factory selects the host by `VOICE_ENGINE`; `cascade` stays the default and is unchanged — cascade pipeline bytes untouched; engine branch tested
- [x] 9.2 Explicit gemini_live → cascade rollback, logged as a configuration event; no hidden mid-turn fallback — superseded by coordinator review: gemini_live without the dependency or key FAILS FAST at socket startup (RuntimeError); no silent or mid-call fallback exists
- [ ] 9.3 Explicit connect/read/first-token timeouts and bounded retries with backoff, honouring Retry-After on 429 — Jev is deliberately one-shot/300ms; Gemini transport timeouts need live verification
- [x] 9.4 Exactly-once submission verified on the Gemini path including the socket-close teardown race — `ctx.submitted` guard tested with repeated teardowns

## 10. Metrics, concurrency and evaluation gate (new)

- [x] 10.1 Structured metrics: engine/model, audio conversion counters, TTFT, tool calls, Jev latency/confidence/abstention, cost — `engine_selected`, `audio_bridge_metrics`, `jev_assessment` (latency/confidence/abstention/usage) audited PII-free; TTFT and cost need live data
- [x] 10.2 Offline tests for the bridge, engine selection, Jev abstention and per-socket isolation — `test_gemini_live.py`, `test_integration_engine.py`, `test_brain_tools.py`
- [x] 10.3 10-call scored concurrency plus the 20-socket diagnostic on the Gemini path — 20 lightweight concurrent sockets pass offline (`test_twenty_lightweight_concurrent_sockets_on_gemini`); the scored 10-call run is live and stays open under 10.4
- [ ] 10.4 Live gate: one practice case, then a scored Run All; only then may `gemini_live` replace `cascade` as the default
- [x] 10.5 Record a privacy-safe per-call pipeline-stage and empty-action diagnostic summary
- [x] 10.6 Expose the diagnostic summary through the ops call record
- [x] 10.7 Add offline tests for silence, tool failure and a successfully queued action
