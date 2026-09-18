# prosper-voice-agent Specification

## ADDED Requirements

### Requirement: Answer calls over the Twilio Media Streams wire
The agent SHALL expose a WebSocket endpoint that accepts the Prosper harness
connection, speaks the Twilio Media Streams protocol (camelCase JSON,
string-typed `sequenceNumber`/`chunk`/`timestamp`, 8kHz µ-law base64 media),
and SHALL keep every conversation object strictly per-socket.

#### Scenario: Caller id present
- **WHEN** a `start` message arrives with `customParameters.from_number`
- **THEN** the agent uses it as a lookup hint against the directory, never as
  identification, and greets the caller personally when the hint resolves.

#### Scenario: Caller id withheld
- **WHEN** `start` arrives without `from_number`
- **THEN** the agent asks the caller for identification normally.

#### Scenario: Concurrent burst
- **WHEN** 20 sockets connect simultaneously
- **THEN** each socket holds an independent pipeline, call_id, transcript and
  submission, with no shared mutable state.

### Requirement: Identify the caller before acting
The agent SHALL resolve the patient via the directory using the phone hint
plus a spoken second identifier, SHALL treat an exact-field mismatch as an
exclusion, and SHALL use only `patient_id` values returned by the API.

#### Scenario: Phone hit plus confirmation
- **WHEN** the caller id matches exactly one patient
- **THEN** the agent confirms identity with one spoken second field before
  reading or writing anything.

#### Scenario: Ambiguous match
- **WHEN** a name matches several patients
- **THEN** the agent disambiguates with date of birth or national id.

### Requirement: Schedule with clinic rules, not conversation
The agent SHALL compute availability, appointment type, and refusals from the
clinic API responses; SHALL submit the `appointment_type` returned by
availability; SHALL resolve relative dates deterministically in
Europe/Madrid; and SHALL never book a same-day slot.

#### Scenario: Relative date on a closure day
- **WHEN** the caller says "first thing Monday" on Friday 9 October
- **THEN** the agent books the next open day per clinic hours and states why.

#### Scenario: Restriction refusal
- **WHEN** availability returns a `blocked` restriction for the only provider
- **THEN** the agent submits NO_ACTION with the matching closed-vocabulary
  reason and tells the caller why.

### Requirement: Submit every call's outcome inside the window
The agent SHALL POST one submission per action to /api/v1/submit/* with the
`call_id` from `start.callSid`, within 30 seconds of socket close, retrying
idempotently and treating 409 as success.

#### Scenario: Correct refusal still reports
- **WHEN** a call ends with no booking
- **THEN** a NO_ACTION (or ESCALATE) submission is always POSTed; the record
  is never empty.

#### Scenario: Multi-action call
- **WHEN** the caller cancels one appointment and books another
- **THEN** two submissions are POSTed, one per action route.

### Requirement: Protect patient data in speech
The agent SHALL never speak another patient's national id or phone number,
and SHALL decline out-of-scope requests with NO_ACTION(out_of_scope).

#### Scenario: Injection attempt
- **WHEN** the caller asks for another patient's data or medical advice
- **THEN** the agent declines, books nothing, and leaks nothing into audio.

### Requirement: Observability of every call
The agent SHALL persist a structured per-call record (call_id, transcript,
tool calls with arguments, actions submitted, timings) to local storage and
SHALL expose it via a local ops console.

#### Scenario: Jury replay
- **WHEN** the jury asks why the agent decided something
- **THEN** the console shows the call timeline end to end.

### Requirement: Select one audio host per socket

The agent SHALL select exactly one audio host per socket through the
`VOICE_ENGINE` feature flag, SHALL support `gemini_live` (Gemini 3.8 Live,
model id `gemini-3.8-live`) and `cascade`, and SHALL record the chosen engine
in the per-call audit.

#### Scenario: Gemini Live selected
- **WHEN** `VOICE_ENGINE=gemini_live`
- **THEN** the socket runs the Gemini host and omits the Deepgram and
  ElevenLabs processors.

#### Scenario: Cascade selected
- **WHEN** `VOICE_ENGINE=cascade`
- **THEN** the socket runs the rollback cascade and one engine is chosen per
  socket, never both.

### Requirement: Convert Twilio audio to and from Gemini formats with bounded buffering

The agent SHALL convert Twilio 8kHz µ-law input to 16kHz PCM for Gemini and
Gemini 24kHz PCM output to 8kHz µ-law for Twilio, SHALL keep both directions
in bounded buffers with an explicit overflow policy, and SHALL count every
conversion, buffer high-water and dropped frame.

#### Scenario: Input conversion
- **WHEN** a 20ms 8kHz µ-law frame arrives
- **THEN** it is decoded and resampled to 16kHz PCM in arrival order.

#### Scenario: Output buffer overflow
- **WHEN** the outbound buffer reaches its high-water mark
- **THEN** the oldest audio is dropped under the stated policy, a drop counter
  increments, and buffering never grows without bound.

### Requirement: One Gemini and one Jev state per socket

The agent SHALL create one Gemini session and one Jev state object per socket
and SHALL never share either across sockets or calls.

#### Scenario: Concurrent sockets
- **WHEN** 20 sockets connect simultaneously
- **THEN** each holds its own Gemini session and Jev state with no shared
  mutable state.

### Requirement: Route Gemini function calls through the validated ToolBox

The agent SHALL execute every Gemini function call through the existing
registry-validated `ToolBox` and SHALL reject any tool argument that was not
previously returned by a clinic lookup.

#### Scenario: Unknown id requested
- **WHEN** Gemini requests a tool with an id it was never given
- **THEN** the tool rejects it and no action is queued.

### Requirement: Jev is a zero-argument redacted turn-assessment tool

Jev SHALL be exposed to Gemini only as a zero-argument internal function tool,
`assess_current_turn`, which reads the latest finalized caller transcript and
state from the per-socket `CallContext`, redacts it locally, and returns a
typed assessment of intent, emergency, clarification and confidence, or an
abstention. Phone number, national id, date of birth and raw record fields
SHALL be stripped before the sidecar is called. The tool SHALL have a 300ms
hard timeout and SHALL abstain on low confidence, timeout or failure. The
transcript and state SHALL never be passed as model-supplied tool arguments.

#### Scenario: Assess the current turn
- **WHEN** Gemini calls `assess_current_turn` with no arguments
- **THEN** the handler reads the finalized transcript from `CallContext`,
  redacts it locally, and returns a typed assessment or an abstention.

#### Scenario: Model-supplied transcript rejected
- **WHEN** a call to `assess_current_turn` carries arguments
- **THEN** it is rejected as a schema violation, and the transcript Jev sees is
  never the model's to supply.

#### Scenario: Protected value in transcript
- **WHEN** the finalized transcript contains a national id or phone number
- **THEN** those values are stripped before Jev is called.

#### Scenario: Timeout or low confidence
- **WHEN** Jev exceeds 300ms or returns low confidence
- **THEN** `assess_current_turn` returns an abstention and the host proceeds as
  if Jev were absent.

### Requirement: Jev never acts, never handles turn-taking, never authorizes writes

Jev SHALL never handle VAD or barge-in, SHALL never authorize or perform a
write, and SHALL never call the clinic API; its output SHALL only annotate a
decision the deterministic tools already permit.

#### Scenario: Jev decision
- **WHEN** Jev emits a decision
- **THEN** the deterministic rules and tools remain the only source of a
  scheduling action and Jev alone can never cause a submission.

### Requirement: Assess the turn before high-risk tools, but tools authorize independently

The prompt SHALL require Gemini to call `assess_current_turn` before
high-risk/write tools, while every tool SHALL still authorize and validate
independently; a missing, abstaining or low-confidence Jev result SHALL NOT
permit a tool and SHALL NOT block the safe path or the fallback.

#### Scenario: Assessment precedes a write
- **WHEN** Gemini is about to call a write tool
- **THEN** the prompt directs it to call `assess_current_turn` first.

#### Scenario: Jev timeout does not block the safe path
- **WHEN** `assess_current_turn` times out
- **THEN** the turn continues, tools authorize independently, and the fallback
  is never blocked by Jev.

### Requirement: Deterministic rules and tools remain the source of truth

The agent SHALL compute availability, appointment type and refusals from
clinic API responses on both engines and SHALL never let the audio host or the
sidecar invent a fact or an action.

#### Scenario: Gemini path booking
- **WHEN** a booking is submitted on the Gemini path
- **THEN** every field traces to a registry-validated tool result.

### Requirement: Exactly-once submission with cancellation and interruption

The agent SHALL submit each call's actions exactly once inside the 30-second
window regardless of cancellation or interruption, and SHALL support barge-in
and cancellation without dropping the submission.

#### Scenario: Interrupt then hang up
- **WHEN** the caller interrupts the agent and the call then ends
- **THEN** exactly one submission per action is POSTed.

#### Scenario: Teardown race
- **WHEN** a teardown race occurs at socket close
- **THEN** no duplicate POST is made and 409 is treated as success.

### Requirement: Structured metrics for the voice path

The agent SHALL emit structured per-call metrics for the selected engine and
model, audio conversion, TTFT, tool calls, Jev latency, confidence and
abstention, and cost.

#### Scenario: Call audit
- **WHEN** a call ends
- **THEN** the audit record contains the engine, model id, conversion counters,
  TTFT samples, tool calls, Jev statistics and cost.

### Requirement: No hidden fallback, explicit timeouts and retries

The agent SHALL use explicit connect, read and first-token timeouts and bounded
retries with backoff, and SHALL NOT silently swap model, provider or engine;
any rollback SHALL be an explicit, logged configuration event.

#### Scenario: Gemini path failure
- **WHEN** the Gemini path fails
- **THEN** the agent rolls back to `cascade` only as an explicit, recorded
  decision and never mid-turn invisibly.

### Requirement: Concurrency and evaluation gate

The agent SHALL be exercised for 10 concurrently scored calls and a 20-socket
diagnostic, and SHALL pass offline tests plus a live practice/eval gate before
`gemini_live` replaces `cascade` as the default.

#### Scenario: Twenty-socket diagnostic
- **WHEN** 20 sockets connect simultaneously
- **THEN** all are accepted and served without cross-talk.

#### Scenario: Live gate not yet run
- **WHEN** the offline suite passes but the live practice/eval gate has not run
- **THEN** `cascade` remains the default.
