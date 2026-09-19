import {
  LATENCY_PENALTY_MS,
  latencyP90,
  type EvaluationResult,
} from "@/lib/mock-data";

/** Plain wording for directors / reception (no engine jargon). */
export type BusinessCase = {
  id: string;
  situation: string;
  assistantDid: string;
  clinicMeaning: string;
  ok: boolean;
  resultLabel: "Correct" | "Review";
  urgencyLabel: string;
};

const OUTCOME_PLAIN: Record<string, string> = {
  EMERGENCY_DIVERTED: "Handed the call to a person for a possible emergency",
  "REFUSED: SPECIALTY_REQUIRES_GP_REFERRAL":
    "Did not book: the specialty requires a GP referral",
  BOOKED_WITHOUT_SECOND_FACTOR:
    "Booked an appointment without confirming the caller’s identity",
  ESCALATED_TO_HUMAN_FALSE_POSITIVE:
    "Passed the call to a person when there was no real emergency",
};

const AUDIT_PLAIN: Record<string, string> = {
  MEDICAL_EMERGENCY:
    "The emergency protocol ran, so the clinic does not delay a critical case.",
  SPECIALTY_REQUIRES_GP_REFERRAL:
    "Appointment policy was respected: the referral path was not skipped.",
  CALLER_NOT_AUTHORISED:
    "Risk of booking under the wrong name or leaking a record.",
  OUT_OF_SCOPE:
    "The request left reception’s scope; the script should be reviewed.",
};

const URGENCY_PLAIN: Record<EvaluationResult["triageLevel"], string> = {
  LEVEL_I: "Highest urgency",
  LEVEL_II: "High priority",
  LEVEL_III: "Medium priority",
  LEVEL_IV: "Routine with rules",
  LEVEL_V: "Light enquiry",
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
    "Review the case with reception to confirm the call."
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
    resultLabel: ok ? "Correct" : "Review",
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
    responseLabel = "No data";
    responseHint = "No evaluations yet.";
  } else if (p90 <= 700) {
    responseLabel = "Snappy";
    responseHint = "Hold time feels fluid.";
  } else if (p90 <= LATENCY_PENALTY_MS) {
    responseLabel = "Acceptable";
    responseHint = "Inside what a caller will tolerate.";
  } else {
    responseLabel = "Slow";
    responseHint = "Callers may hang up or press.";
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
        ? "Automatic reception is answering as expected."
        : failed === 1
          ? "There is 1 case the team should review."
          : `There are ${failed} cases the team should review.`,
  };
}

/** Stored codes stay underscored; the desk shows them with spaces. */
export function displayCode(value: string): string {
  return value.replaceAll("_", " ");
}
