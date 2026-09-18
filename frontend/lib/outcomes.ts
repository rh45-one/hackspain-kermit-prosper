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
    className: "bg-emerald-100 text-emerald-800 border-emerald-200",
    chip: "bg-emerald-50 border-emerald-200 text-emerald-900",
  },
  CANCELLED: {
    label: "CANCELLED",
    className: "bg-red-100 text-red-800 border-red-200",
    chip: "bg-red-50 border-red-200 text-red-900",
  },
  REFUSED: {
    label: "REFUSED",
    className: "bg-slate-200 text-slate-700 border-slate-300",
    chip: "bg-slate-100 border-slate-300 text-slate-800",
  },
  DIVERTED: {
    label: "DIVERTED",
    className: "bg-orange-100 text-orange-800 border-orange-200",
    chip: "bg-orange-50 border-orange-200 text-orange-900",
  },
};

export function fullName(patient: Pick<
  Patient,
  "given_name" | "first_surname" | "second_surname"
>): string {
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
    className: "bg-emerald-100 text-emerald-800 border-emerald-200",
  },
  vigilancia: {
    label: "Vigilancia",
    className: "bg-amber-100 text-amber-900 border-amber-200",
  },
  desviado: {
    label: "Desviado",
    className: "bg-orange-100 text-orange-800 border-orange-200",
  },
  urgente: {
    label: "Urgente",
    className: "bg-red-100 text-red-800 border-red-200",
  },
};
