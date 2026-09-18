# frontdesk-ops-console Specification

## ADDED Requirements

### Requirement: Staff dashboard shell
The FrontDesk SHALL live in `frontend/` as a Next.js App Router app and SHALL
present a sidebar (Monitor de Llamadas, Calendario, Pacientes, Configuración
del Agente) plus a header that shows public-tunnel connection state and
capacity as `n/10` active calls.

#### Scenario: Receptionist lands
- **WHEN** a staff member opens the app
- **THEN** they see the dashboard shell and can reach `/calls`, `/patients`,
  `/calendar` and `/settings` without leaving the layout.

#### Scenario: Capacity at a glance
- **WHEN** three mock (or live) calls are active
- **THEN** the header reads `3/10 llamadas activas` and the tunnel pill
  reflects whether a `ws://` or `wss://` endpoint is configured.

### Requirement: Live call monitor
The `/calls` view SHALL render a grid of up to 10 concurrent call cards. Each
active card SHALL show socket/call id, virtual phone, live transcript,
barge-in / turn-taking state, live entities (name, national id, appointment
type), and a handover control that marks the call DIVERTED (`ESCALATE`).

The browser SHALL NOT attach to the Twilio Media Streams `/ws`; cards are fed
by mock call records (and later by the ops audit API).

#### Scenario: Two concurrent calls without a backend
- **WHEN** the monitor opens with no voice server
- **THEN** at least two active cards still stream a mock transcript so the
  jury can read the UI.

#### Scenario: Human takeover
- **WHEN** the receptionist clicks "Tomar el control" on an active card
- **THEN** that card's outcome becomes DIVERTED and capacity decrements.

### Requirement: Patient directory
The `/patients` view SHALL simulate `GET /api/v1/directory`: a filterable
table on full name and national id (DNI/NIE including the control letter).
Selecting a row SHALL open a detail pane with appointment history and a
reception triage flag derived from the latest agent action (not a clinical
score).

#### Scenario: Control letter mismatch
- **WHEN** the DNI/NIE filter contains a letter that does not match the
  digits
- **THEN** the UI rejects the filter as invalid and does not query.

#### Scenario: Name plus document
- **WHEN** the receptionist filters by surname and a valid DNI
- **THEN** only matching mock patients remain in the table.

### Requirement: Appointment calendar in Europe/Madrid
The `/calendar` view SHALL render week and day grids whose instants are
converted to `Europe/Madrid`. Each appointment chip SHALL use receptionist
colours mapped from the closed action verbs: `BOOK`/`REGISTER`/`RESCHEDULE`
→ BOOKED (green), `CANCEL` → CANCELLED (red), `NO_ACTION` → REFUSED (grey,
showing the closed-vocabulary reason), `ESCALATE` → DIVERTED (orange).

#### Scenario: Offset-aware slot
- **WHEN** a slot is stored as `2026-09-24T16:30:00+02:00`
- **THEN** the chip renders 16:30 on that Madrid calendar day, never shifted
  to the browser's local zone.

#### Scenario: Refusal is visible
- **WHEN** an appointment outcome is `NO_ACTION(referral_required)`
- **THEN** the chip is grey and the restriction reason is readable without
  opening a dialog.

### Requirement: Agent settings
The `/settings` view SHALL let staff set the public tunnel URL and optional
auth headers, choose a voice pipeline preset and behaviour prompt, and
register knowledge sources (CSV upload, SQL connection string, clinic API
sync). A tunnel URL that does not start with `ws://` or `wss://` SHALL fail
validation and MUST NOT be saved.

#### Scenario: Invalid tunnel
- **WHEN** the staff member submits `https://example.ngrok-free.app/ws`
- **THEN** the form is rejected and the previous valid URL (if any) is kept.

#### Scenario: Valid tunnel
- **WHEN** they submit `wss://a1b2c3d4.ngrok-free.app/ws`
- **THEN** the value is stored and the header connection pill updates.
