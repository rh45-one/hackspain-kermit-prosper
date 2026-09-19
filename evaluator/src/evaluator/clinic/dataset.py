"""Local clinic dataset: load a versioned JSON snapshot and answer the
Prosper read API from it.

The dataset mirrors the real API response shapes (see docs/prosper/api.md).
Availability slots are generated deterministically from provider schedules
and the calendar, minus the provider's booked appointments - the clinic is
read-only, so two calls may legitimately "book" the same slot.

A dataset can be written by hand; the catalogue fields mirror the
platform's `/api/v1/clinic` response so a real pull can be transcribed
into it when the team key is available.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")

_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


class Dataset:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.meta = raw.get("meta", {})
        self.calendar = raw["calendar"]
        self.locations = raw["locations"]
        self.specialties = raw["specialties"]
        self.appointment_types = raw["appointment_types"]
        self.plans = raw["plans"]
        self.providers = raw["providers"]
        self.patients = raw["patients"]
        self.appointments = raw.get("appointments", [])
        self.restrictions = raw.get("restrictions", [])

        self.providers_by_id = {p["id"]: p for p in self.providers}
        self.patients_by_id = {p["patient_id"]: p for p in self.patients}
        self.locations_by_id = {l["id"]: l for l in self.locations}
        self.specialties_by_id = {s["id"]: s for s in self.specialties}
        self.types_by_id = {t["id"]: t for t in self.appointment_types}
        self.plans_by_id = {p["id"]: p for p in self.plans}

    @classmethod
    def load(cls, path: str | Path) -> Dataset:
        with open(path, encoding="utf-8") as fh:
            return cls(json.load(fh))

    # --- catalogue endpoints --------------------------------------------------

    def clinic_response(self) -> dict[str, Any]:
        return {
            "clinic_name": self.meta.get("clinic_name", "Clínica Arenal (local)"),
            "patient_count": len(self.patients),
            "calendar": {**self.calendar, "appointment_count": len(self.appointments)},
            "restrictions": self.restrictions,
            "providers": [self._provider_out(p) for p in self.providers],
            "specialties": [self._specialty_out(s) for s in self.specialties],
            "appointment_types": [self._type_out(t) for t in self.appointment_types],
            "locations": [self._location_out(l) for l in self.locations],
            "plans": [self._plan_out(p) for p in self.plans],
        }

    def providers_response(self) -> dict[str, Any]:
        return {"providers": [self._provider_out(p) for p in self.providers]}

    def locations_response(self) -> dict[str, Any]:
        return {"locations": [self._location_out(l) for l in self.locations]}

    def specialties_response(self) -> dict[str, Any]:
        return {"specialties": [self._specialty_out(s) for s in self.specialties]}

    def appointment_types_response(self) -> dict[str, Any]:
        return {"appointment_types": [self._type_out(t) for t in self.appointment_types]}

    def insurance_plans_response(self) -> dict[str, Any]:
        return {"plans": [self._plan_out(p) for p in self.plans]}

    def _plan_ref(self, plan_id: str) -> dict[str, str]:
        plan = self.plans_by_id[plan_id]
        return {"id": plan["id"], "name": plan["name"]}

    def _provider_out(self, p: dict[str, Any]) -> dict[str, Any]:
        spec = self.specialties_by_id.get(p["specialty_id"], {})
        return {
            "id": p["id"],
            "name": p["name"],
            "specialty_id": p["specialty_id"],
            "specialty_name": spec.get("name", p["specialty_id"]),
            "languages": p.get("languages", ["español"]),
            "appointment_type_names": [
                self.types_by_id[t]["name"] for t in p.get("appointment_type_ids", [])
            ],
            "location_names": [
                self.locations_by_id[l]["name"] for l in p.get("location_ids", [])
            ],
            "schedules": [
                {
                    "location_id": s["location_id"],
                    "location_name": self.locations_by_id[s["location_id"]]["name"],
                    "days": s["days"],
                }
                for s in p.get("schedules", [])
            ],
            "accepted_insurers": [
                self._plan_ref(i) for i in p.get("accepted_insurers", [])
            ],
            "refused_insurers": [
                self._plan_ref(i) for i in p.get("refused_insurers", [])
            ],
            "leave": p.get("leave"),
        }

    def _location_out(self, l: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": l["id"],
            "name": l["name"],
            "address": l.get("address", ""),
            "latitude": l.get("latitude"),
            "longitude": l.get("longitude"),
            "hours": l.get("hours", []),
            "provider_names": [
                p["name"] for p in self.providers if l["id"] in p.get("location_ids", [])
            ],
            "covered_by": [self._plan_ref(i) for i in l.get("covered_by", [])],
            "not_covered_by": [self._plan_ref(i) for i in l.get("not_covered_by", [])],
        }

    def _specialty_out(self, s: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": s["id"],
            "name": s["name"],
            "min_age_months": s.get("min_age_months", 0),
            "max_age_months": s.get("max_age_months"),
            "referral_required": s.get("referral_required", False),
            "provider_names": [
                p["name"] for p in self.providers if p["specialty_id"] == s["id"]
            ],
            "covered_by": [self._plan_ref(i) for i in s.get("covered_by", [])],
            "not_covered_by": [self._plan_ref(i) for i in s.get("not_covered_by", [])],
        }

    def _type_out(self, t: dict[str, Any]) -> dict[str, Any]:
        spec = self.specialties_by_id.get(t.get("specialty_id") or "", {})
        return {
            "id": t["id"],
            "name": t["name"],
            "duration_minutes": t["duration_minutes"],
            "new_patient_requirement": t.get("new_patient_requirement", "none"),
            "guidance": t.get("guidance", ""),
            "provider_names": [
                p["name"]
                for p in self.providers
                if t["id"] in p.get("appointment_type_ids", [])
            ],
            "specialty_id": t.get("specialty_id"),
            "specialty_name": spec.get("name"),
        }

    def _plan_out(self, p: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": p["id"],
            "name": p["name"],
            "covered_specialty_names": [
                self.specialties_by_id[s]["name"] for s in p.get("covered_specialties", [])
            ],
            "uncovered_specialty_names": [
                self.specialties_by_id[s]["name"] for s in p.get("uncovered_specialties", [])
            ],
            "covered_location_names": [
                self.locations_by_id[l]["name"] for l in p.get("covered_locations", [])
            ],
            "uncovered_location_names": [
                self.locations_by_id[l]["name"] for l in p.get("uncovered_locations", [])
            ],
            "accepted_by": [
                pr["name"]
                for pr in self.providers
                if p["id"] in pr.get("accepted_insurers", [])
            ],
            "refused_by": [
                pr["name"]
                for pr in self.providers
                if p["id"] in pr.get("refused_insurers", [])
            ],
            "holders": sum(1 for pt in self.patients if pt.get("insurer") == p["id"]),
        }

    # --- directory ------------------------------------------------------------

    def directory(self, query: dict[str, str]) -> dict[str, Any]:
        """Search patients. An exact field that does not match EXCLUDES the
        patient (clinic.md); name matches on folded-token overlap."""
        from evaluator.normalize import (
            norm_national_id,
            norm_person_name,
            norm_phone,
        )

        q_name = norm_person_name(query.get("name", "") or "")
        q_nid = norm_national_id(query["national_id"]) if query.get("national_id") else None
        q_phone = norm_phone(query["phone"]) if query.get("phone") else None
        q_dob = query.get("date_of_birth")

        matches = []
        for p in self.patients:
            if q_nid and norm_national_id(p["national_id"]) != q_nid:
                continue
            if q_phone and norm_phone(p["phone"]) != q_phone:
                continue
            if q_dob and p["date_of_birth"] != q_dob:
                continue
            matched_fields: list[str] = []
            score = 0.0
            if q_name:
                full = norm_person_name(
                    f"{p['given_name']} {p['first_surname']} {p.get('second_surname', '')}"
                )
                tokens = set(full.split())
                want = set(q_name.split())
                # Every spoken token must appear in the record - otherwise a
                # surname shared with a relative would return the caller's
                # child on a name search.
                if not want <= tokens:
                    continue
                matched_fields.append("name")
                score += len(want) / len(tokens)
            if q_nid:
                matched_fields.append("national_id")
                score += 1.0
            if q_phone:
                matched_fields.append("phone")
                score += 1.0
            if q_dob:
                matched_fields.append("date_of_birth")
                score += 1.0
            matches.append({**p, "match_score": round(score, 2), "matched_fields": matched_fields})
        matches.sort(key=lambda m: -m["match_score"])
        return {"matches": matches}

    # --- appointments ---------------------------------------------------------

    def patient_appointments(self, patient_id: str, when: str = "upcoming") -> dict[str, Any]:
        if patient_id not in self.patients_by_id:
            return {"appointments": []}
        today = datetime.now(MADRID).date()
        items = []
        for a in self.appointments:
            if a["patient_id"] != patient_id:
                continue
            start = datetime.fromisoformat(a["start_time"]).date()
            if when == "upcoming" and start < today:
                continue
            if when == "past" and start >= today:
                continue
            items.append(a)
        items.sort(key=lambda a: a["start_time"])
        return {"appointments": items}

    # --- availability ---------------------------------------------------------

    def availability(
        self,
        date_from: date,
        date_to: date,
        provider_id: str | None = None,
        specialty_id: str | None = None,
        location_id: str | None = None,
        patient_id: str | None = None,
        insurers: list[str] | None = None,
        appointment_type_id: str | None = None,
    ) -> dict[str, Any]:
        """Generate slots from provider schedules; name the standing rule
        that blocked an otherwise-matching provider.

        Local approximation of the real endpoint's restriction metadata:
        `blocked` fires on provider leave and on insurers the provider
        refuses. Referral/age checks are the agent's job, as in the real
        clinic.
        """
        cal_start = date.fromisoformat(self.calendar["starts"])
        cal_end = date.fromisoformat(self.calendar["ends"])
        if date_from < cal_start or date_to > cal_end:
            raise ValueError("outside the bookable calendar")
        if (date_to - date_from).days > self.calendar.get("max_span_days", 14):
            raise ValueError("date span exceeds max_span_days")
        if date_to < date_from:
            raise ValueError("date_to before date_from")

        closures = {date.fromisoformat(d) for d in self.calendar.get("closure_days", [])}
        patient = self.patients_by_id.get(patient_id) if patient_id else None
        effective_insurers = insurers or ([patient["insurer"]] if patient else [])

        slots: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []

        for p in self.providers:
            if provider_id and p["id"] != provider_id:
                continue
            if specialty_id and p["specialty_id"] != specialty_id:
                continue
            if location_id and location_id not in p.get("location_ids", []):
                continue

            # Standing rules that stop the provider outright.
            leave = p.get("leave")
            if leave:
                ls, le = date.fromisoformat(leave["start"]), date.fromisoformat(leave["end"])
                if ls <= date_to and le >= date_from:
                    blocked.append({"provider_id": p["id"], "restriction": "provider_on_leave"})
                    continue
            if effective_insurers and all(
                i in p.get("refused_insurers", []) for i in effective_insurers
            ):
                blocked.append(
                    {"provider_id": p["id"], "restriction": "provider_not_in_network"}
                )
                continue

            # A provider only offers the appointment types on its list,
            # even when the caller asks for one explicitly.
            if appointment_type_id and appointment_type_id not in p.get(
                "appointment_type_ids", []
            ):
                continue
            type_ids = (
                [appointment_type_id]
                if appointment_type_id
                else list(p.get("appointment_type_ids", []))
            )
            for type_id in type_ids:
                appt_type = self.types_by_id[type_id]
                duration = appt_type["duration_minutes"]
                for sched in p.get("schedules", []):
                    if location_id and sched["location_id"] != location_id:
                        continue
                    for day in sched.get("days", []):
                        weekday = _WEEKDAYS.index(day["weekday"])
                        cur = date_from
                        while cur <= date_to:
                            if cur.weekday() != weekday or cur in closures:
                                cur += timedelta(days=1)
                                continue
                            if leave:
                                ls = date.fromisoformat(leave["start"])
                                le = date.fromisoformat(leave["end"])
                                if ls <= cur <= le:
                                    cur += timedelta(days=1)
                                    continue
                            for interval in day.get("intervals", []):
                                start_s, end_s = interval.split("-")
                                t0 = time.fromisoformat(start_s)
                                t1 = time.fromisoformat(end_s)
                                start_dt = datetime.combine(cur, t0, MADRID)
                                end_dt = datetime.combine(cur, t1, MADRID)
                                s = start_dt
                                while s + timedelta(minutes=duration) <= end_dt:
                                    if not self._slot_taken(p["id"], s, duration):
                                        payable = [
                                            i
                                            for i in p.get("accepted_insurers", [])
                                            if i not in p.get("refused_insurers", [])
                                        ]
                                        if effective_insurers:
                                            payable = [
                                                i for i in payable if i in effective_insurers
                                            ]
                                        slots.append(
                                            {
                                                "provider_id": p["id"],
                                                "provider_name": p["name"],
                                                "specialty_id": p["specialty_id"],
                                                "location_id": sched["location_id"],
                                                "appointment_type_id": type_id,
                                                "start_time": s.isoformat(),
                                                "duration_minutes": duration,
                                                "payable_with": payable,
                                            }
                                        )
                                    s += timedelta(minutes=self.calendar.get("slot_minutes", 15))
                            cur += timedelta(days=1)

        slots.sort(key=lambda x: x["start_time"])
        provider_out = [
            {
                "id": p["id"],
                "name": p["name"],
                "specialty_id": p["specialty_id"],
                "languages": p.get("languages", []),
                "accepted_insurers": p.get("accepted_insurers", []),
                "locations": p.get("location_ids", []),
                "on_leave_until": (p.get("leave") or {}).get("end"),
            }
            for p in self.providers
            if (not provider_id or p["id"] == provider_id)
            and (not specialty_id or p["specialty_id"] == specialty_id)
        ]
        at = self.types_by_id.get(appointment_type_id or "")
        return {
            "providers": provider_out,
            "appointment_type": (
                {
                    "id": at["id"],
                    "name": at["name"],
                    "duration_minutes": at["duration_minutes"],
                    "new_patient_requirement": at.get("new_patient_requirement", "none"),
                    "guidance": at.get("guidance", ""),
                }
                if at
                else None
            ),
            "slots": slots,
            "blocked": blocked,
        }

    def _slot_taken(self, provider_id: str, start: datetime, duration: int) -> bool:
        end = start + timedelta(minutes=duration)
        for a in self.appointments:
            if a["provider_id"] != provider_id:
                continue
            a_start = datetime.fromisoformat(a["start_time"])
            a_end = a_start + timedelta(minutes=a["duration_minutes"])
            if a_start < end and start < a_end:
                return True
        for b in self.raw.get("booked_slots", []):
            if b["provider_id"] != provider_id:
                continue
            b_start = datetime.fromisoformat(b["start_time"])
            b_end = b_start + timedelta(minutes=b["duration_minutes"])
            if b_start < end and start < b_end:
                return True
        return False
