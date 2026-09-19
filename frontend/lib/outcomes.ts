import type {
  ActionVerb,
  Appointment,
  OutcomeReason,
  Patient,
  ReceptionOutcome,
  ReceptionTriage,
} from "@/lib/types";

export const REASON_LABELS: Record<OutcomeReason, string> = {
  not_eligible_age: "Age outside the window",
  referral_required: "Referral required",
  provider_not_in_network: "Clinician out of network",
  specialty_not_covered: "Specialty not covered",
  location_not_covered: "Site not covered",
  insurer_referral_required: "Referral required by the plan",
  allowance_exhausted: "Allowance exhausted",
  provider_on_leave: "Clinician on leave",
  location_hours: "Outside site hours",
  type_not_offered: "Type not offered",
  patient_history: "Patient history",
  no_availability: "No slot",
  clinic_closed: "Clinic closed",
  patient_not_found: "Patient not found",
  provider_not_found: "Clinician not found",
  caller_not_authorised: "Caller not authorised",
  out_of_scope: "Out of scope",
  medical_emergency: "Medical emergency",
};

export function outcomeFromAction(action: ActionVerb): ReceptionOutcome {
  switch (action) {
    case "CANCEL":
      return "CANCELLED";
    case "NO_ACTION":
      return "REFUSED";
    case "ESCALATE":
      return "DIVERTED";
    default:
      return "BOOKED";
  }
}

export const OUTCOME_STYLES: Record<
  ReceptionOutcome,
  { label: string; className: string; chip: string }
> = {
  BOOKED: {
    label: "Booked",
    className: "border-0 bg-ivory text-brass",
    chip: "border-0 bg-ivory text-graphite",
  },
  CANCELLED: {
    label: "Cancelled",
    className: "border-0 bg-mist text-graphite",
    chip: "border-0 bg-mist text-graphite",
  },
  REFUSED: {
    label: "Could not book",
    className: "border-0 bg-ash text-quiet",
    chip: "border-0 bg-ash text-steel",
  },
  DIVERTED: {
    label: "Handed to a person",
    className: "border-0 bg-ivory text-ember-orange",
    chip: "border-0 bg-ivory text-ember-orange",
  },
};

export function fullName(
  patient: Pick<Patient, "given_name" | "first_surname" | "second_surname">,
): string {
  return [patient.given_name, patient.first_surname, patient.second_surname]
    .filter(Boolean)
    .join(" ");
}

export function triageFromAppointments(
  appointments: Appointment[],
): ReceptionTriage {
  const latest = [...appointments].sort((a, b) =>
    a.start_time < b.start_time ? 1 : -1,
  )[0];
  if (!latest) {
    return "rutinario";
  }
  if (latest.action === "ESCALATE" && latest.reason === "medical_emergency") {
    return "urgente";
  }
  if (latest.action === "ESCALATE") {
    return "desviado";
  }
  if (latest.action === "NO_ACTION") {
    return "vigilancia";
  }
  return "rutinario";
}

export const TRIAGE_STYLES: Record<
  ReceptionTriage,
  { label: string; className: string }
> = {
  rutinario: {
    label: "Routine",
    className: "border-0 bg-ivory text-brass",
  },
  vigilancia: {
    label: "Watch",
    className: "border-0 bg-ash text-steel",
  },
  desviado: {
    label: "Diverted",
    className: "border-0 bg-ivory text-ember-orange",
  },
  urgente: {
    label: "Urgent",
    className: "border-0 bg-graphite text-canvas-white",
  },
};
