export const CLINIC_TZ = "Europe/Madrid";
export const CALL_CAPACITY = 10;

export type ActionVerb =
  | "REGISTER"
  | "BOOK"
  | "RESCHEDULE"
  | "CANCEL"
  | "NO_ACTION"
  | "ESCALATE";

export type ReceptionOutcome = "BOOKED" | "CANCELLED" | "REFUSED" | "DIVERTED";

export type OutcomeReason =
  | "not_eligible_age"
  | "referral_required"
  | "provider_not_in_network"
  | "specialty_not_covered"
  | "location_not_covered"
  | "insurer_referral_required"
  | "allowance_exhausted"
  | "provider_on_leave"
  | "location_hours"
  | "type_not_offered"
  | "patient_history"
  | "no_availability"
  | "clinic_closed"
  | "patient_not_found"
  | "provider_not_found"
  | "caller_not_authorised"
  | "out_of_scope"
  | "medical_emergency";

export type ReceptionTriage = "rutinario" | "vigilancia" | "desviado" | "urgente";

export type TurnState = "listening" | "speaking" | "barge-in";

export type TranscriptRole = "agent" | "caller";

export type TranscriptLine = {
  role: TranscriptRole;
  text: string;
  entities?: Partial<LiveEntities>;
  turn?: TurnState;
};

export type LiveEntities = {
  name: string;
  nationalId: string;
  appointmentType: string;
};

export type LiveCall = {
  callId: string;
  socketId: string;
  virtualPhone: string;
  status: "active" | "ended" | "unknown";
  turn: TurnState;
  startedAt: string;
  transcript: TranscriptLine[];
  script: TranscriptLine[];
  entities: Partial<LiveEntities>;
  outcome?: ReceptionOutcome;
  action?: ActionVerb;
  reason?: OutcomeReason;
  diagnostic?: {
    empty_action_reason?: string | null;
    submissions_succeeded?: number;
    submissions_failed?: number;
    fallback_action_added?: boolean;
  } | null;
};

/** Local FrontDesk operator state. Not returned by the live backend. */
export type CallControlState = {
  heldByOperator: boolean;
  automationPaused: boolean;
};

export const DEFAULT_CALL_CONTROL: CallControlState = {
  heldByOperator: false,
  automationPaused: false,
};

export type Patient = {
  patient_id: string;
  given_name: string;
  first_surname: string;
  second_surname: string;
  national_id: string;
  date_of_birth: string;
  phone: string;
  sex: string;
  has_visited_before: boolean;
  insurer: string;
  referrals: string[];
  note: string;
};

export type Appointment = {
  appointment_id: string;
  patient_id: string;
  provider_id: string;
  provider_name: string;
  location_id: string;
  location_name: string;
  appointment_type_id: string;
  appointment_type_name: string;
  start_time: string;
  duration_minutes: number;
  action: ActionVerb;
  reason?: OutcomeReason;
};

export type KnowledgeKind = "csv" | "sql" | "api";

export type KnowledgeSource = {
  id: string;
  kind: KnowledgeKind;
  label: string;
  detail: string;
  syncedAt: string | null;
};

export type VoicePipeline = "elevenlabs" | "cartesia";

export type AgentSettings = {
  tunnelUrl: string;
  authHeaders: string;
  voicePipeline: VoicePipeline;
  behaviourPrompt: string;
  knowledgeSources: KnowledgeSource[];
};
