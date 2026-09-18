# Reflow interface v0 — optimizer ⇄ voice negotiation

Contract between Germán's optimizer and Ginés's voice negotiation agent.
Backed by a local JSON queue (`backend/data/reflow/`) until the optimizer service
lands; the voice side never talks to the optimizer in-process.

## Batch file: `backend/data/reflow/<batch_id>.json`

Created by the "médico no disponible" trigger (ops console / frontend).

```json
{
  "batch_id": "rf_20260919_1200",
  "unavailable_provider_id": "PR03",
  "reason": "sick_leave",
  "created_at": "2026-09-19T12:00:00+02:00",
  "appointments": [
    {
      "appointment_id": "APPT-0042",
      "patient_id": "P00123",
      "patient_display_name": "Marta Ruiz",
      "simulation": false,
      "original_slot": "2026-09-22T10:30:00+02:00",
      "duration_minutes": 30,
      "specialty_id": "dermatologia",
      "alternatives": [
        {
          "alternative_id": "A1",
          "provider_id": "PR07",
          "location_id": "centro",
          "slot": "2026-09-22T11:00:00+02:00",
          "duration_minutes": 30
        },
        {
          "alternative_id": "A2",
          "provider_id": "PR05",
          "location_id": "norte",
          "slot": "2026-09-23T09:15:00+02:00",
          "duration_minutes": 30
        }
      ]
    }
  ]
}
```

- `alternatives` come from the optimizer, already filtered by professional,
  duration, center and registered constraints, ranked by preference.
- `simulation: true` marks simulated patients (7 of 8) — the voice agent
  reads their scripted answer from `simulation_reply` instead of calling.

## Per-appointment state file: `backend/data/reflow/<batch_id>/<appointment_id>.json`

Voice agent writes the patient's decision after every negotiation call.

```json
{
  "appointment_id": "APPT-0042",
  "outcome": "accepted | rejected | counter_offered | unreachable",
  "accepted_alternative_id": "A1",
  "counter_constraints": ["no puedo ese dia", "no cambiar de medico"],
  "caller_language": "es",
  "call_id": "CAxxxxxxxx",
  "decided_at": "2026-09-19T12:05:10+02:00"
}
```

The optimizer polls these files and recalculates the plan after each one.
`rejected` + `counter_constraints` is the input to the next optimizer pass.

## Voice tool seam

- `get_reflow_context(appointment_id)` → loads the batch entry (the agent
  opens the call knowing the patient, their appointment and the offers).
- `commit_reflow_decision(appointment_id, outcome, accepted_alternative_id,
  counter_constraints)` → writes the state file; only authorized changes are
  committed, everything else stays pending for the optimizer.
