"""Which Prosper key a call uses, now that there can be more than one.

This is the piece PLATFORM.md §2 names as the reason the database exists at
all: *"Hoy hay una PROSPER_API_KEY en el entorno. Con varias clínicas, cada
una tiene la suya y eso ya no cabe en un `.env`."*

The resolution order, and the reason for each step:

1. **The organisation's own stored key**, decrypted here and handed straight
   to the client. This is the only answer that scales past one clinic.
2. **`PROSPER_API_KEY` from the environment, for the default organisation
   only.** This step is what keeps a scored call behaving exactly as it did
   before this module existed: with no database file, or a database whose
   `clinica-arenal` row has no credential of its own, the key a call uses is
   byte-for-byte the one it used yesterday.
3. **Nothing**, for any other organisation with no key. A clinic nobody
   configured gets no credential rather than somebody else's — the one
   failure mode that must never be convenient.

Never raises. A database that is missing, locked, corrupt or encrypted under
a key this process does not have all fall through to step 2, because a
credential lookup is not allowed to be the thing that drops a live call.

Nothing here logs the key. The failure paths log *that* a lookup failed and
for which organisation, never what came back.
"""
from __future__ import annotations

from typing import Any

from loguru import logger

from agent.orgs import DEFAULT_ORG_ID, current_org_id, normalize_org_id


def prosper_api_key_for(config: Any, org_id: str | None = None) -> str:
    """The Prosper API key for an organisation. Empty string when it has none."""
    try:
        org = normalize_org_id(org_id) if org_id else current_org_id()
    except ValueError:
        return ""

    stored = _stored_key(config, org)
    if stored:
        return stored
    if org == DEFAULT_ORG_ID:
        # Read straight off the object, no getattr default: a settings object
        # missing this attribute is broken configuration and must raise here,
        # the way it raised inside the client constructor before this existed.
        return str(config.prosper_api_key or "")
    return ""


def _stored_key(config: Any, org_id: str) -> str:
    """This organisation's own key, or "" for every reason it might not have one."""
    try:
        from agent.accounts.store import store

        platform = store(config)
        if not platform.exists:
            # No database yet. The single-organisation deployment this repo
            # has been running all weekend takes this branch on every call.
            return ""
        return platform.organization_api_key(org_id, str(getattr(config, "ops_secret_key", "") or "")) or ""
    except Exception as exc:  # noqa: BLE001 - never drop a call over a lookup
        # `exc` carries the reason, never the ciphertext or the key.
        logger.warning("no stored Prosper credential for {}: {}", org_id, type(exc).__name__)
        return ""


class ClinicCredentials:
    """A settings-shaped view carrying one organisation's key.

    `ProsperClient` reads exactly two attributes off whatever it is given, so
    this is the whole surface. It exists so the client can be pointed at a
    different clinic without a second constructor and without anybody mutating
    the process-wide `Settings`.
    """

    __slots__ = ("prosper_api_base_url", "prosper_api_key")

    def __init__(self, base_url: str, api_key: str) -> None:
        self.prosper_api_base_url = base_url
        self.prosper_api_key = api_key

    def __repr__(self) -> str:  # pragma: no cover - guards accidental logging
        """Never print the key, not even in a traceback."""
        return f"ClinicCredentials(base_url={self.prosper_api_base_url!r}, api_key=<redacted>)"


def clinic_credentials(config: Any, org_id: str | None = None) -> ClinicCredentials:
    """What to hand `ProsperClient` for this organisation."""
    return ClinicCredentials(
        base_url=str(config.prosper_api_base_url),
        api_key=prosper_api_key_for(config, org_id),
    )
