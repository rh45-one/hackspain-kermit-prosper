import type {
  ActionVerb,
  Appointment,
  OutcomeReason,
  Patient,
  ReceptionOutcome,
  ReceptionTriage,
} from "@/lib/types";

export const REASON_LABELS: Record<OutcomeReason, string> = {
  not_eligible_age: "Edad fuera de ventana",
  referral_required: "Hace falta volante",
  provider_not_in_network: "Profesional fuera de red",
  specialty_not_covered: "Especialidad no cubierta",
  location_not_covered: "Centro no cubierto",
  insurer_referral_required: "Volante exigido por la póliza",
  allowance_exhausted: "Cupo agotado",
  provider_on_leave: "Profesional de baja",
  location_hours: "Fuera de horario del centro",
  type_not_offered: "Tipo no ofertado",
  patient_history: "Historial del paciente",
  no_availability: "Sin hueco",
  clinic_closed: "Clínica cerrada",
  patient_not_found: "Paciente no encontrado",
  provider_not_found: "Profesional no encontrado",
  caller_not_authorised: "Llamante no autorizado",
  out_of_scope: "Fuera de alcance",
  medical_emergency: "Urgencia médica",
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
    label: "BOOKED",
    className: "border-0 bg-ivory text-brass",
    chip: "border-0 bg-ivory text-graphite",
  },
  CANCELLED: {
    label: "CANCELLED",
    className: "border-0 bg-mist text-graphite",
    chip: "border-0 bg-mist text-graphite",
  },
  REFUSED: {
    label: "REFUSED",
    className: "border-0 bg-ash text-quiet",
    chip: "border-0 bg-ash text-steel",
  },
  DIVERTED: {
    label: "DIVERTED",
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
    label: "Rutinario",
    className: "border-0 bg-ivory text-brass",
  },
  vigilancia: {
    label: "Vigilancia",
    className: "border-0 bg-ash text-steel",
  },
  desviado: {
    label: "Desviado",
    className: "border-0 bg-ivory text-ember-orange",
  },
  urgente: {
    label: "Urgente",
    className: "border-0 bg-graphite text-canvas-white",
  },
};
