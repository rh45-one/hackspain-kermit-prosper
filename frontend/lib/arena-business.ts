import {
  LATENCY_PENALTY_MS,
  latencyP90,
  type EvaluationResult,
} from "@/lib/mock-data";

/** Texto claro para dirección / recepción (sin jerga de motor). */
export type BusinessCase = {
  id: string;
  situation: string;
  assistantDid: string;
  clinicMeaning: string;
  ok: boolean;
  resultLabel: "Correcto" | "A revisar";
  urgencyLabel: string;
};

const OUTCOME_PLAIN: Record<string, string> = {
  EMERGENCY_DIVERTED: "Derivó la llamada a personal humano por posible emergencia",
  "REFUSED: SPECIALTY_REQUIRES_GP_REFERRAL":
    "No reservó: la especialidad exige volante del médico de cabecera",
  BOOKED_WITHOUT_SECOND_FACTOR:
    "Reservó una cita sin confirmar bien la identidad del llamante",
  ESCALATED_TO_HUMAN_FALSE_POSITIVE:
    "Pasó la llamada a una persona sin que hubiera una urgencia real",
};

const AUDIT_PLAIN: Record<string, string> = {
  MEDICAL_EMERGENCY:
    "El protocolo de urgencia se aplicó y la clínica evita demorar un caso crítico.",
  SPECIALTY_REQUIRES_GP_REFERRAL:
    "Se respetó la política de citas: no se salta el circuito de derivación.",
  CALLER_NOT_AUTHORISED:
    "Hay riesgo de reserva a nombre equivocado o acceso indebido a datos.",
  OUT_OF_SCOPE:
    "La petición salió del alcance de recepción; conviene revisar el guion.",
};

const URGENCY_PLAIN: Record<EvaluationResult["triageLevel"], string> = {
  LEVEL_I: "Urgencia máxima",
  LEVEL_II: "Alta prioridad",
  LEVEL_III: "Prioridad media",
  LEVEL_IV: "Rutina con reglas",
  LEVEL_V: "Consulta ligera",
};

function plainOutcome(outcome: string): string {
  return (
    OUTCOME_PLAIN[outcome] ??
    outcome
      .replaceAll("_", " ")
      .replaceAll(":", " · ")
      .toLowerCase()
      .replace(/^\w/, (c) => c.toUpperCase())
  );
}

function plainAudit(code: string): string {
  return (
    AUDIT_PLAIN[code] ??
    "Revisar el caso con el equipo de recepción para confirmar el criterio."
  );
}

export function toBusinessCase(result: EvaluationResult): BusinessCase {
  const ok = result.verdict === "PASSED";
  return {
    id: result.id,
    situation: result.personaScenario,
    assistantDid: plainOutcome(result.actionOutcome),
    clinicMeaning: plainAudit(result.auditCode),
    ok,
    resultLabel: ok ? "Correcto" : "A revisar",
    urgencyLabel: URGENCY_PLAIN[result.triageLevel],
  };
}

export function businessSummary(results: EvaluationResult[]) {
  const total = results.length;
  const passed = results.filter((r) => r.verdict === "PASSED").length;
  const failed = total - passed;
  const passRate = total === 0 ? 0 : Math.round((passed / total) * 100);
  const safeRules = results.filter((r) => r.constraintViolationRate === 0).length;
  const rulesOkRate = total === 0 ? 0 : Math.round((safeRules / total) * 100);
  const p90 = latencyP90(results);

  let responseLabel: string;
  let responseHint: string;
  if (p90 === 0) {
    responseLabel = "Sin datos";
    responseHint = "Aún no hay evaluaciones.";
  } else if (p90 <= 700) {
    responseLabel = "Ágil";
    responseHint = "La espera en línea se percibe fluida.";
  } else if (p90 <= LATENCY_PENALTY_MS) {
    responseLabel = "Aceptable";
    responseHint = "Dentro del margen que tolera un llamante.";
  } else {
    responseLabel = "Lenta";
    responseHint = "Los llamantes pueden cortar o insistir.";
  }

  return {
    total,
    passed,
    failed,
    passRate,
    rulesOkRate,
    responseLabel,
    responseHint,
    headline:
      failed === 0
        ? "La recepción automática está respondiendo como se espera."
        : failed === 1
          ? "Hay 1 caso que conviene revisar con el equipo."
          : `Hay ${failed} casos que conviene revisar con el equipo.`,
  };
}
