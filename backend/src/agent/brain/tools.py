"""Guarded tool set for the receptionist brain.

The LLM converses; these tools decide. Every value the model passes that
references clinic data must have come from a previous tool result (slot
tokens, appointment ids, patient ids), making invented ids structurally
impossible. Tools return compact JSON the model can narrate.

On the Gemini path the toolbox additionally exposes the zero-argument
``assess_current_turn`` advisory tool: it reads ONLY the CallContext's latest
finalized caller utterance, redacts it locally (known patient names plus the
core regex scrub) and asks the Jev sidecar for a typed assessment. Jev is
advisory by construction: it never authorizes, vetoes, selects ids/slots or
touches the clinic API; every tool keeps authorizing independently against
the per-call registries.
"""
from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from loguru import logger
from pipecat.services.llm_service import FunctionCallParams

from agent.brain import deps

if TYPE_CHECKING:
    from agent.voice.context import CallContext

MAX_SLOTS_IN_RESULT = 6
MAX_REGISTRY_SLOTS = MAX_SLOTS_IN_RESULT * 3
MADRID = ZoneInfo("Europe/Madrid")

# Transcript turns handed to the Jev sidecar: ONLY the latest finalized
# caller utterance (coordinator contract), never the full conversation.
JEV_CONTEXT_KEYS = ("phase", "identity_status", "patient_confirmed")


def _build_jev_client(settings: Any) -> Any | None:
    """One advisory Jev client per socket, configured from settings.

    Returns None when the decision layer is absent (boot-order safety); every
    caller treats that exactly like an abstention.
    """
    try:
        from agent.decision.client import JevClient
    except ImportError:
        return None
    try:
        kwargs: dict[str, Any] = {
            "api_key": getattr(settings, "typesafe_api_key", None),
            "timeout_seconds": float(getattr(settings, "jev_timeout_seconds", 0.300)),
            "min_confidence": float(getattr(settings, "jev_min_confidence", 0.5)),
        }
        if getattr(settings, "typesafe_base_url", None):
            kwargs["base_url"] = settings.typesafe_base_url
        if getattr(settings, "jev_model", None):
            kwargs["model"] = settings.jev_model
        return JevClient(**kwargs)
    except (TypeError, ValueError):
        return None


def _scrub_known_names(text: str, ctx: Any) -> str:
    """Replace locally known patient names with the redaction marker.

    Applied on top of the decision layer's core regex redaction: the people
    this call already touched must never reach the sidecar, even when the
    caller repeats them inside an utterance.
    """
    from agent.decision.models import REDACTED

    scrubbed = text
    seen: set[str] = set()
    sources = [ctx.confirmed_patient, ctx.phone_hint_match, *ctx.patient_candidates]
    for record in sources:
        if not record:
            continue
        parts = [str(record.get(k, "") or "") for k in ("given_name", "first_surname", "second_surname")]
        full = " ".join(p for p in parts if p)
        for candidate in (*[p for p in parts if len(p) >= 3], full):
            key = candidate.casefold()
            if candidate and key not in seen:
                seen.add(key)
                import re

                scrubbed = re.sub(
                    re.escape(candidate),
                    REDACTED,
                    scrubbed,
                    flags=re.IGNORECASE,
                )
    return scrubbed

# Fields safe to hand to the LLM or keep in per-call state. National id and
# phone never leave the clinic client: they are the protected fields problem
# 14 checks the transcript for, so they are stripped at the source.
def _fold_plain(text: str) -> str:
    """Accent- and case-insensitive key, the same rule the catalogue uses."""
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold().strip()


# Refusals that are only true for the plan on file. A second plan the caller
# holds can overturn every one of them, so none may be sent before they have
# been asked.
def _restrictions(blocked: list[dict[str, Any]]) -> set[str]:
    """The distinct restriction names in a blocked list."""
    return {str(b.get("restriction")) for b in blocked}


def _plan_id(cache: Any, spoken: str | None) -> str | None:
    """The submit enum wants the plan's id; a caller says its name.

    `Mapfre Salud`, `Sanitas`, `AXA` are what people say and what the model
    passes back, and every one of them is a 422 on a field the API declares
    as an enum of ids. The catalogue holds both spellings, so resolve through
    it and let an id pass straight through unchanged.
    """
    if not spoken:
        return None
    spoken = spoken.strip()
    if cache is None:
        return spoken
    plan = cache.plan_by_id(spoken) or cache.plan_by_name(spoken)
    return plan.id if plan is not None else spoken


# One round trip, on a path that would otherwise cost a whole turn of a
# three-minute call. Measured: a Jev read is ~600 ms.
JEV_PLAN_TIMEOUT_SECONDS = 1.5

_COVERAGE_REASONS = frozenset({
    "specialty_not_covered",
    "location_not_covered",
    "provider_not_in_network",
    "insurer_referral_required",
    "allowance_exhausted",
})

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
        self.engine = str(getattr(settings, "voice_engine", "cascade"))
        self.client = deps.try_clinic_client(settings)
        self.cache = deps.try_catalogue_cache()
        self._assessments: set[Any] = set()
        self.resolver = deps.try_date_resolver()
        # Advisory sidecar: one isolated client per socket, closed at teardown.
        self.jev = _build_jev_client(settings)

    def watch_caller_turns(self) -> None:
        """Have Jev read every finalised caller turn, off the critical path.

        Jev is fast (TypeSafe publish 70-500 ms end to end) but a turn is not
        the place to spend even that: the model is already generating by the
        time the transcript lands. So each turn is read in the BACKGROUND and
        the verdict is parked on the CallContext, where any tool can quote it
        for free. Nothing waits on it, nothing breaks if it never finishes.
        """
        self.ctx._on_caller_turn = self._schedule_assessment
        self._schedule_warmup()

    def _schedule_warmup(self) -> None:
        """Open the sidecar connection before the first caller turn needs it.

        Measured cold, the first assessment of a process takes ~600 ms and is
        cut off by the budget — so the FIRST caller turn of a call, the one
        that decides whether we understood them at all, is exactly the one
        that abstains. Warm connections answer in 237-299 ms. This burns that
        cost at connect time, on a fixed harmless string, where nobody is
        waiting.
        """
        if self.jev is None:
            return
        try:
            task = asyncio.create_task(self._warm_jev())
        except RuntimeError:
            return
        self._assessments.add(task)
        task.add_done_callback(self._assessments.discard)

    async def _warm_jev(self) -> None:
        from agent.decision.models import TurnDecisionInput

        try:
            await self.jev.assess(
                TurnDecisionInput.from_messages(
                    [{"role": "caller", "text": "hola"}],
                    context={"phase": "warmup", "identity_status": "unconfirmed",
                             "patient_confirmed": False},
                ),
                cancel=self.ctx.cancel_token,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - warming must never affect the call
            return

    def _schedule_assessment(self, _text: str) -> None:
        if self.jev is None:
            return
        try:
            task = asyncio.create_task(self._assess_in_background())
        except RuntimeError:
            return  # no running loop (sync test context): nothing to schedule
        self._assessments.add(task)
        task.add_done_callback(self._assessments.discard)

    async def _assess_in_background(self) -> None:
        try:
            from agent.decision.client import BACKGROUND_TIMEOUT_SECONDS

            self.ctx.latest_decision = await self._jev_assessment(BACKGROUND_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a sidecar must never surface here
            self.ctx.latest_decision = None

    async def aclose(self) -> None:
        """Release per-socket sidecar resources (idempotent)."""
        self.ctx._on_caller_turn = None
        for task in list(self._assessments):
            task.cancel()
        if self._assessments:
            await asyncio.gather(*self._assessments, return_exceptions=True)
            self._assessments.clear()
        if self.jev is not None:
            await self.jev.close()
            self.jev = None

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
    def _calendar_window(self) -> tuple[date, date] | None:
        """The clinic's bookable range, or None when the catalogue is cold."""
        if self.cache is None or not self.cache.warmed:
            return None
        cal = self.cache.catalogue.calendar

        def as_date(value: Any) -> date | None:
            # The catalogue types these as dates; a fixture may hold strings.
            if isinstance(value, date):
                return value
            try:
                return date.fromisoformat(str(value))
            except ValueError:
                return None

        first, last = as_date(cal.starts), as_date(cal.ends)
        return (first, last) if first and last else None

    def _clamp_to_calendar(self, start: date, end: date) -> tuple[date, date] | None:
        """Pull a requested window inside the published calendar.

        None when the whole window falls outside it, which is a real answer —
        the clinic simply does not take bookings then — rather than a 422 the
        model has to read.
        """
        window = self._calendar_window()
        if window is None:
            return (start, end)
        first, last = window
        start, end = max(start, first), min(end, last)
        return (start, end) if start <= end else None

    def _known_specialties(self) -> list[str]:
        """The clinic's real specialty names, from the cached catalogue.

        Read off the index rather than ``cache.catalogue``, whose property
        raises when the cache was never warmed — a soft "say it another way"
        must not become a hard tool exception mid-call.
        """
        if self.cache is None:
            return []
        return sorted({sp.name for sp in self.cache.specialties_by_id.values()})

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

        # The directory refuses a bare given name, and that refusal costs a
        # turn. It is answerable here: a first name alone is simply not enough
        # to find anybody, and the caller is the one who has to fill the gap.
        if len(str(name).split()) < 2 and not national_id and not date_of_birth:
            await params.result_callback(
                {
                    "error": (
                        f"{name!r} on its own cannot find anyone: the directory needs a "
                        "given name with at least one surname, or an exact national id, "
                        "phone or date of birth. Ask the caller for one and try again."
                    )
                }
            )
            return

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
                # The referrals decide whether a referral-gated specialty is a
                # booking or a refusal, and the note is what lets a receptionist
                # sound like they know the person. Both were being dropped on
                # the floor here while the API returned them every time.
                "referrals": m.get("referrals") or [],
                "note": m.get("note"),
                # WHICH fields matched. Some ids differ from another
                # patient's by a single digit, so a misheard one returns a
                # confidently wrong person; seeing that only the name matched
                # is what tells you to confirm on something else.
                "matched_on": m.get("matched_fields") or [],
            }
            for m in matches
        ]
        # Audit the SHAPE of the lookup, never its values: which identifiers
        # the caller supplied and how many rows came back. Without this, a
        # failed identification is indistinguishable from a failed API call
        # in the trace — both audit as tool ok=True — and that cost a whole
        # debugging round on a live scored call.
        self.ctx.audit(
            "patient_lookup",
            {
                "count": len(summary),
                "with_dob": bool(date_of_birth),
                "with_national_id": bool(national_id),
                "exact_dob_matches": sum(
                    1 for m in summary if date_of_birth and m.get("date_of_birth") == date_of_birth
                ),
            },
        )
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
        insurer: str | None = None,
    ) -> None:
        """Search real availability. Resolves phrases like 'tomorrow', 'this coming Thursday', 'in a fortnight'.

        Args:
            when_phrase: The caller's words about when, e.g. 'tomorrow', 'first thing Monday', 'this coming Thursday', 'in a fortnight', or an explicit date.
            specialty_name: Specialty requested, if any (e.g. 'dermatología').
            provider_name: Doctor requested by name, if any.
            location_name: Site requested, if any ('Centro', 'Norte', 'Sur').
            part_of_day: 'morning' or 'afternoon', if the caller said one.
            language: The language the caller is SPEAKING, whenever that is not English, or one they explicitly ask the doctor to speak. Pass 'español' for a Spanish call and 'català' for a Catalan one. Spanish costs nothing — every doctor here speaks it — but only four of the twelve speak Catalan, so in a Catalan call this parameter IS the booking: leave it out and you will offer a doctor the caller cannot talk to. Leave it out for an English call unless they ask, or you will hide four doctors who may hold the earliest slot.
            insurer: An insurance plan the caller names that is NOT the one on their record. Leave it out and the search prices against the plan on file; a second plan exists nowhere in the data and only the caller can reveal it, so pass it here the moment they mention one.
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
        sound_alikes: list[dict[str, Any]] = []
        if provider_name and self.cache is not None:
            prov = self.cache.provider_by_name(provider_name)
            if prov is not None:
                kwargs["provider_id"] = prov.id
                # A surname is the least reliable thing on a phone line, and
                # this clinic has pairs one letter apart in DIFFERENT fields.
                # Resolving one confidently is how the wrong doctor in the
                # wrong specialty gets booked with nobody noticing, so say
                # who else it could have been and let the model ask.
                sound_alikes = [
                    {
                        "provider_id": other.id,
                        "name": other.name,
                        "specialty": other.specialty_name,
                    }
                    for other in self.cache.providers_sounding_like(provider_name)
                    if other.id != prov.id
                ]
            else:
                await params.result_callback({"error": f"no provider named {provider_name!r} in the clinic"})
                return
        if specialty_name and self.cache is not None and "provider_id" not in kwargs:
            spec = self.cache.specialty_by_name(specialty_name)
            if spec is not None:
                kwargs["specialty_id"] = spec.id
            else:
                # Name the real catalogue so the model can retry in one turn
                # instead of asking the caller to name their own specialty.
                # Name the catalogue from the index, never from
                # cache.catalogue: that property raises when the cache was
                # not warmed, which would turn a soft "say it another way"
                # into a hard tool exception mid-call.
                await params.result_callback(
                    {
                        "error": f"no specialty named {specialty_name!r}",
                        "specialties": self._known_specialties(),
                    }
                )
                return
        if location_name and self.cache is not None:
            loc = self.cache.location_by_name(location_name)
            if loc is not None:
                kwargs["location_id"] = loc.id
        patient_id = (self.ctx.confirmed_patient or {}).get("patient_id")
        if patient_id:
            kwargs["patient_id"] = patient_id
        if insurer and self.cache is not None:
            # Naming a plan IS the answer to the second-plan question, so a
            # coverage refusal after this is an informed one.
            self.ctx.asked_about_second_plan = True
            plan = self.cache.plan_by_name(insurer)
            if plan is not None:
                kwargs["insurer"] = plan.id

        # The API refuses a search with neither a provider nor a specialty, and
        # a refusal costs a whole turn of a 180 s call. Observed live: five of
        # these in one call. Answer it here instead, naming what the clinic
        # actually has, so the retry lands on the next turn.
        if "provider_id" not in kwargs and "specialty_id" not in kwargs:
            await params.result_callback(
                {
                    "error": (
                        "a search needs either a specialty or a named doctor; "
                        "ask the caller which and call again with it"
                    ),
                    "specialties": self._known_specialties(),
                }
            )
            return

        # The calendar is finite and the API rejects anything outside it, which
        # costs a turn. Clamp instead: a caller asking for something beyond the
        # published window gets the nearest real answer with a note, not an
        # error the model has to interpret.
        clamped = self._clamp_to_calendar(kwargs["date_from"], kwargs["date_to"])
        if clamped is None:
            await params.result_callback(
                {
                    "error": "that date is outside the clinic's bookable calendar",
                    "bookable": self._calendar_window(),
                }
            )
            return
        if clamped != (kwargs["date_from"], kwargs["date_to"]):
            resolved["clamped_to_calendar"] = [d.isoformat() for d in clamped]
        kwargs["date_from"], kwargs["date_to"] = clamped

        result = await self._call(self.client.search_availability(**kwargs), "find_availability")
        if self._is_error(result):
            await params.result_callback(result)
            return
        slots = [self._dump(s) for s in result.slots]
        # The query, not just "ok: True". A call that searched four times and
        # then told the caller the diary was full was indistinguishable in the
        # trace from one that never searched at all; ids and dates only, no
        # patient data.
        self.ctx.audit(
            "availability_query",
            {
                "asked": when_phrase,
                **{k: str(v) for k, v in kwargs.items() if k != "patient_id"},
                "slots": len(slots),
            },
        )

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

        # The caller asked for one day and that day has nothing. A closed DAY
        # is already rolled by the resolver, but a closed HALF of a day is not:
        # only Centro opens on a Saturday and only in the morning, so "Saturday
        # afternoon" resolves to a real open day with no afternoon in it. The
        # published rule is that the caller takes the earliest appointment on
        # the next open day that still matches the rest of what they asked —
        # same site, same part of the day — so look forward for them instead of
        # reporting an empty diary.
        #
        # Not when the rule that bit is about the doctor the caller named.
        # `blocked` is never empty — Dr. Requena's leave shows up on every
        # single query — so "was anything blocked" is the wrong question. The
        # right one is whether the caller's OWN request was what got stopped:
        # asking for Requena by name is a refusal that must name his leave,
        # while asking for the specialty is a roll.
        asked_for = kwargs.get("provider_id")
        refused_in_person = asked_for is not None and any(
            getattr(b, "provider_id", None) == asked_for for b in result.blocked
        )
        if (
            not slots
            and not refused_in_person
            and date_from == date_to
            and self.resolver is not None
        ):
            rolled = self.resolver.next_open_day(date_from + timedelta(days=1))
            kwargs["date_from"], kwargs["date_to"] = rolled, rolled + timedelta(days=13)
            wider = await self._call(self.client.search_availability(**kwargs), "find_availability")
            if not self._is_error(wider):
                slots = [self._dump(s) for s in wider.slots]
                if part:
                    slots = [s for s in slots if (slot_hour(s) < 14) == (part == "morning")]
                if language and self.cache is not None:
                    slots = [s for s in slots if s.get("provider_id") in speaking]
                if slots:
                    result = wider
                    resolved["rolled_forward_from"] = date_from.isoformat()
                    resolved["reason"] = (
                        "nothing on the day asked for; this is the next open day "
                        "that matches the rest of the request"
                    )

        # Deterministic order: earliest first, ties broken by provider id.
        slots.sort(key=lambda s: (str(s.get("start_time")), str(s.get("provider_id"))))
        labelled = self.ctx.register_slots(slots[:MAX_REGISTRY_SLOTS])
        appt_type = self._dump(result.appointment_type)
        # Blocked restrictions, with the provider named. The API reports an
        # id; a model cannot tell a caller "PR02 is unavailable", and the
        # whole point of a refusal is naming the rule and the person it hit.
        blocked = []
        for entry in result.blocked:
            dumped = self._dump(entry)
            who = self.cache.provider_by_id(dumped.get("provider_id", "")) if self.cache else None
            if who is not None:
                dumped["provider_name"] = who.name
                dumped["specialty"] = who.specialty_name
            blocked.append(dumped)
        offered = labelled[:MAX_SLOTS_IN_RESULT]
        await params.result_callback(
            {
                "resolved": resolved,
                "suggested_appointment_type": appt_type,
                # Ordered earliest first; the earliest is named explicitly so
                # "the soonest appointment" cannot be answered with a later
                # slot whose site or doctor happens to read better. Its
                # provider and location travel with it: booking the token and
                # confirming another slot's doctor or site is a wrong answer.
                "earliest_token": offered[0]["token"] if offered else None,
                "slots": offered,
                "total_free": len(slots),
                # Populated only when the name the caller said could have been
                # somebody else. Empty means the name was unambiguous.
                "name_could_also_be": sound_alikes,
                "blocked_reasons": blocked,
                "empty_calendar": len(slots) == 0 and not blocked,
                # blocked_reasons is noisy — a doctor on leave appears on
                # every query — so a model learns to skim past it. When it is
                # the ONLY thing standing between the caller and a slot it
                # stops being background and becomes the answer, and it is
                # said here in the words finish_without_booking accepts.
                # Observed: physiotherapy returned zero slots and one
                # location_not_covered, and the caller was told the diary was
                # full and the call closed as no_availability.
                **(
                    {
                        "nothing_free_and_this_is_why": {
                            "restrictions": sorted(_restrictions(blocked)),
                            # Named only when every block agrees; two different
                            # rules are a question for the model, not an answer.
                            "reason_to_submit": (
                                min(_restrictions(blocked))
                                if len(_restrictions(blocked)) == 1
                                else None
                            ),
                            "not_no_availability": (
                                "the diary is not full; a rule stopped this. Do not tell the "
                                "caller there are no appointments"
                            ),
                        }
                    }
                    if not slots and blocked
                    else {}
                ),
            }
        )

    async def describe_clinic(self, params: FunctionCallParams, about: str) -> None:
        """Answer a factual question about the clinic from its own records.

        Use it the moment a caller asks anything about how the clinic works —
        how many sites there are and where, which doctors there are and what
        they do, which languages they speak, what a site's opening hours are,
        which specialties exist, which insurance plans are taken. Never answer
        any of that from memory: a wrong fact sends the caller to a site that
        is shut or a doctor who does not exist, and the booking that follows
        is wrong because of it.

        Args:
            about: What they asked about — one of 'sites', 'doctors', 'specialties' or 'plans'. Anything else returns all four.
        """
        if self.cache is None or not self.cache.warmed:
            await params.result_callback({"error": "clinic catalogue unavailable"})
            return
        catalogue = self.cache.catalogue
        wanted = _fold_plain(about)

        def sites() -> list[dict[str, Any]]:
            return [
                {
                    "location_id": loc.id,
                    "name": loc.name,
                    "address": loc.address,
                    "hours": [{"weekday": d.weekday, "open": d.intervals} for d in loc.hours],
                    "doctors": loc.provider_names,
                }
                for loc in catalogue.locations
            ]

        def doctors() -> list[dict[str, Any]]:
            return [
                {
                    "provider_id": pr.id,
                    "name": pr.name,
                    "specialty": pr.specialty_name,
                    "languages": pr.languages,
                    "sites": pr.location_names,
                    "on_leave": None
                    if pr.leave is None
                    else {"from": str(pr.leave.start), "to": str(pr.leave.end)},
                }
                for pr in catalogue.providers
            ]

        def specialties() -> list[dict[str, Any]]:
            return [
                {
                    "specialty_id": sp.id,
                    "name": sp.name,
                    "referral_required": sp.referral_required,
                    "doctors": sp.provider_names,
                }
                for sp in catalogue.specialties
            ]

        def plans() -> list[dict[str, Any]]:
            return [
                {
                    "policy_id": pl.id,
                    "name": pl.name,
                    "covers_specialties": pl.covered_specialty_names,
                    "does_not_cover_specialties": pl.uncovered_specialty_names,
                    "covers_sites": pl.covered_location_names,
                }
                for pl in catalogue.plans
            ]

        sections = {"sites": sites, "doctors": doctors, "specialties": specialties, "plans": plans}
        picked = {k: v() for k, v in sections.items() if k.startswith(wanted[:4] or "~")}
        await params.result_callback(picked or {k: v() for k, v in sections.items()})

    async def find_nearest_site(
        self,
        params: FunctionCallParams,
        where_the_caller_is: str,
        specialty_name: str | None = None,
    ) -> None:
        """Find which of the clinic's sites is closest to where the caller is.

        The answer is the nearest site that can ACTUALLY serve them: if the
        closest one has nobody who does what they need, the answer is the
        closest one that does — not a refusal, and not the closest outright.

        Args:
            where_the_caller_is: The place they gave, in their words — a street address, a district or a town, e.g. 'Calle de Madrid 54, in Getafe'.
            specialty_name: The specialty they need, when they have said one, so a site that cannot serve it is never offered.
        """
        if self.cache is None or not self.cache.warmed:
            await params.result_callback({"error": "clinic catalogue unavailable"})
            return

        point = await self._geocode(where_the_caller_is)
        if point is None:
            await params.result_callback(
                {
                    "error": f"could not place {where_the_caller_is!r} on the map",
                    "sites": [
                        {"location_id": loc.id, "name": loc.name, "address": loc.address}
                        for loc in self.cache.catalogue.locations
                    ],
                    "hint": "ask the caller which town or district they are in",
                }
            )
            return

        wanted: set[str] | None = None
        if specialty_name:
            spec = self.cache.specialty_by_name(specialty_name)
            if spec is not None:
                wanted = {
                    loc_name
                    for pr in self.cache.providers_for_specialty(spec.id)
                    for loc_name in pr.location_names
                }

        ranked = []
        for loc, km in self.cache.nearest_locations(point[0], point[1]):
            serves = wanted is None or loc.name in wanted
            ranked.append(
                {
                    "location_id": loc.id,
                    "name": loc.name,
                    "address": loc.address,
                    "km_straight_line": round(km, 2),
                    "can_serve_the_request": serves,
                }
            )
        servable = [r for r in ranked if r["can_serve_the_request"]]
        await params.result_callback(
            {
                "located": where_the_caller_is,
                "nearest_that_can_serve": servable[0] if servable else None,
                "all_sites_by_distance": ranked,
            }
        )

    async def _geocode(self, place: str) -> tuple[float, float] | None:
        """Put a spoken place on the map, or give up quietly.

        The map comes first and the shortcut second, which is the opposite of
        the obvious order and the reason it works: matching the caller's words
        against the clinic's own addresses sent "Calle de Madrid 54, Getafe"
        to the Madrid site, because the street is called Madrid. A street name
        is not a town. Only when the geocoder has nothing to say is the town
        fallback allowed to guess, and then only on a whole word that is not
        part of a street name.

        Fails soft in every direction: a geocoder that is slow, down or
        rate-limited must never be the reason a call ends without an answer.
        """
        import httpx

        queries = [place]
        if "spain" not in _fold_plain(place) and "españa" not in _fold_plain(place):
            queries.append(f"{place}, Madrid, Spain")
        # A house number the map has never heard of sinks the whole query, and
        # the street alone is well inside the margin these cases are drawn
        # with. Try it before giving up.
        without_number = re.sub(r"\s*\b\d+\b", "", place).strip(" ,")
        if without_number and without_number != place:
            queries.append(f"{without_number}, Madrid, Spain")
        # And the Spanish street-type prefix, which the geocoder dislikes:
        # "Calle de Alberto Alcocer" finds nothing, "Alberto Alcocer" lands on
        # the street. Callers say the prefix; the map would rather they didn't.
        bare = re.sub(
            r"^\s*(calle|avenida|avda|plaza|paseo|carretera|camino|ronda|via)\s+(de\s+|del\s+|de\s+la\s+)?",
            "",
            without_number or place,
            flags=re.IGNORECASE,
        ).strip(" ,")
        if bare and bare not in (place, without_number):
            queries.append(f"{bare}, Madrid, Spain")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as http:
                for query in queries:
                    response = await http.get(
                        "https://nominatim.openstreetmap.org/search",
                        params={
                            "q": query,
                            "format": "json",
                            "limit": 1,
                            "countrycodes": "es",
                        },
                        headers={"User-Agent": "clinica-arenal-receptionist/1.0"},
                    )
                    response.raise_for_status()
                    hits = response.json()
                    if hits:
                        return (float(hits[0]["lat"]), float(hits[0]["lon"]))
        except Exception as exc:  # noqa: BLE001 - a map lookup must not end a call
            logger.warning("geocoder unavailable, falling back to town match: {}", exc)

        # Last resort: the caller named the town one of our sites sits in.
        folded = _fold_plain(place)
        words = set(folded.replace(",", " ").split())
        for loc in self.cache.catalogue.locations if self.cache else []:
            tail = _fold_plain(loc.address).rsplit(",", 1)[-1].strip()
            town = tail.split()[-1] if tail.split() else ""
            # A whole word, and never one that is only there as a street name.
            if town and town in words and f"calle de {town}" not in folded:
                return (loc.latitude, loc.longitude)
        return None

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
            "policy_id": _plan_id(self.cache, policy_id or patient.get("insurer")),
        }
        self.ctx.queued_actions.append(action)
        self.ctx.audit("action_queued", action)
        reading = self.ctx.latest_decision
        await params.result_callback(
            {
                "booked_would_be": True,
                # A second opinion on the words that led here, already paid
                # for in the background. Advisory: the booking is queued
                # either way. It is here so that a reading which does NOT
                # look like a booking gets noticed on the next turn instead
                # of at the reveal.
                "caller_intent_reading": None if reading is None else {
                    "intent": reading.get("intent"),
                    "confidence": reading.get("confidence"),
                },
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
            "policy_id": _plan_id(
                self.cache, policy_id or (self.ctx.confirmed_patient or {}).get("insurer")
            ),
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
        plan_id = _plan_id(self.cache, insurer)
        if (
            self.cache is not None
            and self.cache.plan_by_id(plan_id or "") is None
            and self.jev is not None
            and self.jev.configured
        ):
            # The catalogue could not place these words. Before making the
            # caller repeat themselves, put the whole list of plans the clinic
            # sells in front of a model built for constrained choice, and take
            # its answer only when it is confident. The list is the live
            # catalogue, so this never needs editing when the clinic signs an
            # insurer. Costs one round trip, on a path that otherwise ends in
            # a wasted turn.
            chosen = await self.jev.classify_plan(
                insurer,
                {p.id: p.name for p in self.cache.plans_by_id.values()},
                timeout_seconds=JEV_PLAN_TIMEOUT_SECONDS,
            )
            if chosen is not None:
                self.ctx.audit("plan_classified", {"by": "jev", "plan_id": chosen})
                plan_id = chosen
        if self.cache is not None and self.cache.plan_by_id(plan_id or "") is None:
            # Caught here, not at submit time: a rejected registration is only
            # discovered once the call is over and nothing can be asked again.
            # Name the ones it could have been. A bad line does not produce a
            # plausible wrong plan, it produces noise, and the answer to noise
            # is to read the real names back — not to pick the nearest, which
            # is guessing with extra steps.
            near = [p.name for p in self.cache.plans_sounding_like(insurer)]
            await params.result_callback(
                {
                    "error": f"no such insurer: {insurer!r}",
                    "did_you_mean": near,
                    "ask_them": (
                        "say these names to them and let them pick one"
                        if near
                        else "ask them to say their insurer again"
                    ),
                    "the_clinic_knows": ", ".join(p.name for p in self.cache.plans_by_id.values()),
                }
            )
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
                "insurer": plan_id,
            }
        )
        # The whole body, not just the id. Four registrations were lost to a
        # 422 nobody could see because this audit named one field; and one was
        # lost to an insurer the caller never said, which this would have shown.
        self.ctx.audit(
            "action_queued",
            {"route": "register", **{k: v for k, v in self.ctx.queued_actions[-1].items() if k != "route"}},
        )
        plan = self.cache.plan_by_id(plan_id or "") if self.cache is not None else None
        await params.result_callback(
            {
                "registered_would_be": True,
                # Say this back to them. A plan is one word over a telephone and
                # the wrong one fails the registration as surely as a wrong id:
                # "Mapfre Salud" came through as "ma phrase salue" on a scored
                # call and the plan submitted was one nobody had mentioned.
                "insurer_recorded": plan.name if plan is not None else plan_id,
                "read_this_back_to_them": True,
            }
        )

    async def finish_without_booking(self, params: FunctionCallParams, reason: str) -> None:
        """End the call with no booking, for a named, allowed reason.

        Args:
            reason: Exactly one value from the clinic's closed vocabulary, naming the rule that actually bit. The first eleven mirror a standing clinic restriction one-for-one and /availability names the one that stopped a provider in its `blocked` list: not_eligible_age (too young or too old for the specialty), referral_required (the specialty needs one and they have none), provider_not_in_network (that doctor refuses their plan), specialty_not_covered (their plan does not cover it), location_not_covered (their plan does not cover that site), insurer_referral_required (their plan demands its own referral), allowance_exhausted (their plan has run out of visits), provider_on_leave, location_hours (the site is shut then), type_not_offered (that specialty does not offer that visit type), patient_history (their record rules it out). The rest end a call that no rule refused: no_availability (the diary is simply full), clinic_closed, patient_not_found, provider_not_found, caller_not_authorised, out_of_scope (not a receptionist's job), medical_emergency.
        """
        reason = reason.strip().lower()
        if reason not in deps.CLOSED_REASONS:
            await params.result_callback({"error": f"reason {reason!r} not allowed", "allowed": sorted(deps.CLOSED_REASONS)})
            return
        # A coverage refusal is only true for the plan we know about, and a
        # patient may hold a second one that is nowhere in the data — only the
        # caller can reveal it. Observed live: the agent refused orthopaedics,
        # the caller answered "why can't it be booked with Nueva Mutua?", and
        # the agent repeated the refusal and ended the call. Refuse only after
        # the question has been put.
        if reason in _COVERAGE_REASONS and not self.ctx.asked_about_second_plan:
            # One nudge, not a loop: the flag is set here, so the same refusal
            # goes through next time. The point is to buy the caller a single
            # chance to volunteer the plan that changes the answer, not to
            # argue with the model about whether it asked.
            self.ctx.asked_about_second_plan = True
            self.ctx.audit("refusal_deferred", {"reason": reason})
            await params.result_callback(
                {
                    "error": "not yet: this refusal depends on which plan they hold",
                    "do_this_first": (
                        "ask the caller whether they hold another insurance plan besides "
                        "the one on file. A second plan exists nowhere in the data and "
                        "only they can tell you. If they name one, search availability "
                        "again passing it as insurer, and bill the plan that works. If "
                        "they say they have no other, call this tool again and it will "
                        "go through."
                    ),
                }
            )
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
        """Hand the call to a human. Book nothing.

        Use it the moment a caller describes any of these, in these words or
        near them — they are the clinic's own red flags and none of them is
        an appointment:

        - tight pain across the chest, struggling to catch their breath
        - one side of the face suddenly droopy, an arm gone weak, words slurred
        - cannot get their breath at all, came on out of nowhere, stopping
          between words
        - a cut bleeding heavily that will not stop after ten minutes of pressure
        - banged their head an hour ago, confused and being sick since

        Recognising one is not a clinical judgement and not a close call: it
        is this list. Stop scheduling, tell them to get urgent help now (112
        or urgent care), and escalate with medical_emergency.

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

    # ---- Jev advisory (Gemini path only) ----------------------------------
    async def assess_current_turn(self, params: FunctionCallParams) -> None:
        """Answer one question: what did the caller just ask you to do?

        Returns a second opinion on their LAST sentence as a typed intent —
        book_appointment, reschedule_appointment, cancel_appointment,
        register_patient, ask_information, escalate, out_of_scope, other —
        plus whether it reads as a medical emergency and whether it is too
        ambiguous to act on.

        Call it when, and only when, you are about to act and you are not
        sure what they meant: a short reply to an offer you cannot read as
        yes or no ("bueno", "ya veremos", "go on then"), a sentence that
        might be a new request or a confirmation of the old one, or anything
        that might be an emergency. Do not call it when the caller was
        plain. It costs the caller half a second of silence.

        Takes no arguments: it reads the caller's own words from the call
        state, redacted, never anything you pass in. It is advisory — it
        never authorises or blocks anything, the real tools decide. If it
        abstains, carry on and ask the caller to clarify.
        """
        # The background reader has usually answered for this turn already;
        # reuse it rather than spend the caller's silence a second time.
        decision = self.ctx.latest_decision or await self._jev_assessment()
        self.ctx.latest_decision = decision
        await params.result_callback(decision)

    async def _jev_assessment(self, budget: float | None = None) -> dict[str, Any]:
        """Invoke redaction + Jev; return a PII-free advisory dict.

        ``budget`` overrides the per-call timeout. Background reads pass the
        wider one; a read the model is waiting on keeps the tight default,
        because that one is silence on the line.
        """
        from agent.decision.models import AbstentionReason, TurnDecision, TurnDecisionInput

        if self.jev is None:
            decision = TurnDecision(abstained=True, abstention_reason=AbstentionReason.MISSING_KEY)
            self.ctx.audit("jev_assessment", decision.as_audit_dict())
            return self._jev_result(decision)
        latest = self.ctx.latest_caller_turn
        if not latest:
            decision = TurnDecision(abstained=True, abstention_reason=AbstentionReason.EMPTY_STATE)
            self.ctx.audit("jev_assessment", decision.as_audit_dict())
            return self._jev_result(decision)
        # Local scrub of known names plus the decision layer's core regex
        # redaction (phones, ids, dates) applied here as defense in depth;
        # JevClient.build_payload runs the same redaction again before
        # anything leaves the host.
        from agent.decision.redaction import redact_text

        scrubbed = redact_text(_scrub_known_names(latest, self.ctx))
        snapshot = TurnDecisionInput.from_messages(
            [{"role": "caller", "text": scrubbed}],
            context={
                "phase": "scheduling",
                "identity_status": "confirmed" if self.ctx.confirmed_patient else "unconfirmed",
                "patient_confirmed": self.ctx.confirmed_patient is not None,
            },
        )
        try:
            decision = await self.jev.assess(
                snapshot, cancel=self.ctx.cancel_token, timeout_seconds=budget
            )
        except Exception:  # noqa: BLE001 - sidecar must never crash the call
            decision = TurnDecision(abstained=True, abstention_reason=AbstentionReason.TRANSPORT_ERROR)
        # Metadata only: intent/confidence/latency/usage. Never the transcript.
        self.ctx.audit("jev_assessment", decision.as_audit_dict())
        return self._jev_result(decision)

    @staticmethod
    def _jev_result(decision: Any) -> dict[str, Any]:
        """The answer the model needs, and nothing else.

        The full projection (source, model, latency, token counts) goes to
        the audit; handing it to the model as well buried the one field that
        matters under telemetry it cannot act on.
        """
        full = decision.as_audit_dict()
        # needs_clarification is deliberately NOT forwarded. Measured over
        # six probes it came back True every time, including on verdicts with
        # confidence 1.0 — handing the model "too ambiguous to act" on an
        # unambiguous booking would make it second-guess correct work. It
        # stays in the audit, where a wrong signal costs nothing.
        return {
            "intent": full.get("intent"),
            "medical_emergency": full.get("medical_emergency"),
            "confidence": full.get("confidence"),
            "abstained": full.get("abstained"),
            "message": (
                "A second opinion, not a decision: it never authorises or blocks "
                "anything. If it abstained, carry on with your own judgement and "
                "ask the caller to clarify if you still cannot tell."
            ),
        }

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
        registered = [
            self.lookup_patient,
            self.confirm_patient,
            self.list_my_appointments,
            self.find_availability,
            self.book_appointment,
            self.cancel_appointment,
            self.reschedule_appointment,
            self.register_new_patient,
            self.describe_clinic,
            self.find_nearest_site,
            self.finish_without_booking,
            self.escalate_call,
            self.get_reflow_context,
            self.commit_reflow_decision,
        ]
        if self.engine == "gemini_live":
            registered.append(self.assess_current_turn)
        return registered
