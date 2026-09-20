"""Reads and writes over the four tables. The only module that speaks SQL.

Everything above this file — the login routes, the ops console, the clinic
client — talks in `User`, `Organization`, `Membership` and `Session` and
never in rows. That is what makes the choice in `db.py` reversible: if this
ever moves to Postgres, this file changes and nothing else does.

Two rules this module enforces and does not delegate:

1. **A decrypted Prosper key leaves here exactly once**, through
   `organization_api_key`, and only into a client that is about to call the
   clinic. Every other accessor returns a fingerprint. There is no method
   that returns a key for display, so there is no route that can accidentally
   serve one.
2. **Membership is the tenancy boundary.** `role_in` is the single answer to
   "may this person see this clinic", and a session may only be switched to
   an organisation the person is actually in.
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent.accounts import secrets as crypto
from agent.accounts.db import connect, migrate, now_iso
from agent.orgs import normalize_org_id

# owner can do everything including handing out roles; admin may write the
# clinic's credential; member reads the console. Deliberately three, and
# deliberately checked in one place.
ROLES = ("owner", "admin", "member")
CREDENTIAL_ROLES = frozenset({"owner", "admin"})

# A console session. Long enough for a working day, short enough that a
# forgotten laptop is not a standing invitation.
SESSION_TTL = timedelta(hours=12)

# How stale `last_seen_at` may get before a read bothers to refresh it.
LAST_SEEN_RESOLUTION = timedelta(minutes=1)


def _older_than(stamp: str, age: timedelta) -> bool:
    """True when `stamp` is further in the past than `age`, or unreadable."""
    try:
        return datetime.fromisoformat(stamp) < datetime.now(UTC) - age
    except (TypeError, ValueError):
        return True


# A slug is an id a route points at and a node the graph draws. Same shape as
# an organisation id, and for the same reason: it must never be able to be
# anything but a bare name.
_SLUG = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")


def normalize_slug(raw: str) -> str:
    """Canonical person slug, or StoreError. Never a path, never a blank."""
    value = (raw or "").strip().lower()
    if not _SLUG.fullmatch(value):
        raise StoreError(f"invalid person id: {raw!r}")
    return value


class StoreError(RuntimeError):
    """A rule of this layer was broken: unknown org, duplicate email, bad role."""


def _incident_row(row: Any) -> Incident:
    return Incident(
        id=row["id"],
        reason=row["reason"],
        summary=row["summary"],
        assigned_to=row["assigned_to"],
        urgency=row["urgency"],
        status=row["status"],
        source=row["source"],
        call_id=row["call_id"],
        patient=row["patient"],
        note=row["note"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        closed_at=row["closed_at"],
    )


@dataclass(frozen=True)
class PatientRow:
    """Un paciente que la clínica ha visto de verdad.

    Sin documento ni teléfono, la misma regla que sigue `PatientCard`: este
    fichero acaba dentro de una copia de seguridad, y lo que no se guarda no
    se filtra.
    """

    patient_id: str
    given_name: str = ""
    first_surname: str = ""
    second_surname: str = ""
    date_of_birth: str = ""
    sex: str = ""
    insurer: str = ""
    has_visited_before: bool = False
    referrals: tuple[str, ...] = ()
    note: str = ""
    likely_specialty: str = ""
    likely_confidence: float = 0.0
    times_seen: int = 1
    first_seen_at: str = ""
    last_seen_at: str = ""

    @property
    def name(self) -> str:
        return " ".join(
            part for part in (self.given_name, self.first_surname, self.second_surname) if part
        )


@dataclass(frozen=True)
class CoverShift:
    """Un turno que alguien se ha comprometido a cubrir, por teléfono.

    No es una cita. Una cita es de un paciente y vive en la API de Prosper;
    esto es de la clínica y de su gente. `covers_when` es texto y no una
    fecha a propósito: lo que se dice por teléfono es "el martes por la
    mañana", y convertirlo aquí en una hora sería inventarse una que nadie
    ha dicho.
    """

    id: str
    person_slug: str
    person_name: str = ""
    covers_when: str = ""
    site: str = ""
    instead_of: str = ""
    reason: str = ""
    incident_id: str = ""
    call_id: str = ""
    note: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class Incident:
    """Algo que ha ido mal, mientras va mal.

    Nace de una llamada que acaba sin cita o de alguien que lo escribe en el
    panel, y vive hasta que una persona la cierra. `assigned_to` es el slug
    de quien tiene que ocuparse, resuelto por la misma tabla de rutas que
    decide a quién llama el agente — así que la incidencia y la llamada
    apuntan siempre a la misma persona.
    """

    id: str
    reason: str
    summary: str = ""
    assigned_to: str = ""
    urgency: str = "today"
    status: str = "open"  # open | acknowledged | closed
    source: str = "panel"  # panel | agent
    call_id: str = ""
    patient: str = ""
    note: str = ""
    created_at: str = ""
    updated_at: str = ""
    closed_at: str | None = None


@dataclass(frozen=True)
class Organization:
    id: str
    name: str
    created_at: str
    # Never the key. `has_credential` answers "is one loaded", `fingerprint`
    # answers "which one", and neither is usable as a credential.
    has_credential: bool = False
    credential_fingerprint: str = ""
    credentials_updated_at: str | None = None


@dataclass(frozen=True)
class User:
    id: str
    email: str
    display_name: str
    created_at: str
    disabled: bool = False


@dataclass(frozen=True)
class Membership:
    user_id: str
    org_id: str
    org_name: str
    role: str


@dataclass(frozen=True)
class Person:
    """Somebody the clinic can ring, and how this agent should ring them.

    Everything after `provider_id` is the call profile: it belongs to the
    person and not to the deployment, so two colleagues on the same line can
    be opened differently, in different languages, with different things the
    agent is allowed to ask them.

    `source` is "configured" for a row and "default" for one of the four roles
    `clinic/graph.py` declares by hand. It is what lets a panel show "nobody
    has set this up yet" instead of pretending somebody did.
    """

    slug: str
    name: str
    role: str
    detail: str = ""
    languages: tuple[str, ...] = ()
    provider_id: str | None = None
    # Staff contact details. Shown to members of this organisation; never put
    # into a model prompt, which is why `directory.cover_brief` does not carry
    # them. Ringing somebody is a thing a person does with this, not the agent.
    phone: str = ""
    email: str = ""
    # The call profile.
    opening: str = ""
    may_ask: tuple[str, ...] = ()
    must_not_ask: tuple[str, ...] = ()
    # Whose absence this person covers. The dependency the clinic runs on and
    # the one thing no catalogue has ever known.
    covers_for: str = ""
    # La voz de Gemini con la que la clínica llama a esta persona. Vacío usa
    # la del despliegue, que es como se comportaba antes de existir.
    voice: str = ""
    active: bool = True
    source: str = "configured"


@dataclass(frozen=True)
class Route:
    """One of the eighteen endings, and who hears about it in this clinic."""

    reason: str
    person_slug: str
    urgency: str
    detail: str = ""
    source: str = "configured"


@dataclass(frozen=True)
class Session:
    user_id: str
    current_org_id: str
    created_at: str
    expires_at: str


def _org_row(row: sqlite3.Row) -> Organization:
    return Organization(
        id=row["id"],
        name=row["name"],
        created_at=row["created_at"],
        has_credential=bool(row["prosper_api_key_encrypted"]),
        credential_fingerprint=row["prosper_api_key_fingerprint"] or "",
        credentials_updated_at=row["credentials_updated_at"],
    )


def _split(raw: str | None) -> tuple[str, ...]:
    """A stored list. Commas for language codes, newlines for sentences."""
    text = (raw or "").strip()
    if not text:
        return ()
    separator = "\n" if "\n" in text else ","
    return tuple(part.strip() for part in text.split(separator) if part.strip())


def _optional(row: sqlite3.Row, column: str) -> str:
    """A column that may predate the migration that added it."""
    try:
        return str(row[column] or "")
    except (IndexError, KeyError):
        return ""


def _person_row(row: sqlite3.Row) -> Person:
    return Person(
        slug=row["slug"],
        name=row["name"],
        role=row["role"],
        detail=row["detail"],
        languages=_split(row["languages"]),
        provider_id=row["provider_id"] or None,
        phone=row["phone"],
        email=row["email"],
        opening=row["opening"],
        may_ask=_split(row["may_ask"]),
        must_not_ask=_split(row["must_not_ask"]),
        covers_for=_optional(row, "covers_for"),
        voice=_optional(row, "voice"),
        active=bool(row["active"]),
    )


def _user_row(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        email=row["email"],
        display_name=row["display_name"],
        created_at=row["created_at"],
        disabled=bool(row["disabled_at"]),
    )


class Store:
    """One database file. Cheap to construct; holds no connection."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def migrate(self) -> int:
        return migrate(self.path)

    @property
    def exists(self) -> bool:
        return self.path.exists()

    # ---- organisations ---------------------------------------------------
    def create_organization(self, org_id: str, name: str) -> Organization:
        org_id = normalize_org_id(org_id)
        with connect(self.path) as db:
            try:
                db.execute(
                    "INSERT INTO organizations (id, name, created_at) VALUES (?, ?, ?)",
                    (org_id, name.strip() or org_id, now_iso()),
                )
            except sqlite3.IntegrityError as exc:
                raise StoreError(f"organisation {org_id!r} already exists") from exc
        found = self.get_organization(org_id)
        assert found is not None
        return found

    def get_organization(self, org_id: str) -> Organization | None:
        with connect(self.path) as db:
            row = db.execute(
                "SELECT * FROM organizations WHERE id = ?", (normalize_org_id(org_id),)
            ).fetchone()
        return _org_row(row) if row else None

    def list_organizations(self) -> list[Organization]:
        with connect(self.path) as db:
            rows = db.execute("SELECT * FROM organizations ORDER BY name").fetchall()
        return [_org_row(row) for row in rows]

    def set_organization_credential(self, org_id: str, api_key: str, key_material: str) -> Organization:
        """Encrypt and store a clinic's Prosper key. Write-only by design.

        Raises `SecretsUnavailable` when `OPS_SECRET_KEY` is not configured —
        refusing to store a credential is the only safe failure here. The
        alternative, writing it in the clear onto the volume, is how a backup
        becomes a breach.
        """
        org_id = normalize_org_id(org_id)
        api_key = (api_key or "").strip()
        if not api_key:
            raise StoreError("empty API key")
        blob = crypto.encrypt_secret(api_key, key_material, aad=org_id)
        with connect(self.path) as db:
            changed = db.execute(
                """UPDATE organizations
                      SET prosper_api_key_encrypted = ?,
                          prosper_api_key_fingerprint = ?,
                          credentials_updated_at = ?
                    WHERE id = ?""",
                (blob, crypto.fingerprint(api_key), now_iso(), org_id),
            ).rowcount
        if not changed:
            raise StoreError(f"unknown organisation {org_id!r}")
        found = self.get_organization(org_id)
        assert found is not None
        return found

    def clear_organization_credential(self, org_id: str) -> None:
        """Back to the environment's key for the default clinic, nothing for others."""
        with connect(self.path) as db:
            db.execute(
                """UPDATE organizations
                      SET prosper_api_key_encrypted = NULL,
                          prosper_api_key_fingerprint = NULL,
                          credentials_updated_at = ?
                    WHERE id = ?""",
                (now_iso(), normalize_org_id(org_id)),
            )

    def organization_api_key(self, org_id: str, key_material: str) -> str | None:
        """The clinic's own key in the clear, or None when it has none.

        The one place a credential is decrypted. Callers hand it straight to
        `ProsperClient` and must not log it, return it or trace it.
        """
        with connect(self.path) as db:
            row = db.execute(
                "SELECT prosper_api_key_encrypted FROM organizations WHERE id = ?",
                (normalize_org_id(org_id),),
            ).fetchone()
        if row is None or not row["prosper_api_key_encrypted"]:
            return None
        return crypto.decrypt_secret(
            row["prosper_api_key_encrypted"], key_material, aad=normalize_org_id(org_id)
        )

    # ---- people ----------------------------------------------------------
    def upsert_person(self, org_id: str, person: Person) -> Person:
        """Create or replace one person. The slug is the identity, not the name.

        A name changes; a route pointing at somebody must not break because
        somebody married. So routes reference the slug and this is an upsert
        on (org_id, slug).
        """
        org_id = normalize_org_id(org_id)
        slug = normalize_slug(person.slug)
        if not person.name.strip():
            raise StoreError("a person needs a name")
        if self.get_organization(org_id) is None:
            raise StoreError(f"unknown organisation {org_id!r}")
        stamp = now_iso()
        with connect(self.path) as db:
            db.execute(
                """INSERT INTO people (id, org_id, slug, name, role, detail, languages,
                                       provider_id, phone, email, opening, may_ask,
                                       must_not_ask, covers_for, voice, active,
                                       created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(org_id, slug) DO UPDATE SET
                       name = excluded.name, role = excluded.role,
                       detail = excluded.detail, languages = excluded.languages,
                       provider_id = excluded.provider_id, phone = excluded.phone,
                       email = excluded.email, opening = excluded.opening,
                       may_ask = excluded.may_ask, must_not_ask = excluded.must_not_ask,
                       covers_for = excluded.covers_for, voice = excluded.voice,
                       active = excluded.active, updated_at = excluded.updated_at""",
                (
                    uuid.uuid4().hex,
                    org_id,
                    slug,
                    person.name.strip(),
                    person.role.strip() or "other",
                    person.detail.strip(),
                    ",".join(person.languages),
                    (person.provider_id or "").strip() or None,
                    person.phone.strip(),
                    person.email.strip(),
                    person.opening.strip(),
                    "\n".join(person.may_ask),
                    "\n".join(person.must_not_ask),
                    person.covers_for.strip(),
                    person.voice.strip(),
                    1 if person.active else 0,
                    stamp,
                    stamp,
                ),
            )
        found = self.get_person(org_id, slug)
        assert found is not None
        return found

    def get_person(self, org_id: str, slug: str) -> Person | None:
        with connect(self.path) as db:
            row = db.execute(
                "SELECT * FROM people WHERE org_id = ? AND slug = ?",
                (normalize_org_id(org_id), (slug or "").strip().lower()),
            ).fetchone()
        return _person_row(row) if row else None

    def list_people(self, org_id: str) -> list[Person]:
        """Configured people only. The defaults are layered on in `directory`."""
        with connect(self.path) as db:
            rows = db.execute(
                "SELECT * FROM people WHERE org_id = ? ORDER BY name",
                (normalize_org_id(org_id),),
            ).fetchall()
        return [_person_row(row) for row in rows]

    def delete_person(self, org_id: str, slug: str) -> bool:
        """Remove a person. Routes pointing at them fall back to the default."""
        with connect(self.path) as db:
            return bool(
                db.execute(
                    "DELETE FROM people WHERE org_id = ? AND slug = ?",
                    (normalize_org_id(org_id), (slug or "").strip().lower()),
                ).rowcount
            )

    # ---- routes ----------------------------------------------------------
    def upsert_route(self, org_id: str, route: Route) -> Route:
        """Point one of the eighteen reasons at somebody, with an urgency."""
        org_id = normalize_org_id(org_id)
        if self.get_organization(org_id) is None:
            raise StoreError(f"unknown organisation {org_id!r}")
        with connect(self.path) as db:
            db.execute(
                """INSERT INTO routes (org_id, reason, person_slug, urgency, detail, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(org_id, reason) DO UPDATE SET
                       person_slug = excluded.person_slug, urgency = excluded.urgency,
                       detail = excluded.detail, updated_at = excluded.updated_at""",
                (
                    org_id,
                    route.reason,
                    normalize_slug(route.person_slug),
                    route.urgency,
                    route.detail.strip(),
                    now_iso(),
                ),
            )
        found = self.get_route(org_id, route.reason)
        assert found is not None
        return found

    def get_route(self, org_id: str, reason: str) -> Route | None:
        with connect(self.path) as db:
            row = db.execute(
                "SELECT * FROM routes WHERE org_id = ? AND reason = ?",
                (normalize_org_id(org_id), reason),
            ).fetchone()
        if row is None:
            return None
        return Route(
            reason=row["reason"],
            person_slug=row["person_slug"],
            urgency=row["urgency"],
            detail=row["detail"],
        )

    def list_routes(self, org_id: str) -> list[Route]:
        """Configured routes only. `directory` overlays them on the defaults."""
        with connect(self.path) as db:
            rows = db.execute(
                "SELECT * FROM routes WHERE org_id = ? ORDER BY reason",
                (normalize_org_id(org_id),),
            ).fetchall()
        return [
            Route(
                reason=row["reason"],
                person_slug=row["person_slug"],
                urgency=row["urgency"],
                detail=row["detail"],
            )
            for row in rows
        ]

    def delete_route(self, org_id: str, reason: str) -> bool:
        """Back to the hand-written route. A reason is never left with nobody."""
        with connect(self.path) as db:
            return bool(
                db.execute(
                    "DELETE FROM routes WHERE org_id = ? AND reason = ?",
                    (normalize_org_id(org_id), reason),
                ).rowcount
            )


    # ---- incidents -------------------------------------------------------
    def open_incident(self, org_id: str, incident: Incident) -> Incident:
        """Abre una incidencia. Devuelve la fila tal y como ha quedado."""
        now = now_iso()
        row = Incident(
            id=incident.id or f"inc-{uuid.uuid4().hex[:12]}",
            reason=incident.reason,
            summary=incident.summary,
            assigned_to=incident.assigned_to,
            urgency=incident.urgency or "today",
            status=incident.status or "open",
            source=incident.source or "panel",
            call_id=incident.call_id,
            patient=incident.patient,
            note=incident.note,
            created_at=now,
            updated_at=now,
            closed_at=None,
        )
        with connect(self.path) as db:
            db.execute(
                """
                INSERT INTO incidents (
                    id, org_id, reason, summary, assigned_to, urgency, status,
                    source, call_id, patient, note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.id,
                    normalize_org_id(org_id),
                    row.reason,
                    row.summary,
                    row.assigned_to,
                    row.urgency,
                    row.status,
                    row.source,
                    row.call_id,
                    row.patient,
                    row.note,
                    row.created_at,
                    row.updated_at,
                ),
            )
        return row

    def list_incidents(self, org_id: str, *, status: str = "", limit: int = 100) -> list[Incident]:
        """Las más recientes primero. `status` vacío las trae todas."""
        sql = "SELECT * FROM incidents WHERE org_id = ?"
        args: list[Any] = [normalize_org_id(org_id)]
        if status:
            sql += " AND status = ?"
            args.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(max(1, min(int(limit), 500)))
        with connect(self.path) as db:
            return [_incident_row(row) for row in db.execute(sql, args)]

    def set_incident_status(
        self, org_id: str, incident_id: str, status: str, *, note: str = ""
    ) -> Incident | None:
        """Mueve una incidencia de estado. `closed` sella la hora."""
        if status not in {"open", "acknowledged", "closed"}:
            raise ValueError(f"estado desconocido: {status!r}")
        now = now_iso()
        with connect(self.path) as db:
            changed = db.execute(
                """
                UPDATE incidents
                   SET status = ?,
                       note = CASE WHEN ? = '' THEN note ELSE ? END,
                       updated_at = ?,
                       closed_at = CASE WHEN ? = 'closed' THEN ? ELSE NULL END
                 WHERE org_id = ? AND id = ?
                """,
                (status, note, note, now, status, now, normalize_org_id(org_id), incident_id),
            ).rowcount
            if not changed:
                return None
            row = db.execute(
                "SELECT * FROM incidents WHERE org_id = ? AND id = ?",
                (normalize_org_id(org_id), incident_id),
            ).fetchone()
        return _incident_row(row) if row is not None else None

    # ---- pacientes vistos ------------------------------------------------
    def remember_patient(self, org_id: str, row: PatientRow) -> None:
        """Apunta que esta clínica ha visto a este paciente. Idempotente.

        Un segundo encuentro no reemplaza lo que ya se sabía: suma una visita
        y refresca la fecha. Y lo que llega vacío no borra lo que había — una
        búsqueda por documento devuelve menos campos que una por nombre, y la
        segunda no puede vaciar lo que trajo la primera.
        """
        if not row.patient_id:
            return
        stamp = now_iso()
        with connect(self.path) as db:
            db.execute(
                """INSERT INTO patients (
                        patient_id, org_id, given_name, first_surname, second_surname,
                        date_of_birth, sex, insurer, has_visited_before, referrals, note,
                        likely_specialty, likely_confidence, times_seen,
                        first_seen_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                   ON CONFLICT(org_id, patient_id) DO UPDATE SET
                       given_name = CASE WHEN excluded.given_name = '' THEN given_name
                                         ELSE excluded.given_name END,
                       first_surname = CASE WHEN excluded.first_surname = '' THEN first_surname
                                            ELSE excluded.first_surname END,
                       second_surname = CASE WHEN excluded.second_surname = '' THEN second_surname
                                             ELSE excluded.second_surname END,
                       date_of_birth = CASE WHEN excluded.date_of_birth = '' THEN date_of_birth
                                            ELSE excluded.date_of_birth END,
                       sex = CASE WHEN excluded.sex = '' THEN sex ELSE excluded.sex END,
                       insurer = CASE WHEN excluded.insurer = '' THEN insurer
                                      ELSE excluded.insurer END,
                       has_visited_before = MAX(has_visited_before, excluded.has_visited_before),
                       referrals = CASE WHEN excluded.referrals = '' THEN referrals
                                        ELSE excluded.referrals END,
                       note = CASE WHEN excluded.note = '' THEN note ELSE excluded.note END,
                       likely_specialty = CASE WHEN excluded.likely_specialty = ''
                                               THEN likely_specialty
                                               ELSE excluded.likely_specialty END,
                       likely_confidence = CASE WHEN excluded.likely_specialty = ''
                                                THEN likely_confidence
                                                ELSE excluded.likely_confidence END,
                       times_seen = times_seen + 1,
                       last_seen_at = excluded.last_seen_at""",
                (
                    row.patient_id,
                    normalize_org_id(org_id),
                    row.given_name,
                    row.first_surname,
                    row.second_surname,
                    row.date_of_birth,
                    row.sex,
                    row.insurer,
                    1 if row.has_visited_before else 0,
                    "\n".join(row.referrals),
                    row.note,
                    row.likely_specialty,
                    float(row.likely_confidence),
                    stamp,
                    stamp,
                ),
            )

    def list_patients(self, org_id: str, *, query: str = "", limit: int = 200) -> list[PatientRow]:
        """Los vistos, el último primero. `query` filtra por nombre o aseguradora."""
        sql = "SELECT * FROM patients WHERE org_id = ?"
        args: list[Any] = [normalize_org_id(org_id)]
        if query.strip():
            like = f"%{query.strip().lower()}%"
            sql += (
                " AND (lower(given_name) LIKE ? OR lower(first_surname) LIKE ?"
                " OR lower(second_surname) LIKE ? OR lower(insurer) LIKE ?"
                " OR lower(likely_specialty) LIKE ?)"
            )
            args += [like, like, like, like, like]
        sql += " ORDER BY last_seen_at DESC LIMIT ?"
        args.append(max(1, min(int(limit), 500)))
        with connect(self.path) as db:
            rows = db.execute(sql, args).fetchall()
        return [
            PatientRow(
                patient_id=r["patient_id"],
                given_name=r["given_name"],
                first_surname=r["first_surname"],
                second_surname=r["second_surname"],
                date_of_birth=r["date_of_birth"],
                sex=r["sex"],
                insurer=r["insurer"],
                has_visited_before=bool(r["has_visited_before"]),
                referrals=_split(r["referrals"]),
                note=r["note"],
                likely_specialty=r["likely_specialty"],
                likely_confidence=float(r["likely_confidence"]),
                times_seen=int(r["times_seen"]),
                first_seen_at=r["first_seen_at"],
                last_seen_at=r["last_seen_at"],
            )
            for r in rows
        ]

    # ---- turnos cubiertos ------------------------------------------------
    def record_cover_shift(self, org_id: str, shift: CoverShift) -> CoverShift:
        """Apunta que alguien cubre un turno. Nunca reemplaza: es un registro."""
        row = CoverShift(
            id=shift.id or f"cov-{uuid.uuid4().hex[:12]}",
            person_slug=shift.person_slug,
            person_name=shift.person_name,
            covers_when=shift.covers_when,
            site=shift.site,
            instead_of=shift.instead_of,
            reason=shift.reason,
            incident_id=shift.incident_id,
            call_id=shift.call_id,
            note=shift.note,
            created_at=now_iso(),
        )
        with connect(self.path) as db:
            db.execute(
                """INSERT INTO cover_shifts (id, org_id, person_slug, person_name,
                                             covers_when, site, instead_of, reason,
                                             incident_id, call_id, note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row.id,
                    normalize_org_id(org_id),
                    row.person_slug,
                    row.person_name,
                    row.covers_when,
                    row.site,
                    row.instead_of,
                    row.reason,
                    row.incident_id,
                    row.call_id,
                    row.note,
                    row.created_at,
                ),
            )
        return row

    def list_cover_shifts(self, org_id: str, *, limit: int = 100) -> list[CoverShift]:
        with connect(self.path) as db:
            rows = db.execute(
                "SELECT * FROM cover_shifts WHERE org_id = ? ORDER BY created_at DESC LIMIT ?",
                (normalize_org_id(org_id), max(1, min(int(limit), 500))),
            ).fetchall()
        return [
            CoverShift(
                id=r["id"],
                person_slug=r["person_slug"],
                person_name=r["person_name"],
                covers_when=r["covers_when"],
                site=r["site"],
                instead_of=r["instead_of"],
                reason=r["reason"],
                incident_id=r["incident_id"],
                call_id=r["call_id"],
                note=r["note"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def reassign_incident(self, org_id: str, incident_id: str, slug: str) -> bool:
        """Pasa una incidencia a otra persona, sin tocar su estado ni su nota."""
        with connect(self.path) as db:
            return bool(
                db.execute(
                    "UPDATE incidents SET assigned_to = ?, updated_at = ? "
                    "WHERE org_id = ? AND id = ?",
                    (slug, now_iso(), normalize_org_id(org_id), incident_id),
                ).rowcount
            )

    # ---- users -----------------------------------------------------------
    def create_user(self, email: str, password: str, display_name: str = "") -> User:
        email = (email or "").strip().lower()
        if "@" not in email:
            raise StoreError(f"not an email address: {email!r}")
        row_id = uuid.uuid4().hex
        with connect(self.path) as db:
            try:
                db.execute(
                    """INSERT INTO users (id, email, display_name, password_hash, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        row_id,
                        email,
                        (display_name or "").strip() or email.split("@")[0],
                        crypto.hash_password(password),
                        now_iso(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise StoreError(f"a user with email {email!r} already exists") from exc
        found = self.get_user(row_id)
        assert found is not None
        return found

    def get_user(self, user_id: str) -> User | None:
        with connect(self.path) as db:
            row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _user_row(row) if row else None

    def get_user_by_email(self, email: str) -> User | None:
        with connect(self.path) as db:
            row = db.execute(
                "SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),)
            ).fetchone()
        return _user_row(row) if row else None

    def user_count(self) -> int:
        """How many people exist. Zero is what "nobody has been provisioned" means."""
        with connect(self.path) as db:
            return int(db.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def set_password(self, user_id: str, password: str) -> None:
        with connect(self.path) as db:
            db.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (crypto.hash_password(password), user_id),
            )
        # A password change ends every session that password opened.
        self.delete_sessions_of(user_id)

    def authenticate(self, email: str, password: str) -> User | None:
        """The password check. One answer for "no such user" and "wrong password".

        A disabled account fails the same way. Telling a stranger which of the
        three it was is telling them which emails exist here.
        """
        with connect(self.path) as db:
            row = db.execute(
                "SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),)
            ).fetchone()
        if row is None:
            # Spend the same time as a real check so the answer does not time
            # differently for an address that exists.
            crypto.verify_password(password or "", crypto.hash_password("placeholder"))
            return None
        if row["disabled_at"]:
            return None
        if not crypto.verify_password(password or "", row["password_hash"]):
            return None
        return _user_row(row)

    # ---- memberships -----------------------------------------------------
    def add_membership(self, user_id: str, org_id: str, role: str = "member") -> Membership:
        if role not in ROLES:
            raise StoreError(f"unknown role {role!r}; expected one of {ROLES}")
        org_id = normalize_org_id(org_id)
        with connect(self.path) as db:
            try:
                db.execute(
                    """INSERT INTO memberships (user_id, org_id, role, created_at)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(user_id, org_id) DO UPDATE SET role = excluded.role""",
                    (user_id, org_id, role, now_iso()),
                )
            except sqlite3.IntegrityError as exc:
                raise StoreError("unknown user or organisation") from exc
        found = self.role_in(user_id, org_id)
        return Membership(
            user_id=user_id,
            org_id=org_id,
            org_name=(self.get_organization(org_id) or Organization(org_id, org_id, "")).name,
            role=found or role,
        )

    def remove_membership(self, user_id: str, org_id: str) -> None:
        with connect(self.path) as db:
            db.execute(
                "DELETE FROM memberships WHERE user_id = ? AND org_id = ?",
                (user_id, normalize_org_id(org_id)),
            )

    def memberships_of(self, user_id: str) -> list[Membership]:
        """Every clinic this person may switch to, in the order a menu shows them."""
        with connect(self.path) as db:
            rows = db.execute(
                """SELECT m.user_id, m.org_id, m.role, o.name AS org_name
                     FROM memberships m
                     JOIN organizations o ON o.id = m.org_id
                    WHERE m.user_id = ?
                    ORDER BY o.name""",
                (user_id,),
            ).fetchall()
        return [
            Membership(
                user_id=row["user_id"],
                org_id=row["org_id"],
                org_name=row["org_name"],
                role=row["role"],
            )
            for row in rows
        ]

    def role_in(self, user_id: str, org_id: str) -> str | None:
        """The single answer to "may this person see this clinic"."""
        with connect(self.path) as db:
            row = db.execute(
                "SELECT role FROM memberships WHERE user_id = ? AND org_id = ?",
                (user_id, normalize_org_id(org_id)),
            ).fetchone()
        return row["role"] if row else None

    # ---- sessions --------------------------------------------------------
    def create_session(self, user_id: str, org_id: str, ttl: timedelta = SESSION_TTL) -> str:
        """Return the token to put in the cookie. It is never stored."""
        org_id = normalize_org_id(org_id)
        if self.role_in(user_id, org_id) is None:
            raise StoreError("cannot open a session on an organisation the user is not in")
        token = crypto.new_session_token()
        stamp = now_iso()
        expires = (datetime.now(UTC) + ttl).isoformat(timespec="seconds")
        with connect(self.path) as db:
            db.execute(
                """INSERT INTO sessions
                       (token_hash, user_id, current_org_id, created_at, expires_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (crypto.hash_session_token(token), user_id, org_id, stamp, expires, stamp),
            )
        return token

    def load_session(self, token: str) -> Session | None:
        """The session behind a cookie, or None. Expired rows are deleted here."""
        if not token:
            return None
        token_hash = crypto.hash_session_token(token)
        with connect(self.path) as db:
            row = db.execute(
                "SELECT * FROM sessions WHERE token_hash = ?", (token_hash,)
            ).fetchone()
            if row is None:
                return None
            if row["expires_at"] <= now_iso():
                db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                return None
            # The panel polls every 3 seconds per open tab. Writing
            # `last_seen_at` on every poll would turn a read into a write a
            # thousand times an hour for a column nobody reads to the second,
            # so it is touched at most once a minute.
            if _older_than(row["last_seen_at"], LAST_SEEN_RESOLUTION):
                db.execute(
                    "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
                    (now_iso(), token_hash),
                )
        return Session(
            user_id=row["user_id"],
            current_org_id=row["current_org_id"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
        )

    def switch_session_org(self, token: str, org_id: str) -> Session | None:
        """Point a live session at another clinic. Membership is checked here.

        Returns None when the session is gone or the person is not in that
        organisation — the caller turns both into the same refusal, because
        "you are not in it" and "it does not exist" are the same answer to
        somebody guessing org ids.
        """
        session = self.load_session(token)
        if session is None:
            return None
        org_id = normalize_org_id(org_id)
        if self.role_in(session.user_id, org_id) is None:
            return None
        with connect(self.path) as db:
            db.execute(
                "UPDATE sessions SET current_org_id = ? WHERE token_hash = ?",
                (org_id, crypto.hash_session_token(token)),
            )
        return Session(
            user_id=session.user_id,
            current_org_id=org_id,
            created_at=session.created_at,
            expires_at=session.expires_at,
        )

    def delete_session(self, token: str) -> None:
        with connect(self.path) as db:
            db.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (crypto.hash_session_token(token),)
            )

    def delete_sessions_of(self, user_id: str) -> None:
        with connect(self.path) as db:
            db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def purge_expired_sessions(self) -> int:
        with connect(self.path) as db:
            return int(
                db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now_iso(),)).rowcount
            )


# ---- the process-wide store ----------------------------------------------
def database_path(config: Any) -> Path:
    """`DATA_DIR/platform.db` — the same volume the call traces are on."""
    return Path(config.data_dir) / "platform.db"


@lru_cache
def _store_at(path: str) -> Store:
    return Store(path)


def store(config: Any | None = None) -> Store:
    """The Store this process uses, built from settings and cached per path."""
    if config is None:
        from agent.config import settings

        config = settings()
    return _store_at(str(database_path(config)))


def reset_store_cache() -> None:
    """Test isolation only."""
    _store_at.cache_clear()


def ensure_database(config: Any | None = None) -> Store | None:
    """Create and migrate the platform database at boot. Never raises.

    Called from every entry point's startup, so nobody has to remember to run
    a migration step and no deploy can serve a schema it has not applied. A
    fresh file is one organisation row, no users and no credentials — which is
    the state in which this whole package changes nothing: `people_are_
    provisioned()` is False, and a call resolves its key from the environment
    exactly as it did before there was a database.

    Returns None when the database could not be prepared. That is logged and
    then ignored on purpose: this process answers scored calls, and a console
    feature is never allowed to be the reason one does not connect.
    """
    from loguru import logger

    if config is None:
        from agent.config import settings

        config = settings()
    try:
        platform = store(config)
        version = platform.migrate()
    except Exception as exc:  # noqa: BLE001 - a console feature never stops the agent
        logger.error("platform database unavailable: {}", exc)
        return None
    logger.info("platform database ready at schema v{}", version)
    return platform
