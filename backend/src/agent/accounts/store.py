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


class StoreError(RuntimeError):
    """A rule of this layer was broken: unknown org, duplicate email, bad role."""


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
