"""Product view: what happened on a call, in Spanish, for clinic staff.

`console.py` is the debugging console — raw events for whoever wrote them.
This is the other audience: a receptionist who wants to know who called, what
they asked for, which patient was confirmed, what the agent searched and what
it decided. Same JSONL on disk, different reader.

Two properties this module owes its callers:

Live. ``ctx.audit`` appends to ``DATA_DIR/<org_id>/calls/<call_id>.jsonl`` as each event
happens, so a call in progress is a file that is still growing. Reading it is
reading the call live; there is no second channel to build.

Cheap. The panel polls, and the process that answers may also be carrying a
scored call. Every trace is parsed once per (mtime, size) and a finished call
is therefore parsed exactly once for the life of the process.

Nothing here writes. Access is gated by `require_ops_access` from console.py —
the same door, never a second one.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from agent.config import settings
from agent.orgs import DEFAULT_ORG_ID, InvalidOrgId, normalize_org_id


def require_access(request: Request) -> None:
    """Delegate to the single door in `console.py`.

    Imported inside the function on purpose: `console` registers this router,
    so a module-level import here would be a cycle and would break depending
    on which of the two modules got imported first. The check itself is not
    duplicated — two doors is how one ends up open.
    """
    from agent.ops.console import require_ops_access

    require_ops_access(request)


router = APIRouter(dependencies=[Depends(require_access)])

# How many calls the list returns, newest first.
_MAX_CALLS = 40
# A trace with no closing event is only "in progress" while it is still being
# written. A live call is capped at three minutes and writes a line per
# transcript fragment, so it touches its file every few seconds; a minute of
# silence with no close record is a call that died, not one in progress, and
# telling a receptionist it is live is worse than saying it never closed.
_ACTIVE_WINDOW_SECONDS = 60.0


# ---- redaction -----------------------------------------------------------
# Problem 14 defines the protected fields as the target patient's national id
# and telephone. The name is deliberately NOT protected: it is what somebody
# says in order to make the request. So the name stays and the rest goes.
#
# This is the second layer. The first is redaction at the source, which is
# owned elsewhere; what is never sent cannot leak, and one door is how a door
# ends up open.
_NATIONAL_ID = re.compile(r"\b[XYZxyz]?\d{7,8}[-\s]?[A-Za-z]\b")
_PHONE_ES = re.compile(r"\b[6-9](?:[\s.\-]?\d){8}\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def redact(text: str) -> str:
    """Strip national ids, Spanish phone numbers and emails from free text.

    Callers dictate all three out loud, so they are in the transcript verbatim.
    Best effort by construction: a national id spelled out in words ("tres uno
    cuatro...") survives this, which is exactly why the source-side redaction
    exists too.
    """
    if not text:
        return text
    text = _EMAIL.sub("[email]", text)
    text = _NATIONAL_ID.sub("[DNI]", text)
    return _PHONE_ES.sub("[teléfono]", text)


# Allow-list, not a block-list: a field added upstream tomorrow is invisible
# here until somebody names it, which is the safe direction to fail.
_PUBLIC_FIELDS: dict[str, frozenset[str]] = {
    "register": frozenset({"given_name", "first_surname", "second_surname", "insurer"}),
    "book": frozenset({"provider_id", "location_id", "appointment_type_id", "slot", "policy_id"}),
    "reschedule": frozenset({"appointment_id", "provider_id", "location_id", "slot", "policy_id"}),
    "cancel": frozenset({"appointment_id"}),
    "no-action": frozenset({"reason"}),
    "escalate": frozenset({"reason"}),
}

_REASONS_ES = {
    "not_eligible_age": "la edad queda fuera de la franja",
    "referral_required": "hace falta volante",
    "provider_not_in_network": "el profesional está fuera de la red",
    "specialty_not_covered": "la especialidad no está cubierta",
    "location_not_covered": "el centro no está cubierto",
    "insurer_referral_required": "la póliza exige volante",
    "allowance_exhausted": "el cupo está agotado",
    "provider_on_leave": "el profesional está de baja",
    "location_hours": "fuera del horario del centro",
    "type_not_offered": "ese tipo de cita no se ofrece",
    "patient_history": "por el historial del paciente",
    "no_availability": "no hay hueco",
    "clinic_closed": "la clínica está cerrada",
    "patient_not_found": "no se encontró al paciente",
    "provider_not_found": "no se encontró al profesional",
    "caller_not_authorised": "quien llama no está autorizado",
    "out_of_scope": "la petición se sale de lo que atiende la clínica",
    "medical_emergency": "es una urgencia médica",
}


_SECTIONS_ES = {
    "sites": "las sedes",
    "doctors": "los médicos",
    "specialties": "las especialidades",
    "plans": "las pólizas",
}


def _join_es(items: list[str]) -> str:
    """"a, b y c" — a list a person reads, not a Python repr."""
    if len(items) <= 1:
        return items[0] if items else ""
    return f"{', '.join(items[:-1])} y {items[-1]}"


def _reason_es(reason: str | None) -> str:
    if not reason:
        return "sin motivo registrado"
    return _REASONS_ES.get(reason, reason)


# ---- catalogue names -----------------------------------------------------
# Warming is attempted at most once per process per organisation, successful
# or not: a failing warm must not turn a 3-second poll into 3-second outbound
# retries, and one unreachable clinic must not stop another one's names from
# ever being fetched.
_WARM_TRIED: set[str] = set()


async def _catalogue(org_id: str = DEFAULT_ORG_ID) -> Any | None:
    """This organisation's catalogue, warmed once if it is not already.

    Without this the panel says "PR10" and "norte" to a receptionist, which is
    the id of a doctor and the id of a site and means nothing to a person.
    The catalogue is immutable within an organisation, so this is one burst of
    requests for the life of the process — and when this module runs inside
    `agent.serve`, the server's lifespan has already warmed the cache of the
    organisation it serves and nothing is fetched at all.
    """
    try:
        from agent.brain import deps
    except (ImportError, AttributeError):
        return None
    cache = deps.try_catalogue_cache(org_id)
    if cache is None:
        return None
    if cache.warmed:
        return cache
    if org_id in _WARM_TRIED:
        return None
    _WARM_TRIED.add(org_id)
    # `ensure_catalogue_warm` owns the whole guarded path, the client
    # construction included: `deps.try_clinic_client` calls the constructor
    # outside its own try, so bad configuration raises out of it and would
    # reach a reader whose whole job is to answer. A cold catalogue degrades
    # to ids, never to a 500.
    return await deps.ensure_catalogue_warm(settings(), org_id)


def _name_of(cache: Any | None, kind: str, ident: str | None) -> str:
    """Resolve an id to its human name, falling back to the id itself."""
    if not ident:
        return "—"
    if cache is None:
        return ident
    getter = {
        "provider": "provider_by_id",
        "location": "location_by_id",
        "type": "type_by_id",
        "plan": "plan_by_id",
    }.get(kind)
    item = getattr(cache, getter)(ident) if getter else None
    return getattr(item, "name", None) or ident


# ---- narration -----------------------------------------------------------
# Plumbing: real events, but they describe the socket and not the appointment,
# and a receptionist reading them learns nothing.
_PLUMBING = frozenset({
    "call_context_created", "client_connected", "start_received", "call_id_bound",
    "engine_selected", "greeting_prepared", "socket_stop", "flush_start",
    "flush_done", "audio_bridge_metrics", "barge_in_reset", "turn_nudged",
    "turn_forced", "transcript",
})


def _narrate(event: str, data: dict[str, Any], cache: Any | None) -> str | None:
    """One trace event as one sentence, or None when it is plumbing."""
    if event in _PLUMBING:
        return None

    if event == "phone_hint":
        # A hint for the greeting, never proof of identity: the caller is only
        # identified at `identity_confirmed`, and saying otherwise here would
        # show a confirmation that did not happen.
        outcome = data.get("outcome")
        if outcome == "matched":
            return "El número entrante coincide con una ficha, todavía sin confirmar."
        if outcome == "ambiguous":
            return "El número entrante no coincide con ninguna ficha."
        return "No se pudo comprobar el número entrante."

    if event == "patient_lookup":
        count = data.get("count", 0)
        if count == 0:
            return "Buscó al paciente en el fichero y no encontró a nadie."
        if count == 1:
            return "Buscó al paciente en el fichero y encontró una coincidencia."
        return f"Buscó al paciente en el fichero: {count} coincidencias."

    if event == "identity_confirmed":
        # The security boundary of the call: before this line the agent may
        # not talk about the record. Worth reading as the event it is.
        name = str(data.get("given_name") or "").strip()
        return f"Confirmó la identidad de {name}." if name else "Confirmó la identidad del paciente."

    if event == "clinic_question":
        about = redact(str(data.get("about") or "").strip())
        answered = [_SECTIONS_ES.get(s, s) for s in data.get("answered") or []]
        asked = f' sobre "{about}"' if about else " sobre la clínica"
        if not answered:
            return f"Le preguntaron{asked} y no encontró nada que contestar."
        return f"Le preguntaron{asked} y respondió con {_join_es(answered)}."

    if event == "nearest_site":
        origin = redact(str(data.get("asked_from") or "").strip())
        where = f' a "{origin}"' if origin else ""
        chosen = data.get("chose")
        if not chosen:
            return f"Buscó la sede más cercana{where} y ninguna podía atender la petición."
        line = f"Buscó la sede más cercana{where} y eligió {_name_of(cache, 'location', chosen)}"
        km = data.get("km")
        if isinstance(km, int | float):
            line += f", a {km:.1f} km".replace(".", ",")
        closest = data.get("closest_overall")
        if closest and closest != chosen:
            # The whole point of problem 15: the nearest site is not the answer
            # when it cannot serve the request. Saying so is saying why.
            line += (
                f". La más cercana era {_name_of(cache, 'location', closest)}, "
                "pero no podía atender la petición"
            )
        return line + "."

    if event == "availability_query":
        asked = data.get("asked")
        slots = data.get("slots", 0)
        when = f' para "{asked}"' if asked else ""
        if slots == 0:
            # WHY there was nothing, not just that there was nothing. "No hay
            # hueco" and "su plan no cubre esa sede" are different answers, and
            # the second is the one a person at the desk can act on.
            rules = [_reason_es(r) for r in data.get("blocked") or []]
            if rules:
                return f"Buscó huecos{when} y no había ninguno libre: {_join_es(rules)}."
            return f"Buscó huecos{when} y no había ninguno libre."
        if slots == 1:
            return f"Buscó huecos{when}: 1 disponible."
        return f"Buscó huecos{when}: {slots} disponibles."

    if event == "plan_classified":
        return f"Identificó la póliza: {_name_of(cache, 'plan', data.get('plan_id'))}."

    if event == "refusal_deferred":
        return (
            "Iba a declinar la petición y primero preguntó si el paciente "
            "tiene una segunda póliza."
        )

    if event == "jev_assessment":
        if data.get("abstained"):
            return None
        if data.get("medical_emergency"):
            return "Detectó una posible urgencia médica."
        intent = data.get("intent")
        # "other" with nothing else attached is the model saying it has no
        # reading yet. Printing it four times in a row is noise, not insight.
        if not intent or intent == "other":
            return None
        if data.get("needs_clarification"):
            return f"Entendió la petición como «{intent}», pero le faltaba información."
        return f"Entendió la petición como «{intent}»."

    if event == "action_queued":
        return _narrate_action(data, cache)

    if event == "submitted":
        return "Envió la decisión a la clínica correctamente."

    if event == "submit_failed":
        return "El envío de la decisión a la clínica falló."

    if event == "tool":
        if data.get("ok") is False:
            return f"La consulta «{data.get('tool', '?')}» dio error."
        return None

    if event == "call_ended":
        seconds = data.get("elapsed_s")
        duration = f" Duró {seconds:.0f} segundos." if isinstance(seconds, int | float) else ""
        return f"La llamada terminó.{duration}"

    return None


def _narrate_action(data: dict[str, Any], cache: Any | None) -> str:
    """The decision itself, which is the line that matters most."""
    route = data.get("route")
    if route == "register":
        name = " ".join(
            str(data[k]) for k in ("given_name", "first_surname", "second_surname") if data.get(k)
        )
        who = f" a {name}" if name else ""
        plan = _name_of(cache, "plan", data.get("insurer"))
        return f"Dio de alta{who} como paciente nuevo, con póliza {plan}."
    if route == "book":
        return (
            f"Reservó cita con {_name_of(cache, 'provider', data.get('provider_id'))}"
            f" en {_name_of(cache, 'location', data.get('location_id'))}"
            f" para {_name_of(cache, 'type', data.get('appointment_type_id'))}."
        )
    if route == "reschedule":
        return f"Cambió la cita a otro hueco con {_name_of(cache, 'provider', data.get('provider_id'))}."
    if route == "cancel":
        return "Anuló la cita."
    if route == "no-action":
        return f"No hizo ninguna gestión: {_reason_es(data.get('reason'))}."
    if route == "escalate":
        return f"Pasó la llamada a una persona: {_reason_es(data.get('reason'))}."
    return "Registró una decisión que este panel no sabe describir."


# ---- trace reading -------------------------------------------------------
# path -> (mtime_ns, size, parsed). A finished call never changes, so it is
# parsed exactly once for the life of the process; only the call currently
# being written is ever re-read.
_CACHE: dict[str, tuple[int, int, dict[str, Any]]] = {}


def _parse(path: Path) -> dict[str, Any]:
    """Read one trace into everything both views need. Never raises on junk."""
    started_at = ""
    ended_at = ""
    elapsed: float | None = None
    ended = False
    transcripts = 0
    submitted = 0
    failed = 0
    emergency = False
    patient = ""
    raw_events: list[tuple[str, str, dict[str, Any]]] = []
    conversation: list[dict[str, str]] = []
    role = ""
    buffer: list[str] = []

    def flush_turn() -> None:
        if not buffer:
            return
        # Fragments arrive split by streaming and already carry their own
        # spacing ("Clínica Arenal, " + "good morning."), so they join with
        # nothing between them. Joining with a space doubles every gap.
        text = redact("".join(buffer).strip())
        buffer.clear()
        if text:
            conversation.append(
                {"speaker": "agente" if role == "assistant" else "paciente", "text": text}
            )

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        raw = ""

    for line in raw.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        event = record.get("event", "")
        data = record.get("data") or {}
        if not isinstance(data, dict):
            data = {}
        timestamp = str(record.get("ts", ""))
        if not started_at:
            started_at = timestamp

        if event == "transcript":
            transcripts += 1
            speaker = str(data.get("role", ""))
            if speaker != role:
                flush_turn()
                role = speaker
            buffer.append(str(data.get("text", "")))
            continue

        if event == "call_ended":
            ended = True
            ended_at = timestamp
            if isinstance(data.get("elapsed_s"), int | float):
                elapsed = float(data["elapsed_s"])
        elif event == "socket_stop":
            ended = True
            ended_at = ended_at or timestamp
        elif event == "jev_assessment" and data.get("medical_emergency"):
            emergency = True
        elif event == "submitted":
            submitted += 1
        elif event == "submit_failed":
            failed += 1
        elif event == "identity_confirmed" and not patient:
            # A registration carries the full name; a booking only ever had a
            # patient_id, which is why most rows used to read "unidentified".
            # The confirmed given name is the caller, and it is not protected.
            patient = str(data.get("given_name") or "").strip() or patient
        elif event == "action_queued" and data.get("route") == "register":
            name = " ".join(
                str(data[k])
                for k in ("given_name", "first_surname", "second_surname")
                if data.get(k)
            )
            patient = name or patient

        if event == "action_queued":
            route = str(data.get("route", ""))
            allowed = _PUBLIC_FIELDS.get(route, frozenset())
            data = {k: v for k, v in data.items() if k in allowed or k == "route"}
        raw_events.append((timestamp, event, data))

    flush_turn()
    return {
        "started_at": started_at,
        "ended_at": ended_at,
        "elapsed": elapsed,
        "ended": ended,
        "transcripts": transcripts,
        "submitted": submitted,
        "failed": failed,
        "emergency": emergency,
        "patient": patient,
        "raw_events": raw_events,
        "conversation": conversation,
    }


def _read(path: Path) -> dict[str, Any] | None:
    """Parsed trace, reusing the cached parse while the file has not changed."""
    key = str(path)
    try:
        stat = path.stat()
    except OSError:
        _CACHE.pop(key, None)
        return None
    hit = _CACHE.get(key)
    if hit is not None and hit[0] == stat.st_mtime_ns and hit[1] == stat.st_size:
        return hit[2]
    parsed = _parse(path)
    _CACHE[key] = (stat.st_mtime_ns, stat.st_size, parsed)
    return parsed


def _recent(limit: int, org_id: str = DEFAULT_ORG_ID) -> list[tuple[Path, float]]:
    """Newest traces first, with their mtime. One scandir pass per directory.

    An organisation has one directory of its own and, for the clinic that
    predates organisations, a second one holding everything recorded before
    this layout existed. A call id appearing in both is the same call: the
    current layout wins and the older copy is dropped.
    """
    entries: dict[str, os.DirEntry] = {}
    for calls_dir in settings().call_trace_dirs(org_id):
        try:
            for entry in os.scandir(calls_dir):
                if entry.name.endswith(".jsonl") and entry.is_file():
                    entries.setdefault(entry.name, entry)
        except OSError:
            continue
    ordered = sorted(entries.values(), key=lambda e: e.stat().st_mtime_ns, reverse=True)
    found = [(Path(e.path), e.stat().st_mtime) for e in ordered[:limit]]
    live = {str(p) for p, _ in found}
    for stale in [k for k in _CACHE if k not in live]:
        del _CACHE[stale]
    return found


def _status(parsed: dict[str, Any], mtime: float, now: float) -> str:
    if parsed["ended"]:
        return "finalizada"
    if now - mtime <= _ACTIVE_WINDOW_SECONDS:
        return "en curso"
    return "sin cierre"


def _duration(parsed: dict[str, Any]) -> int | None:
    if parsed["elapsed"] is not None:
        return round(parsed["elapsed"])
    return None


# ---- routes --------------------------------------------------------------
def _org_of(raw: str) -> str:
    """The organisation a request asks for. An unknown shape is a 400, never a path."""
    try:
        return normalize_org_id(raw)
    except InvalidOrgId as exc:
        raise HTTPException(400, "organización no válida") from exc


@router.get("/ops/api/live/calls")
async def live_calls(org: str = DEFAULT_ORG_ID) -> list[dict[str, Any]]:
    """Recent calls, newest first, as a receptionist would skim them.

    Calls with no transcript at all are left out: 24 of the 164 traces on disk
    are sockets that opened and never produced a word, and they tell a person
    at the front desk nothing.

    `org` defaults to the one clinic this process serves, so a panel that
    knows nothing about organisations sees exactly what it always saw. Until
    there are sessions (PLATFORM.md step 4) it is the whole of the tenancy
    boundary on this route — it is behind the ops door and nothing more.
    """
    org_id = _org_of(org)
    now = time.time()
    cache = await _catalogue(org_id)
    out: list[dict[str, Any]] = []
    for path, mtime in _recent(_MAX_CALLS, org_id):
        parsed = _read(path)
        if parsed is None or parsed["transcripts"] == 0:
            continue
        headline = ""
        for _ts, event, data in reversed(parsed["raw_events"]):
            if event == "action_queued":
                headline = _narrate(event, data, cache) or ""
                break
            if event == "submitted" and not headline:
                # flush.py refuses to end a call silently: with nothing queued
                # it submits a no-action itself, and that submission is the
                # only trace of it. The call did have an outcome.
                headline = "No registró ninguna decisión; se envió un cierre automático."
        out.append(
            {
                "call_id": path.stem,
                "status": _status(parsed, mtime, now),
                "started_at": parsed["started_at"],
                "ended_at": parsed["ended_at"] or None,
                "duration_seconds": _duration(parsed),
                "patient": parsed["patient"] or None,
                # The one thing on this screen that may need a person to move,
                # so it belongs on the row and not three clicks in.
                "medical_emergency": parsed["emergency"],
                "headline": headline or "Todavía sin decisión registrada.",
                "turns": len(parsed["conversation"]),
                "submissions_ok": parsed["submitted"],
                "submissions_failed": parsed["failed"],
            }
        )
    return out


@router.get("/ops/api/live/calls/{call_id}")
async def live_call(call_id: str, org: str = DEFAULT_ORG_ID) -> dict[str, Any]:
    """One call: the conversation and the story of the decision, in Spanish."""
    # The id lands in a filesystem path, so it may only ever be a bare name.
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", call_id) or call_id.startswith("."):
        raise HTTPException(400, "identificador de llamada no válido")
    org_id = _org_of(org)
    path = settings().call_trace_path(call_id, org_id)
    parsed = _read(path)
    if parsed is None:
        raise HTTPException(404, "llamada no encontrada")
    cache = await _catalogue(org_id)
    now = time.time()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    events: list[dict[str, str]] = []
    for timestamp, event, data in parsed["raw_events"]:
        sentence = _narrate(event, data, cache)
        if not sentence:
            continue
        # The same reading is re-emitted on every turn while it holds. Saying
        # it four times running reads as a stutter, not as four findings.
        if events and events[-1]["text"] == sentence:
            continue
        events.append({"at": timestamp[11:19], "text": sentence})
    return {
        "call_id": call_id,
        "status": _status(parsed, mtime, now),
        "started_at": parsed["started_at"],
        "ended_at": parsed["ended_at"] or None,
        "duration_seconds": _duration(parsed),
        "patient": parsed["patient"] or None,
        "medical_emergency": parsed["emergency"],
        "events": events,
        "conversation": parsed["conversation"],
        "submissions_ok": parsed["submitted"],
        "submissions_failed": parsed["failed"],
    }
