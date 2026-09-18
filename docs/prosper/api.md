# API reference

Summary of the live schema at https://hackspain.getprosperapp.com/api/redoc (spec: `/api/openapi.json`). OpenAPI 3.1.0 — "Prosper — platform API".

## Auth

API key in the `X-Api-Key` header (`TeamApiKey` security scheme). Every route except `/api/v1/health` requires it. Missing, invalid or revoked keys return `403 {"detail":"Invalid API key"}`.

## Status

| Method | Path | Summary |
| --- | --- | --- |
| GET | `/api/v1/health` | Health. No auth. |

## Submission

All take JSON (snake_case) and return `SubmitResponse`. Errors: `404` no call with this `call_id` for your key, `410` submission window closed, `422` validation error.

| Method | Path | Summary |
| --- | --- | --- |
| POST | `/api/v1/submit/register` | Register Patient — put a caller not on file into the record. |
| POST | `/api/v1/submit/book` | Book Appointment — book a slot for a patient already on file. |
| POST | `/api/v1/submit/reschedule` | Reschedule Appointment — move an existing appointment. |
| POST | `/api/v1/submit/cancel` | Cancel Appointment — cancel an existing appointment (two cancels = two requests). |
| POST | `/api/v1/submit/no-action` | No Action — end the call with no write, carrying the reason. |
| POST | `/api/v1/submit/escalate` | Escalate to Human — hand the call to a human, carrying the reason. |
| GET | `/api/v1/submissions?limit=50` | List Submissions. `limit` 1–200, default 50. Returns `RecordsResponse`. |

### Submit bodies (besides `call_id`, required everywhere)

- **register**: `given_name`, `first_surname`, `second_surname`, `national_id`, `date_of_birth`, `phone`, `email`, `insurer`
- **book**: `patient_id`, `provider_id`, `location_id`, `appointment_type_id`, `slot`, `policy_id`
- **reschedule**: `appointment_id`, `provider_id`, `location_id`, `slot`, `policy_id`
- **cancel**: `appointment_id`
- **no-action**: `reason`
- **escalate**: `reason`

`slot` is a date-time with an explicit timezone offset, compared in Europe/Madrid to the exact minute.

## Clinic

All require `X-Api-Key`.

| Method | Path | Summary |
| --- | --- | --- |
| GET | `/api/v1/directory` | Search Patient. Query: `name`, `national_id`, `phone`, `date_of_birth`. Returns `DirectoryResponse`. |
| GET | `/api/v1/patients/{patient_id}/appointments` | List Patient Appointments. Query: `when` (`AppointmentWindow`). Returns `AppointmentsResponse`. |
| GET | `/api/v1/availability` | Search Availability. Query: `date_from`, `date_to` (required), `provider_id`, `specialty_id`, `location_id`, `patient_id`, `insurer` (repeatable `Insurer`). Returns `AvailabilityResponse`. |
| GET | `/api/v1/clinic` | Clinic Overview — whole catalogue, bookable window, restrictions, providers, specialties, types, locations, plans. Returns `ClinicResponse`. |
| GET | `/api/v1/providers` | List Providers. Returns `ProvidersResponse`. |
| GET | `/api/v1/locations` | List Locations. Returns `LocationsResponse`. |
| GET | `/api/v1/specialties` | List Specialties. Returns `SpecialtiesResponse`. |
| GET | `/api/v1/appointment-types` | List Appointment Types. Returns `AppointmentTypesResponse`. |
| GET | `/api/v1/insurance-plans` | List Insurance Plans. Returns `InsurancePlansResponse`. |

## Enums

- **Insurer**: `sanitas`, `adeslas`, `dkv`, `asisa`, `mapfre`, `caser`, `cigna`, `axa`, `nueva_mutua`, `privado`
- **AppointmentWindow**: `upcoming`, `past`, `all`
- **OutcomeReason**: `not_eligible_age`, `referral_required`, `provider_not_in_network`, `specialty_not_covered`, `location_not_covered`, `insurer_referral_required`, `allowance_exhausted`, `provider_on_leave`, `location_hours`, `type_not_offered`, `patient_history`, `no_availability`, `clinic_closed`, `patient_not_found`, `provider_not_found`, `caller_not_authorised`, `out_of_scope`, `medical_emergency`
- **Action verbs** (discriminator `action`): `REGISTER`, `BOOK`, `RESCHEDULE`, `CANCEL`, `NO_ACTION`, `ESCALATE`

## Key schemas

- **SubmitResponse**: `call_id`, `received_at` (UTC), `record` (`SubmittedOutcome`). The call's record so far, this action included.
- **SubmittedOutcome**: `actions[]` — one of `RegisterAction`, `BookAction`, `RescheduleAction`, `CancelAction`, `NoAction`, `EscalateAction`, each carrying its verb and fields.
- **DirectoryResponse**: `matches[]` of **PatientMatchOut**: `patient_id`, names, `national_id`, `date_of_birth`, `phone`, `sex`, `has_visited_before`, `insurer`, `referrals[]`, `note`, `match_score`, `matched_fields[]`.
- **AvailabilityResponse**: `providers[]` (`ProviderOut`), `appointment_type` (`AppointmentTypeOut`), `slots[]` (`SlotOut`), `blocked[]` (`BlockedOut`).
- **SlotOut**: `provider_id`, `provider_name`, `specialty_id`, `location_id`, `appointment_type_id`, `start_time`, `duration_minutes`, `payable_with[]`.
- **BlockedOut**: `provider_id`, `restriction` — the standing rule that stopped that provider.
- **AppointmentsResponse**: `appointments[]` of **AppointmentOut**: `appointment_id`, `patient_id`, `provider_id`, `location_id`, `appointment_type_id`, `start_time`, `duration_minutes`.
- **ClinicResponse**: `clinic_name`, `patient_count`, `calendar`, `restrictions[]`, `providers[]`, `specialties[]`, `appointment_types[]`, `locations[]`, `plans[]`.
- **ClinicCalendarResponse**: `starts`, `ends`, `max_span_days`, `slot_minutes`, `closure_days[]`, `appointment_count`.
- **ClinicProviderResponse**: `id`, `name`, `specialty_id/name`, `languages[]`, `appointment_type_names[]`, `location_names[]`, `schedules[]`, `accepted_insurers[]`, `refused_insurers[]`, `leave` (nullable).
- **ClinicSpecialtyResponse**: `id`, `name`, `min_age_months`, `max_age_months` (nullable), `referral_required`, `provider_names[]`, `covered_by[]`, `not_covered_by[]`.
- **ClinicAppointmentTypeResponse**: `id`, `name`, `duration_minutes`, `new_patient_requirement`, `guidance`, `provider_names[]`, `specialty_id/name` (nullable).
- **ClinicLocationResponse**: `id`, `name`, `address`, `latitude`, `longitude`, `hours[]`, `provider_names[]`, `covered_by[]`, `not_covered_by[]`.
- **ClinicPlanResponse**: `id`, `name`, `covered_specialty_names[]`, `uncovered_specialty_names[]`, `covered_location_names[]`, `uncovered_location_names[]`, `accepted_by[]`, `refused_by[]`, `holders`.
- **RecordsResponse**: `submissions[]` of **RecordResponse** (`call_id`, `record`, `received_at`).
- **RegisterAction**: `action: REGISTER`, `new_patient` (`NewPatient`).
- **NewPatient**: `given_name`, `first_surname`, `second_surname`, `national_id`, `date_of_birth`, `phone`, `email`, `insurer`.
- **BookAction**: `action: BOOK`, `patient_id`, `provider_id`, `location_id`, `appointment_type_id`, `slot`, `policy_id`.
- **RescheduleAction**: `action: RESCHEDULE`, `appointment_id`, `provider_id`, `location_id`, `slot`, `policy_id`.
- **CancelAction**: `action: CANCEL`, `appointment_id`.
- **NoAction**: `action: NO_ACTION`, `reason`. **EscalateAction**: `action: ESCALATE`, `reason`.
