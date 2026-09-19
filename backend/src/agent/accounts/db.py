"""The platform database: SQLite, on the machine's own volume.

Why SQLite and not Postgres
---------------------------
This is not a preference, it is what `fly.toml` already says out loud:

    [[mounts]] source = "prosper_data" destination = "/data"
    auto_stop_machines = false
    min_machines_running = 1
    # One machine owns the volume and the in-process call state; never two.

One machine, one volume, one process, and that comment is a constraint the
voice path already depends on: the call state lives in memory and the traces
live on that mount, so a second machine was never an option here. A database
that has exactly one writer, on the same host as its only reader, is the
shape SQLite is for.

Postgres would mean a second Fly app with its own machine, its own volume,
its own upgrades and its own outage — a network hop introduced between a
scored call and the credential it needs, in exchange for concurrency this
deployment is configured never to have. It would also be the second thing
that can be down at 3 minutes' notice during a call that scores. For a table
of organisations, a table of people and their memberships, we would be paying
an availability cost for a row count that fits on one screen.

Three more things fall out of picking SQLite here, and they are the reason
this took an hour rather than a day:

* `sqlite3` is in the standard library, so the image and `uv.lock` do not
  change for the database itself.
* The file sits at ``DATA_DIR/platform.db``, on the same volume as the call
  traces, so it is inside the same Fly volume snapshot. One backup, not two.
* Migrations are a `PRAGMA user_version` and a list of statements, applied on
  boot. No migration tool, no `alembic upgrade head` in an entrypoint, no
  step where somebody has to remember to run something.

When this outgrows one machine, the thing that forces the move is the second
machine, not the row count — and the day that arrives, these four tables port
to Postgres in an afternoon because nothing here uses a SQLite-ism.

Connections
-----------
One connection per operation, opened and closed. It costs tens of
microseconds against an already-open file and removes every question about
which thread or which event loop a connection belongs to — FastAPI runs sync
dependencies in a threadpool and async routes on the loop, and a shared
`sqlite3.Connection` across both is a class of bug nobody needs at a
hackathon. WAL mode is set once, at migration time, and is a property of the
file rather than of the connection.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from agent.orgs import DEFAULT_ORG_ID

# Bumped by appending to _MIGRATIONS. Never by editing one in place: the
# volume already holds a database that has run the old ones.
SCHEMA_VERSION = 3

_MIGRATIONS: list[tuple[int, tuple[str, ...]]] = [
    (
        1,
        (
            """
            CREATE TABLE IF NOT EXISTS organizations (
                id                          TEXT PRIMARY KEY,
                name                        TEXT NOT NULL,
                -- AES-GCM ciphertext, never the key itself, and never read
                -- back over HTTP. NULL means "no credential of its own",
                -- which is how the one clinic that predates this table keeps
                -- using PROSPER_API_KEY from the environment.
                prosper_api_key_encrypted   TEXT,
                -- A truncated digest, safe to show a person so they can tell
                -- which key is loaded without being told what it is.
                prosper_api_key_fingerprint TEXT,
                credentials_updated_at      TEXT,
                created_at                  TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS users (
                id            TEXT PRIMARY KEY,
                email         TEXT NOT NULL UNIQUE,
                display_name  TEXT NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                disabled_at   TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS memberships (
                user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                org_id     TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                role       TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, org_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sessions (
                -- The token is never stored. A stolen database file is not a
                -- pile of live sessions.
                token_hash     TEXT PRIMARY KEY,
                user_id        TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                current_org_id TEXT NOT NULL REFERENCES organizations(id),
                created_at     TEXT NOT NULL,
                expires_at     TEXT NOT NULL,
                last_seen_at   TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_memberships_org ON memberships(org_id)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)",
        ),
    ),
    (
        2,
        (
            # The four human nodes `clinic/graph.py` has had to declare by
            # hand, turned into data per organisation. A hospital has twenty
            # and a consulting room has two, and neither should edit code.
            #
            # `slug` is the id the graph draws and the routes point at. A row
            # whose slug is one of the four default role ids REPLACES that
            # default; any default nobody has taken stays. That is what stops
            # configuring one role from silently deleting the other three.
            """
            CREATE TABLE IF NOT EXISTS people (
                id           TEXT PRIMARY KEY,
                org_id       TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                slug         TEXT NOT NULL,
                name         TEXT NOT NULL,
                role         TEXT NOT NULL,
                detail       TEXT NOT NULL DEFAULT '',
                -- Catalogue language codes, in the catalogue's own order.
                -- Empty means "ask the catalogue", which is how a doctor keeps
                -- behaving exactly as they did before this table existed.
                languages    TEXT NOT NULL DEFAULT '',
                -- The catalogue provider this person is, when they are one at
                -- all. NULL for a receptionist, a manager, or 112.
                provider_id  TEXT,
                -- How to reach them. Staff contact details, shown to members
                -- of their own organisation and never put in a model prompt.
                phone        TEXT NOT NULL DEFAULT '',
                email        TEXT NOT NULL DEFAULT '',
                -- The call profile: what Ginés asked for. What the agent says
                -- when this person picks up, and what it may and may not ask
                -- of them. Per person, not per deployment.
                opening      TEXT NOT NULL DEFAULT '',
                may_ask      TEXT NOT NULL DEFAULT '',
                must_not_ask TEXT NOT NULL DEFAULT '',
                active       INTEGER NOT NULL DEFAULT 1,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL,
                UNIQUE (org_id, slug)
            )
            """,
            # One of the eighteen endings, and who hears about it here. A
            # reason with no row falls back to the hand-written route, so an
            # organisation that configures nothing still has somebody to call.
            """
            CREATE TABLE IF NOT EXISTS routes (
                org_id      TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                reason      TEXT NOT NULL,
                person_slug TEXT NOT NULL,
                urgency     TEXT NOT NULL,
                detail      TEXT NOT NULL DEFAULT '',
                updated_at  TEXT NOT NULL,
                PRIMARY KEY (org_id, reason)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_people_org ON people(org_id)",
        ),
    ),
    (
        3,
        (
            # Who steps in when this person is not there. A route says "when a
            # doctor is off, ring Germán" and that is one answer for every
            # absence; this says which absence, which is what a rota is. Held
            # as a slug rather than a foreign key so deleting somebody leaves a
            # chain that reads as broken instead of one that quietly vanishes.
            "ALTER TABLE people ADD COLUMN covers_for TEXT NOT NULL DEFAULT ''",
        ),
    ),
]


def now_iso() -> str:
    """UTC, to the second, the way every trace line on this volume is stamped."""
    return datetime.now(UTC).isoformat(timespec="seconds")


@contextmanager
def connect(path: str | Path) -> Iterator[sqlite3.Connection]:
    """One configured connection, closed on the way out.

    `isolation_level=None` turns off the driver's implicit transactions, so a
    statement commits when it runs and a multi-statement change says BEGIN for
    itself. That is the only mode where "what did this actually commit" has a
    single answer.
    """
    connection = sqlite3.connect(str(path), isolation_level=None, timeout=5.0)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        yield connection
    finally:
        connection.close()


def migrate(path: str | Path, *, default_org_name: str = "Clínica Arenal") -> int:
    """Bring the file at `path` up to `SCHEMA_VERSION`. Idempotent.

    Called on boot by every entry point that has a database, and safe to call
    from several of them: SQLite takes the write lock, the loser waits, and
    the second caller finds `user_version` already where it wants it.

    Returns the version the file is at afterwards.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with connect(target) as connection:
        # A property of the file, not of the connection: readers stop
        # blocking writers for good once this has run once.
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        for number, statements in _MIGRATIONS:
            if number <= version:
                continue
            connection.execute("BEGIN IMMEDIATE")
            try:
                for statement in statements:
                    connection.execute(statement)
                # `user_version` takes no parameter binding.
                connection.execute(f"PRAGMA user_version = {int(number)}")
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
            version = number
        # The clinic this repository was built for always exists, so a first
        # boot has somewhere to put a session and a credential without anybody
        # creating anything. No credential is written: with the column NULL,
        # the environment's PROSPER_API_KEY is still what a call uses, which
        # is what keeps single-organisation behaviour identical.
        connection.execute(
            "INSERT OR IGNORE INTO organizations (id, name, created_at) VALUES (?, ?, ?)",
            (DEFAULT_ORG_ID, default_org_name, now_iso()),
        )
    return version
