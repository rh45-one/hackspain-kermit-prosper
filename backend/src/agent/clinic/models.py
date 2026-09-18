"""Pydantic models mirroring the Prosper platform API (docs/prosper/openapi.json)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PatientMatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    patient_id: str
    given_name: str
    first_surname: str
    second_surname: str
    national_id: str
    date_of_birth: str
    phone: str
    sex: str
    has_visited_before: bool
    insurer: str
    referrals: list[str] = []
    note: str = ""
    match_score: float = 0.0
    matched_fields: list[str] = []


class AppointmentTypeOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    duration_minutes: int
    new_patient_requirement: str
    guidance: str


class ProviderOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    specialty_id: str
    languages: list[str] = []
    accepted_insurers: list[str] = []
    locations: list[str] = []
    on_leave_until: str | None = None


class Slot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider_id: str
    provider_name: str
    specialty_id: str
    location_id: str
    appointment_type_id: str
    start_time: str
    duration_minutes: int
    payable_with: list[str] = []


class Blocked(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider_id: str
    restriction: str


class AvailabilityResponse(BaseModel):
    """GET /api/v1/availability. `appointment_type` is server-selected: submit its id."""

    model_config = ConfigDict(extra="ignore")

    providers: list[ProviderOut] = []
    appointment_type: AppointmentTypeOut
    slots: list[Slot] = []
    blocked: list[Blocked] = []


# Historical name kept so existing imports keep working.
AvailabilityResult = AvailabilityResponse


class DirectoryResponse(BaseModel):
    """GET /api/v1/directory."""

    model_config = ConfigDict(extra="ignore")

    matches: list[PatientMatch] = []


class AppointmentsResponse(BaseModel):
    """GET /api/v1/patients/{patient_id}/appointments. Only source of an appointment_id."""

    model_config = ConfigDict(extra="ignore")

    appointments: list[Appointment] = []


class Appointment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    appointment_id: str
    patient_id: str
    provider_id: str
    location_id: str
    appointment_type_id: str
    start_time: str
    duration_minutes: int


# ---- catalogue shapes (GET /clinic and friends) ---------------------------
class InsurerRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str


class ClinicDay(BaseModel):
    model_config = ConfigDict(extra="ignore")

    weekday: str
    intervals: list[str] = []


class ClinicLeave(BaseModel):
    model_config = ConfigDict(extra="ignore")

    start: str
    end: str
    reason: str = ""


class ClinicSchedule(BaseModel):
    model_config = ConfigDict(extra="ignore")

    location_id: str
    location_name: str = ""
    days: list[ClinicDay] = []


class ClinicProvider(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    specialty_id: str
    specialty_name: str = ""
    languages: list[str] = []
    appointment_type_names: list[str] = []
    location_names: list[str] = []
    schedules: list[ClinicSchedule] = []
    accepted_insurers: list[InsurerRef] = []
    refused_insurers: list[InsurerRef] = []
    leave: ClinicLeave | None = None


class ClinicSpecialty(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    min_age_months: int = 0
    max_age_months: int | None = None
    referral_required: bool = False
    provider_names: list[str] = []
    covered_by: list[InsurerRef] = []
    not_covered_by: list[InsurerRef] = []


class ClinicAppointmentType(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    duration_minutes: int
    new_patient_requirement: str
    guidance: str = ""
    provider_names: list[str] = []
    # Universal types (first_visit, review) belong to no specialty: null on the wire.
    specialty_id: str | None = None
    specialty_name: str | None = None


class ClinicLocation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    address: str = ""
    latitude: float
    longitude: float
    hours: list[ClinicDay] = []
    provider_names: list[str] = []
    covered_by: list[InsurerRef] = []
    not_covered_by: list[InsurerRef] = []


class ClinicPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    covered_specialty_names: list[str] = []
    uncovered_specialty_names: list[str] = []
    covered_location_names: list[str] = []
    uncovered_location_names: list[str] = []
    accepted_by: list[str] = []
    refused_by: list[str] = []
    holders: int = 0


class ClinicRestriction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    explanation: str = ""


class ClinicCalendar(BaseModel):
    model_config = ConfigDict(extra="ignore")

    starts: str
    ends: str
    max_span_days: int = 14
    slot_minutes: int = 15
    closure_days: list[str] = []
    appointment_count: int = 0


class ClinicCatalogue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    clinic_name: str = ""
    patient_count: int = 0
    calendar: ClinicCalendar
    restrictions: list[ClinicRestriction] = []
    providers: list[ClinicProvider] = []
    specialties: list[ClinicSpecialty] = []
    appointment_types: list[ClinicAppointmentType] = []
    locations: list[ClinicLocation] = []
    plans: list[ClinicPlan] = []
