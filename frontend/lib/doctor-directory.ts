/**
 * Staff directory shapes aligned with Prosper Clínica Arenal catalogue
 * (`GET /api/v1/providers` / `ClinicProviderResponse`).
 *
 * Local evaluator/backend fixtures are a reduced seed ("Clínica Arenal (local)")
 * and intentionally diverge — this UI mock follows published Prosper rules in
 * docs/prosper/clinic.md. Wire to live `/providers` for the official 12-person
 * roster (given names / ids may differ from this provisional list).
 */

export type DoctorDutyStatus = "active" | "off_duty" | "absent";

export type DoctorLeave = {
  start: string;
  end: string;
  reason: string;
};

export type DirectoryDoctor = {
  id: string;
  name: string;
  specialtyId: string;
  specialtyName: string;
  locationNames: string[];
  languages: string[];
  status: DoctorDutyStatus;
  leave: DoctorLeave | null;
  refusedInsurers?: string[];
};

export const DOCTOR_STATUS_META: Record<
  DoctorDutyStatus,
  { label: string; className: string }
> = {
  active: {
    label: "Active",
    className: "border-transparent bg-emerald-100 text-emerald-800",
  },
  off_duty: {
    label: "Off-Duty",
    className: "border-transparent bg-slate-100 text-slate-800",
  },
  absent: {
    label: "Absent / On Leave",
    className: "border-transparent bg-red-100 text-red-800",
  },
};

/** Prosper specialty ids / names (availability?specialty_id=). */
export const PROSPER_SPECIALTIES = [
  { id: "general", name: "General practice" },
  { id: "paediatrics", name: "Paediatrics" },
  { id: "dermatology", name: "Dermatology" },
  { id: "orthopaedics", name: "Orthopaedics" },
  { id: "physiotherapy", name: "Physiotherapy" },
  { id: "gynaecology", name: "Gynaecology" },
] as const;

/**
 * Provisional roster for the Staff Directory.
 * Includes every named Prosper trap (Requena leave, Sáez/Sáenz, Iglesias/Iglesia,
 * Cid title, Iglesias≠DKV → Vilar). Official given names/ids come from `/providers`.
 */
export const MOCK_DIRECTORY_DOCTORS: DirectoryDoctor[] = [
  {
    id: "PR01",
    name: "Dra. Ana Sáez",
    specialtyId: "general",
    specialtyName: "General practice",
    locationNames: ["Centro", "Norte"],
    languages: ["español", "catalán"],
    status: "active",
    leave: null,
  },
  {
    id: "PR08",
    name: "Dra. Sáenz",
    specialtyId: "paediatrics",
    specialtyName: "Paediatrics",
    locationNames: ["Norte"],
    languages: ["español"],
    status: "active",
    leave: null,
  },
  {
    id: "PR02",
    name: "Dra. Marta Iglesias",
    specialtyId: "dermatology",
    specialtyName: "Dermatology",
    locationNames: ["Centro"],
    languages: ["español"],
    status: "active",
    leave: null,
    refusedInsurers: ["dkv"],
  },
  {
    id: "PR09",
    name: "Dr. Vilar",
    specialtyId: "dermatology",
    specialtyName: "Dermatology",
    locationNames: ["Centro"],
    languages: ["español"],
    status: "active",
    leave: null,
  },
  {
    id: "PR07",
    name: "Dr. Iván Iglesia",
    specialtyId: "orthopaedics",
    specialtyName: "Orthopaedics",
    locationNames: ["Norte"],
    languages: ["español"],
    status: "active",
    leave: null,
  },
  {
    id: "PR03",
    name: "D. Álvaro Cid",
    specialtyId: "physiotherapy",
    specialtyName: "Physiotherapy",
    locationNames: ["Sur"],
    languages: ["español", "catalán", "galego"],
    status: "off_duty",
    leave: null,
  },
  {
    id: "PR05",
    name: "Dr. Pablo Requena",
    specialtyId: "general",
    specialtyName: "General practice",
    locationNames: ["Sur", "Norte"],
    languages: ["español"],
    status: "absent",
    leave: {
      start: "2026-09-14",
      end: "2026-09-30",
      reason: "sick leave",
    },
  },
  {
    id: "PR10",
    name: "Dra. Ortiz",
    specialtyId: "general",
    specialtyName: "General practice",
    locationNames: ["Centro"],
    languages: ["español"],
    status: "active",
    leave: null,
  },
  {
    id: "PR06",
    name: "Dra. Carmen Fuentes",
    specialtyId: "gynaecology",
    specialtyName: "Gynaecology",
    locationNames: ["Centro"],
    languages: ["español"],
    status: "active",
    leave: null,
  },
  {
    id: "PR04",
    name: "Dra. Lucía Navarro",
    specialtyId: "paediatrics",
    specialtyName: "Paediatrics",
    locationNames: ["Norte"],
    languages: ["español"],
    status: "off_duty",
    leave: null,
  },
];
