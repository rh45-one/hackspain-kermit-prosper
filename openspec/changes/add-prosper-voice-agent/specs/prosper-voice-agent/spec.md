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
