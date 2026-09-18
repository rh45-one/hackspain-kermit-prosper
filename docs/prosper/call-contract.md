# The call contract

How a call reaches you, and what you POST when it ends. Frozen for the event:
once your agent integrates, only additive changes happen â new optional
fields, new `reason` values â never a breaking one.

## 1. How a call reaches you

You give us one WebSocket URL. When it is your turn we connect to it and speak
**exactly the wire format Twilio's Media Streams uses for a voice app**,
playing the part of the carrier. You need no Twilio account, no phone number
and no telephony of your own â just a socket.

We send, in order:

1. `connected`.
2. `start`. Its `start.callSid` is the id for this call â **this is the
   `call_id` you send back**. Keep it. `start.customParameters` carries two
   more values, the way a Twilio stream parameter does:
   - `call_id` â the same id again, for convenience.
   - `from_number` â **the number the caller is ringing from**, in E.164
     (`+34612345678`). It is the number the clinic holds for them, so
     `GET /api/v1/directory?phone=+34612345678` finds their chart before they
     have said a word. The parameter is **absent** when the caller id is
     withheld, which is what a caller the clinic has no number for looks like
     â so treat it as a hint, never as identification. The caller is also not
     always the patient.
3. `media` messages: 20ms frames of 8kHz Âµ-law audio, base64-encoded, in real
   time. This is the caller's voice.
4. `stop` when the call ends on our side, then we close the socket.

The message shapes are Twilio's own â see
[their reference](https://www.twilio.com/docs/voice/media-streams/websocket-messages).
Two easy-to-miss quirks: `sequenceNumber`, `chunk` and `timestamp` are
**strings** on the wire, not numbers, and every key is camelCase.

Your agent talks back over the same socket with its own `media` messages. You
may send `mark` and `clear` â they exist on the wire, but **turn-taking and
interruption are entirely yours**. We implement no server-side barge-in;
`clear` has no effect on our side today.

### More than one call at a time

One URL, many calls. A Run All opens **ten** sockets to your endpoint at once,
each with its own `start.callSid`, overlapping for the whole conversation.
Problem 2's largest burst opens twenty.

Everything a call owns â the conversation, its `call_id`, its submission â is
per socket. Sharing one conversation, one session object or one in-flight
`call_id` across sockets is the mistake this challenge looks for. Build a
fresh pipeline per connection.

A refused or dropped connection is a failed call for the case it carried; the
other calls in that wave continue and are scored normally.

## 2. The submission window

The window opens when we open the call and closes **30 seconds after our
socket to you closes**. Arriving early, before the call ends, is never a
rejection reason â only arriving late is.

| Situation | Response |
|---|---|
| `call_id` was never one we called you on, or is another team's | `404` |
| Call still open, or closed at most 30s ago | `200` â accepted |
| Call closed more than 30s ago | `410` â window closed |
| An identical action was already accepted for this call | `409` |
| Malformed body | `422`, and nothing is recorded |

A call's record is **every action accepted inside its window**. Most calls
submit one; "cancel mine and my son's" submits two, one request each. An
identical action twice is a retry and returns `409` â expected, not a bug.
After the window every route returns `410`: the deadline is checked before
anything else. A `200` acknowledges receipt, not a pass.

## 3. `POST /api/v1/submit/<action>`

One route per action, each with the payload that action carries and nothing
else. Send your desk-issued key in `X-Api-Key`. Attribution comes from the
registered call session, never from a team id in the body.

The clinic is read-only, so nothing here mutates anything: you report the
write you **would** have made.

```http
POST /api/v1/submit/book
```
```json
{
  "call_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "patient_id": "P00042",
  "provider_id": "PR05",
  "location_id": "sur",
  "appointment_type_id": "review",
  "slot": "2026-09-24T16:30:00+02:00",
  "policy_id": "sanitas"
}
```

| Route | Body, besides `call_id` |
|---|---|
| `POST /submit/register` | `given_name`, `first_surname`, `second_surname`, `national_id`, `date_of_birth`, `phone`, `email`, `insurer` |
| `POST /submit/book` | `patient_id`, `provider_id`, `location_id`, `appointment_type_id`, `slot`, `policy_id` |
| `POST /submit/reschedule` | `appointment_id`, `provider_id`, `location_id`, `slot`, `policy_id` |
| `POST /submit/cancel` | `appointment_id` |
| `POST /submit/no-action` | `reason` |
| `POST /submit/escalate` | `reason` |

`register` is for a caller the directory does not know: nothing is booked,
the demographics are the answer. A patient who is not on the chart cannot be
booked at all â see
[the scheduling guidelines](clinic-api.md#scheduling-guidelines). Every one of its fields is scored after
[normalization](scoring.md), and `national_id` re-derives its own check
letter â which is what separates a misheard digit from an invented one. A
`national_id` whose letter does not match its digits is `422`.

`book` names a patient already on file by `patient_id`, which comes from
[the directory](clinic-api.md) â never from what the caller said.

`policy_id` is which of the patient's plans the appointment is billed
against. A patient may hold two and only one may cover what they asked for, so
naming it is part of the answer rather than a detail the clinic can infer.
`appointment_id` comes from
[the appointments lookup](clinic-api.md); there is no other source for one.

`slot` must carry an explicit timezone offset. It converts to Europe/Madrid
and must match to the **exact minute**.

### `reason`

Closed vocabulary. The first eleven mirror the clinic's own restrictions
one-for-one, so a rule that bit can always be reported â a test enforces that,
because a rule with no way to say it makes its case unanswerable:

`not_eligible_age` Â· `referral_required` Â· `provider_not_in_network` Â·
`specialty_not_covered` Â· `location_not_covered` Â·
`insurer_referral_required` Â· `allowance_exhausted` Â· `provider_on_leave` Â·
`location_hours` Â· `type_not_offered` Â· `patient_history`

The rest cover endings that are not about a clinic rule:

`no_availability` Â· `clinic_closed` Â· `patient_not_found` Â·
`provider_not_found` Â· `caller_not_authorised` Â· `out_of_scope` Â·
`medical_emergency`

**Response** (`200`): `{"call_id": "â¦", "received_at": "â¦", "record": {"actions": [...]}}`
â every action accepted for this call so far, this one included, in the
shape the record readback returns it: each with an `action`
verb (`REGISTER`, `BOOK`, `RESCHEDULE`, `CANCEL`, `NO_ACTION`, `ESCALATE`)
and its fields; a `REGISTER` nests its fields under `new_patient`.

## 4. Gotchas

- `/submit/*`'s JSON is plain snake_case. camelCase applies only to the
  Twilio-shaped handshake in Â§1.
- Each request is one action. A call that does two things posts twice, to
  the route each thing belongs to.
- The `call_id` you submit is exactly `start.callSid`. Don't mint your own.
- Ids are compared **exactly**. There is nothing to normalize about `PR05`.
- Submitting nothing always fails. See [scoring](rules.md).
- Every field of every route is in the [API reference](api.md); this page is
  the protocol and the deadline, which the schema cannot state.
