"""Guarded tool set for the receptionist brain.

The LLM converses; these tools decide. Every value the model passes that
references clinic data must have come from a previous tool result (slot
tokens, appointment ids, patient ids), making invented ids structurally
impossible. Tools return compact JSON the model can narrate.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from pipecat.services.llm_service import FunctionCallParams

from agent.brain import deps

if TYPE_CHECKING:
    from agent.voice.context import CallContext

MAX_SLOTS_IN_RESULT = 6
MAX_REGISTRY_SLOTS = MAX_SLOTS_IN_RESULT * 3
MADRID = ZoneInfo("Europe/Madrid")

# Fields safe to hand to the LLM or keep in per-call state. National id and
# phone never leave the clinic client: they are the protected fields problem
# 14 checks the transcript for, so they are stripped at the source.
_SAFE_PATIENT_FIELDS = (
    "patient_id",
    "given_name",
    "first_surname",
    "second_surname",
    "date_of_birth",
    "sex",
    "has_visited_before",
    "insurer",
    "referrals",
    "note",
    "matched_fields",
)


class ToolBox:
    """Builds the per-call tool closures. One ToolBox per socket."""

    def __init__(self, ctx: CallContext, settings: Any) -> None:
        self.ctx = ctx
        self.settings = settings
        self.client = deps.try_clinic_client(settings)
        self.cache = deps.try_catalogue_cache()
        self.resolver = deps.try_date_resolver()

    # ---- helpers ---------------------------------------------------------
    async def _call(self, coro: Any, tool: str) -> dict[str, Any]:
        """Await a clinic call with audit + graceful failure."""
        try:
            result = await coro
            self.ctx.audit("tool", {"tool": tool, "ok": True})
            return result
        except Exception as exc:  # noqa: BLE001 - surfaced to the LLM
            self.ctx.audit("tool", {"tool": tool, "ok": False, "error": str(exc)})
            return {"error": f"{tool} failed: {exc}"}

    def _identity_gate(self) -> dict[str, Any] | None:
        if self.ctx.confirmed_patient is None:
            return {"error": "No confirmed patient yet. Identify the caller first."}
        return None

    def _safe_patient(self, match: Any) -> dict[str, Any]:
        """Strip protected fields from a directory match before it is stored."""
        dump = self._dump(match)
        return {k: v for k, v in dump.items() if k in _SAFE_PATIENT_FIELDS}

    @staticmethod
    def _is_error(result: Any) -> bool:
        """True when _call returned a failure dict instead of a typed model."""
        return isinstance(result, dict) and "error" in result

    def _dump(self, obj: Any) -> dict[str, Any]:
        if obj is None:
            return {}
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump"):
            return obj.model_dump(exclude_none=True)
        return {"value": str(obj)}

    # ---- phone hint (caller id is a hint, never identity) -----------------
    async def prepare_phone_hint(self) -> None:
        """Privately resolve `start.customParameters.from_number` after connect.

        Waits at most START_WAIT_SECONDS for the harness `start` event, then
        searches the directory by phone. Exactly one match is stored in
        `ctx.phone_hint_match` with protected fields stripped. Ambiguous,
        errored, absent-number or offline cases leave the hint unset and the
        call greets generically.

        Guarantees: the hint never enters `patient_candidates`, so it can
        never satisfy `confirm_patient`; the lookup uses the phone only
        internally and neither the number nor any national id is stored or
        audited.
        """
        if not await self.ctx.wait_for_start():
            return  # start never arrived: no usable hint, generic greeting
        if not self.ctx.from_number:
            return  # caller id withheld
        if self.client is None or not getattr(self.settings, "prosper_api_key", ""):
            return  # no credentials: never push the API, greet generically
        result = await self._call(
            self.client.search_directory(phone=self.ctx.from_number),
            "phone_hint",
        )
        if self._is_error(result):
            self.ctx.audit("phone_hint", {"outcome": "error"})
            return
        if len(result.matches) != 1:
            self.ctx.audit("phone_hint", {"outcome": "ambiguous", "match_count": len(result.matches)})
            return
        match = self._safe_patient(result.matches[0])
        self.ctx.phone_hint_match = match
        self.ctx.audit("phone_hint", {"outcome": "matched", "patient_id": match.get("patient_id")})

    # ---- tools -----------------------------------------------------------
    async def lookup_patient(
        self,
        params: FunctionCallParams,
        name: str,
        national_id: str | None = None,
        date_of_birth: str | None = None,
    ) -> None:
        """Look up a patient in the clinic directory by name plus one exact identifier.

        Args:
            name: Full name the caller gave, as spoken.
            national_id: DNI or NIE exactly as dictated, if given.
            date_of_birth: The caller's date of birth, ISO yyyy-mm-dd, if given.
        """
        if self.client is None:
            await params.result_callback({"error": "clinic layer unavailable"})
            return
        kwargs: dict[str, Any] = {"name": name}
        if national_id:
            kwargs["national_id"] = national_id
        if date_of_birth:
            kwargs["date_of_birth"] = date_of_birth
        result = await self._call(self.client.search_directory(**kwargs), "lookup_patient")
        if self._is_error(result):
            await params.result_callback(result)
            return
        matches = [self._safe_patient(m) for m in result.matches]
        self.ctx.patient_candidates = matches
        summary = [
            {
                "patient_id": m.get("patient_id"),
                "name": f"{m.get('given_name')} {m.get('first_surname')} {m.get('second_surname')}",
                "date_of_birth": m.get("date_of_birth"),
                "insurer": m.get("insurer"),
                "has_visited_before": m.get("has_visited_before"),
            }
            for m in matches
        ]
        await params.result_callback({"matches": summary, "count": len(summary)})

    async def confirm_patient(self, params: FunctionCallParams, patient_id: str) -> None:
        """Confirm the caller's identity against a patient found by lookup_patient.

        Args:
            patient_id: A patient_id returned by lookup_patient in this call.
        """
        match = next((m for m in self.ctx.patient_candidates if m.get("patient_id") == patient_id), None)
        if match is None:
            await params.result_callback({"error": "patient_id not among lookup results"})
            return
        self.ctx.confirmed_patient = match
        self.ctx.audit("identity_confirmed", {"patient_id": patient_id})
        await params.result_callback({"confirmed": True, "note": match.get("note", "")})

    async def list_my_appointments(self, params: FunctionCallParams, when: str = "upcoming") -> None:
        """List the confirmed patient's appointments (upcoming or past).

        Args:
            when: One of 'upcoming', 'past' or 'all'. Default 'upcoming'.
        """
        gate = self._identity_gate()
        if gate or self.client is None:
            await params.result_callback(gate or {"error": "clinic layer unavailable"})
            return
        patient_id = self.ctx.confirmed_patient["patient_id"]
        result = await self._call(self.client.list_appointments(patient_id, when=when), "list_appointments")
        if self._is_error(result):
            await params.result_callback(result)
            return
        appts = [self._dump(a) for a in result.appointments]
        self.ctx.register_appointments(appts)
        summary = [
            {
                "appointment_id": a.get("appointment_id"),
                "start_time": a.get("start_time"),
                "provider_id": a.get("provider_id"),
                "location_id": a.get("location_id"),
                "type": a.get("appointment_type_id"),
            }
            for a in appts
        ]
        await params.result_callback({"appointments": summary})

    async def find_availability(
        self,
        params: FunctionCallParams,
        when_phrase: str,
        specialty_name: str | None = None,
        provider_name: str | None = None,
        location_name: str | None = None,
        part_of_day: str | None = None,
        language: str | None = None,
    ) -> None:
        """Search real availability. Resolves phrases like 'tomorrow', 'this coming Thursday', 'in a fortnight'.

        Args:
            when_phrase: The caller's words about when, e.g. 'tomorrow', 'first thing Monday', 'this coming Thursday', 'in a fortnight', or an explicit date.
            specialty_name: Specialty requested, if any (e.g. 'dermatología').
            provider_name: Doctor requested by name, if any.
            location_name: Site requested, if any ('Centro', 'Norte', 'Sur').
            part_of_day: 'morning' or 'afternoon', if the caller said one.
            language: Language the caller needs the doctor to speak, if said.
        """
        if self.client is None:
            await params.result_callback({"error": "clinic layer unavailable"})
            return
        resolved: dict[str, Any] = {"phrase": when_phrase}
        date_from: date | None = None
        date_to: date | None = None
        today = datetime.now(MADRID).date()
        if self.resolver is not None:
            try:
                res = self.resolver.resolve_relative(when_phrase, datetime.now(MADRID))
                resolved.update({"date": res.date.isoformat(), "part_of_day": res.part_of_day})
                date_from, date_to = res.date, res.date
            except Exception as exc:  # noqa: BLE001
                resolved["warning"] = f"could not resolve phrase: {exc}"
        if date_from is None:
            # Unresolvable when-phrase: search the full window starting tomorrow
            # (never today — same-day booking is never accepted). 14 days is the
            # API's own span limit.
            date_from = today + timedelta(days=1)
            date_to = today + timedelta(days=14)
            resolved["window"] = [date_from.isoformat(), date_to.isoformat()]
        part = part_of_day or resolved.get("part_of_day")
        kwargs: dict[str, Any] = {"date_from": date_from, "date_to": date_to}
        if provider_name and self.cache is not None:
            prov = self.cache.provider_by_name(provider_name)
            if prov is not None:
                kwargs["provider_id"] = prov.id
            else:
                await params.result_callback({"error": f"no provider named {provider_name!r} in the clinic"})
                return
        if specialty_name and self.cache is not None and "provider_id" not in kwargs:
            spec = self.cache.specialty_by_name(specialty_name)
            if spec is not None:
                kwargs["specialty_id"] = spec.id
            else:
                await params.result_callback({"error": f"no specialty named {specialty_name!r}"})
                return
        if location_name and self.cache is not None:
            loc = self.cache.location_by_name(location_name)
            if loc is not None:
                kwargs["location_id"] = loc.id
        patient_id = (self.ctx.confirmed_patient or {}).get("patient_id")
        if patient_id:
            kwargs["patient_id"] = patient_id
        result = await self._call(self.client.search_availability(**kwargs), "find_availability")
        if self._is_error(result):
            await params.result_callback(result)
            return
        slots = [self._dump(s) for s in result.slots]

        def slot_hour(slot: dict[str, Any]) -> int:
            try:
                return int(str(slot.get("start_time", ""))[11:13])
            except ValueError:
                return -1

        if part:
            # 'Morning' is before 14:00, 'afternoon' from 14:00 (problem-set rule).
            slots = [s for s in slots if (slot_hour(s) < 14) == (part == "morning")]
        if language and self.cache is not None:
            speaking = {p.id for p in self.cache.providers_speaking(language)}
            slots = [s for s in slots if s.get("provider_id") in speaking]
        # Deterministic order: earliest first, ties broken by provider id.
        slots.sort(key=lambda s: (str(s.get("start_time")), str(s.get("provider_id"))))
        labelled = self.ctx.register_slots(slots[:MAX_REGISTRY_SLOTS])
        appt_type = self._dump(result.appointment_type)
        # Blocked restrictions are preserved exactly as the API reported them.
        blocked = [self._dump(b) for b in result.blocked]
        await params.result_callback(
            {
                "resolved": resolved,
                "suggested_appointment_type": appt_type,
                "slots": labelled[:MAX_SLOTS_IN_RESULT],
                "total_free": len(slots),
                "blocked_reasons": blocked,
                "empty_calendar": len(slots) == 0 and not blocked,
            }
        )

    async def book_appointment(
        self,
        params: FunctionCallParams,
        slot_token: str,
        policy_id: str | None = None,
    ) -> None:
        """Queue a booking of a confirmed slot for the confirmed patient.

        Args:
            slot_token: A token returned by find_availability in this call.
            policy_id: The insurance plan to bill, if the caller named one; otherwise the patient's plan on file.
        """
        gate = self._identity_gate()
        if gate:
            await params.result_callback(gate)
            return
        slot = self.ctx.slot_registry.get(slot_token)
        if slot is None:
            await params.result_callback({"error": "unknown slot_token; use one from find_availability"})
            return
        patient = self.ctx.confirmed_patient or {}
        action = {
            "route": "book",
            "patient_id": patient.get("patient_id"),
            "provider_id": slot.get("provider_id"),
            "location_id": slot.get("location_id"),
            "appointment_type_id": slot.get("appointment_type_id"),
            "slot": slot.get("start_time"),
            "policy_id": policy_id or patient.get("insurer"),
        }
        self.ctx.queued_actions.append(action)
        self.ctx.audit("action_queued", action)
        await params.result_callback(
            {
                "booked_would_be": True,
                "confirm_to_caller": {
                    "doctor": slot.get("provider_name"),
                    "site": slot.get("location_id"),
                    "when": slot.get("start_time"),
                    "type": slot.get("appointment_type_id"),
                    "policy": action["policy_id"],
                },
            }
        )

    async def cancel_appointment(self, params: FunctionCallParams, appointment_id: str) -> None:
        """Cancel one of the confirmed patient's upcoming appointments.

        Args:
            appointment_id: An appointment_id from list_my_appointments.
        """
        gate = self._identity_gate()
        if gate:
            await params.result_callback(gate)
            return
        appt = self.ctx.appointment_registry.get(appointment_id)
        if appt is None:
            await params.result_callback({"error": "unknown appointment_id; list appointments first"})
            return
        self.ctx.queued_actions.append({"route": "cancel", "appointment_id": appointment_id})
        self.ctx.audit("action_queued", {"route": "cancel", "appointment_id": appointment_id})
        await params.result_callback({"cancel_would_be": True, "appointment_id": appointment_id})

    async def reschedule_appointment(
        self, params: FunctionCallParams, appointment_id: str, slot_token: str, policy_id: str | None = None
    ) -> None:
        """Move one of the confirmed patient's upcoming appointments to a new confirmed slot.

        Args:
            appointment_id: An appointment_id from list_my_appointments.
            slot_token: A token returned by find_availability for the new slot.
            policy_id: Plan to bill the moved appointment against, if it changes.
        """
        gate = self._identity_gate()
        if gate:
            await params.result_callback(gate)
            return
        appt = self.ctx.appointment_registry.get(appointment_id)
        slot = self.ctx.slot_registry.get(slot_token)
        if appt is None or slot is None:
            await params.result_callback({"error": "unknown appointment_id or slot_token"})
            return
        action = {
            "route": "reschedule",
            "appointment_id": appointment_id,
            "provider_id": slot.get("provider_id"),
            "location_id": slot.get("location_id"),
            "slot": slot.get("start_time"),
            "policy_id": policy_id or (self.ctx.confirmed_patient or {}).get("insurer"),
        }
        self.ctx.queued_actions.append(action)
        self.ctx.audit("action_queued", action)
        await params.result_callback({"reschedule_would_be": True, "new_when": slot.get("start_time")})

    async def register_new_patient(
        self,
        params: FunctionCallParams,
        given_name: str,
        first_surname: str,
        second_surname: str,
        national_id: str,
        date_of_birth: str,
        phone: str,
        email: str,
        insurer: str,
    ) -> None:
        """Register a caller who is not on file. Nothing is booked.

        Args:
            given_name: The patient's given name.
            first_surname: First surname.
            second_surname: Second surname.
            national_id: DNI or NIE with its letter, exactly as dictated.
            date_of_birth: ISO yyyy-mm-dd.
            phone: Phone number as dictated.
            email: Email as dictated ('dot' means '.', 'at' means '@').
            insurer: The insurance plan the patient names.
        """
        valid, normalized_id = deps.validate_national_id(national_id)
        if not valid:
            await params.result_callback({"error": "national id check letter does not match; ask again"})
            return
        self.ctx.queued_actions.append(
            {
                "route": "register",
                "given_name": given_name.strip(),
                "first_surname": first_surname.strip(),
                "second_surname": second_surname.strip(),
                "national_id": normalized_id,
                "date_of_birth": date_of_birth.strip(),
                "phone": phone.strip(),
                "email": email.strip(),
                "insurer": insurer.strip(),
            }
        )
        self.ctx.audit("action_queued", {"route": "register", "national_id": normalized_id})
        await params.result_callback({"registered_would_be": True})

    async def finish_without_booking(self, params: FunctionCallParams, reason: str) -> None:
        """End the call with no booking, for a named, allowed reason.

        Args:
            reason: One of the clinic's refusal reasons, e.g. no_availability, out_of_scope, not_eligible_age, referral_required, provider_on_leave, clinic_closed, patient_not_found, provider_not_found, caller_not_authorised.
        """
        reason = reason.strip().lower()
        if reason not in deps.CLOSED_REASONS:
            await params.result_callback({"error": f"reason {reason!r} not allowed", "allowed": sorted(deps.CLOSED_REASONS)})
            return
        if self.ctx.queued_actions:
            await params.result_callback(
                {
                    "noted": False,
                    "reason": reason,
                    "already_queued": [a.get("route") for a in self.ctx.queued_actions],
                    "warning": "another action is already queued for this call; no refusal was recorded",
                }
            )
            return
        self.ctx.queued_actions.append({"route": "no-action", "reason": reason})
        self.ctx.audit("action_queued", {"route": "no-action", "reason": reason})
        await params.result_callback({"noted": True, "reason": reason})

    async def escalate_call(self, params: FunctionCallParams, reason: str = "medical_emergency") -> None:
        """Escalate the call to a human, for emergencies only.

        Args:
            reason: Why the call escalates; use medical_emergency for health emergencies.
        """
        reason = reason.strip().lower()
        if reason not in deps.CLOSED_REASONS:
            await params.result_callback({"error": f"reason {reason!r} not allowed"})
            return
        self.ctx.queued_actions.append({"route": "escalate", "reason": reason})
        self.ctx.audit("action_queued", {"route": "escalate", "reason": reason})
        await params.result_callback({"escalated": True})

    # ---- reflow seam (ClinicReflow) --------------------------------------
    async def get_reflow_context(self, params: FunctionCallParams, appointment_id: str) -> None:
        """Load a reflow negotiation case: the affected appointment and its alternatives.

        Args:
            appointment_id: The affected appointment being renegotiated.
        """
        try:
            from agent.voice.reflow import load_reflow_case

            case = await load_reflow_case(appointment_id, self.settings.data_dir)
            await params.result_callback(case)
        except FileNotFoundError as exc:
            await params.result_callback({"error": str(exc)})

    async def commit_reflow_decision(
        self,
        params: FunctionCallParams,
        appointment_id: str,
        outcome: str,
        accepted_alternative_id: str | None = None,
        counter_constraints: list[str] | None = None,
    ) -> None:
        """Commit the patient's reflow decision so the optimizer can recalculate.

        Args:
            appointment_id: The affected appointment.
            outcome: One of accepted, rejected, counter_offered, unreachable.
            accepted_alternative_id: The alternative the patient accepted, when accepted.
            counter_constraints: What the patient says would work instead, when not accepted.
        """
        try:
            from agent.voice.reflow import commit_reflow_decision

            saved = await commit_reflow_decision(
                appointment_id,
                outcome,
                self.ctx.call_id,
                self.settings.data_dir,
                accepted_alternative_id=accepted_alternative_id,
                counter_constraints=counter_constraints or [],
            )
            await params.result_callback(saved)
        except (FileNotFoundError, ValueError) as exc:
            await params.result_callback({"error": str(exc)})

    # ---- registration ----------------------------------------------------
    def tools(self) -> list[Any]:
        return [
            self.lookup_patient,
            self.confirm_patient,
            self.list_my_appointments,
            self.find_availability,
            self.book_appointment,
            self.cancel_appointment,
            self.reschedule_appointment,
            self.register_new_patient,
            self.finish_without_booking,
            self.escalate_call,
            self.get_reflow_context,
            self.commit_reflow_decision,
        ]
