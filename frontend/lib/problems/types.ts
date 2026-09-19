import type { ActionVerb, OutcomeReason } from "@/lib/types";

export const PROBLEM_IDS = [
  "simple_booking",
  "switchboard",
  "doctor_and_site",
  "the_new_patient",
  "when_exactly",
  "the_rules",
  "no_slot_free",
  "change_and_cancel",
  "third_party",
  "triage",
  "languages",
  "noise",
  "difficult_caller",
  "adversarial",
  "nearest_site",
  "the_questions",
  "second_policy",
  "the_real_call",
] as const;

export type ProblemId = (typeof PROBLEM_IDS)[number];

export type PublicCaseAction = {
  action: ActionVerb;
  reason?: OutcomeReason;
  fields?: Record<string, string>;
};

export type PublicCase = {
  id: string;
  persona: string;
  facts: Record<string, string>;
  goal: string;
  acceptedActions: PublicCaseAction[];
};

export type TriageRoute = {
  complaint: string;
  route: string;
};

export type ProblemBrief = {
  number: number;
  id: ProblemId;
  title: string;
  titleEs: string;
  publicCaseCount: number;
  weight: number | null;
  open: boolean;
  diagnostic: boolean;
  answerVerbs: ActionVerb[];
  summary: string;
  answerNote: string;
  datePhrases?: string[];
  triageRoutes?: TriageRoute[];
  redFlags?: string[];
  noiseTextures?: string[];
  protectedFields?: string[];
  burstSize?: number;
  publicCases: PublicCase[];
};
