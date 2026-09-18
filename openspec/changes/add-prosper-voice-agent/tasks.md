# Tasks: add-prosper-voice-agent

## 1. Scaffold (coordinator)

- [x] 1.1 uv project, pinned deps, package layout, .env.example, Makefile, runbook README
- [x] 1.2 OpenAPI schema vendored at docs/prosper/openapi.json
- [x] 1.3 Config + structured logging + paths

## 2. Clinic layer (worker A — owns backend/src/agent/clinic/, backend/tests/test_clinic*)

- [ ] 2.1 httpx client: directory, availability, appointments, catalogue, health; X-Api-Key; 422/404 typed errors
- [ ] 2.2 CatalogueCache: warm /clinic at startup; provider/specialty/type/plan/site lookups; nearest-site haversine
- [ ] 2.3 Unit tests against vendored schema fixtures (no network)

## 3. Scheduling core (worker B — owns backend/src/agent/scheduling/, backend/tests/test_scheduling*)

- [ ] 3.1 Date resolver: fixed problem-5 vocabulary, Europe/Madrid, closure days, site hours, no same-day, part-of-day
- [ ] 3.2 Rules engine: age window, referral, plan×specialty×site×provider matrix → closed reason vocabulary
- [ ] 3.3 Slot matcher: earliest-from-tomorrow, tie-break load spreading, filters (site/provider/part-of-day/language)
- [ ] 3.4 Submission recorder: action dataclasses, normalization per scoring doc, POST client, 409-as-success, bounded retry
- [ ] 3.5 Unit tests incl. Fiesta Nacional 12 Oct, Friday-lunch Sur, second-policy flow

## 4. Voice pipeline (coordinator — owns backend/src/agent/voice/, backend/src/agent/brain/)

- [ ] 4.1 pipecat WebsocketServerTransport + TwilioFrameSerializer server on /ws
- [ ] 4.2 Per-socket PipelineTask wiring STT→LLM(tools)→TTS with Silero barge-in
- [ ] 4.3 Guarded tool set over clinic+scheduling (registry-validated ids)
- [ ] 4.4 System prompt v1 (multilingual, refusal discipline, no-id-speech)
- [ ] 4.5 Local audio simulator: script a public case, dial own WS without the harness

## 5. Integration & rehearsal

- [ ] 5.1 Practice problem 1 end-to-end via harness (needs team pk- key + ngrok)
- [ ] 5.2 Concurrency soak: 20 local WS clients
- [ ] 5.3 Problem 3 (doctor/site) + problem 4 (register) rehearsal
- [ ] 5.4 Run All #1, read verdicts, fix fields

## 6. Jury platform (worker C, later wave)

- [ ] 6.1 Ops console: live call timeline, transcripts, actions, costs
- [ ] 6.2 ClinicReflow demo seam: "doctor unavailable" → affected list → negotiation call → plan delta
