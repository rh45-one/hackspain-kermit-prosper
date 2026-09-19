"""Lazy access to the clinic and scheduling layers.

Worker modules may not exist yet during the build; tools degrade with an
explicit error for the LLM instead of crashing the call.

Catalogue caches are per organisation and process-wide within one: the
instance warmed for a clinic is the same instance every ToolBox serving that
clinic reads, so the immutable catalogue is fetched exactly once per process
per organisation. With one organisation that is exactly the previous
behaviour — a single cache, warmed once at startup.

Callers that pass no ``org_id`` get the organisation bound to the current
task (``agent.orgs.current_org_id``), which is the default organisation
unless a call set one. That indirection is what lets ``brain/tools.py`` keep
calling ``deps.try_catalogue_cache()`` with no arguments and still receive
its own clinic's catalogue.

``reset_catalogue_cache`` exists for test isolation only.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

from agent.orgs import current_org_id, normalize_org_id

CLOSED_REASONS: frozenset[str] = frozenset(
    {
        "not_eligible_age",
        "referral_required",
        "provider_not_in_network",
        "specialty_not_covered",
        "location_not_covered",
        "insurer_referral_required",
        "allowance_exhausted",
        "provider_on_leave",
        "location_hours",
        "type_not_offered",
        "patient_history",
        "no_availability",
        "clinic_closed",
        "patient_not_found",
        "provider_not_found",
        "caller_not_authorised",
        "out_of_scope",
        "medical_emergency",
    }
)

_LANGUAGE_CODES = {
    "español": "es",
    "espanol": "es",
    "spanish": "es",
    "castellano": "es",
    "catalán": "ca",
    "catalan": "ca",
    "gallego": "gl",
    "galego": "gl",
    "galician": "gl",
    "euskera": "eu",
    "euskara": "eu",
    "basque": "eu",
    "inglés": "en",
    "ingles": "en",
    "english": "en",
}


def normalize_language(name: str | None) -> str | None:
    if not name:
        return None
    low = name.strip().lower()
    return _LANGUAGE_CODES.get(low, low[:2])


def _import(path: str) -> Any:
    module_name, attr = path.rsplit(".", 1)
    import importlib

    return getattr(importlib.import_module(module_name), attr)


# ---- shared catalogue caches, one per organisation ------------------------
# Created lazily and thread-safely; ``warm`` itself is idempotent and atomic
# (it rebuilds every index locally, then publishes in a single assignment), so
# concurrent warmers of the same organisation converge on a complete snapshot.
# Two organisations never share a lock, so a slow clinic cannot hold up
# another one's first call.
_catalogue_caches: dict[str, Any] = {}
_catalogue_cache_lock = threading.Lock()
_warm_locks: dict[str, asyncio.Lock] = {}


def _org(org_id: str | None) -> str:
    """The organisation to serve: the argument, else the current task's."""
    return normalize_org_id(org_id) if org_id else current_org_id()


def get_shared_catalogue_cache(org_id: str | None = None) -> Any | None:
    """Return this organisation's CatalogueCache, creating it once."""
    key = _org(org_id)
    cache = _catalogue_caches.get(key)
    if cache is not None:
        return cache
    with _catalogue_cache_lock:
        cache = _catalogue_caches.get(key)
        if cache is None:
            try:
                cache_cls = _import("agent.clinic.cache.CatalogueCache")
            except (ImportError, AttributeError):
                return None
            cache = cache_cls()
            _catalogue_caches[key] = cache
    return cache


def try_catalogue_cache(org_id: str | None = None) -> Any | None:
    """Return the shared CatalogueCache for an organisation.

    With no argument this is the organisation bound to the current task, which
    is how the ToolBox gets the right one without naming it.
    """
    return get_shared_catalogue_cache(org_id)


def _warm_lock_for(org_id: str) -> asyncio.Lock:
    """One warm lock per organisation, created under the same guard."""
    lock = _warm_locks.get(org_id)
    if lock is not None:
        return lock
    with _catalogue_cache_lock:
        return _warm_locks.setdefault(org_id, asyncio.Lock())


def reset_catalogue_cache(org_id: str | None = None) -> None:
    """Drop a cache, or every cache. Test isolation only — never in production.

    Called with no argument it drops them all, which is what an autouse test
    fixture wants: one warmed organisation leaking into a test that expects a
    cold catalogue is exactly the cross-test failure this guards.
    """
    with _catalogue_cache_lock:
        if org_id is None:
            _catalogue_caches.clear()
            _warm_locks.clear()
            return
        key = normalize_org_id(org_id)
        _catalogue_caches.pop(key, None)
        _warm_locks.pop(key, None)


async def warm_shared_catalogue(client: Any, org_id: str | None = None) -> bool:
    """Warm one organisation's cache once, even under concurrent callers.

    Returns False only when the clinic layer is unavailable. A second warm of
    an already-warmed cache performs no fetch.
    """
    key = _org(org_id)
    cache = get_shared_catalogue_cache(key)
    if cache is None:
        return False
    async with _warm_lock_for(key):
        if cache.warmed:
            return True
        await cache.warm(client)
        return True


async def ensure_catalogue_warm(settings: Any, org_id: str | None = None) -> Any | None:
    """This organisation's catalogue, warmed on first use. Never raises.

    The single place that turns "I need this clinic's catalogue" into at most
    one fetch. Returns the cache when it is usable and None when the clinic
    layer is absent, there are no credentials, or the fetch failed — callers
    degrade to ids rather than fail, which is what every reader already did.
    """
    cache = get_shared_catalogue_cache(org_id)
    if cache is None or cache.warmed:
        return cache
    if not getattr(settings, "prosper_api_key", ""):
        return None
    client: Any = None
    try:
        # Inside the guard on purpose: try_clinic_client calls the constructor
        # outside its own try, so bad configuration raises out of it.
        client = try_clinic_client(settings)
        if client is None:
            return None
        await warm_shared_catalogue(client, org_id)
    except Exception:  # noqa: BLE001 - a cold catalogue degrades, never 500s
        return None
    finally:
        close = getattr(client, "close", None) if client is not None else None
        if close is not None:
            await close()
    return cache if cache.warmed else None


def try_clinic_client(settings: Any) -> Any | None:
    """Return a ProsperClient, or None when the clinic layer is not ready."""
    try:
        client_cls = _import("agent.clinic.client.ProsperClient")
    except (ImportError, AttributeError):
        return None
    return client_cls(settings)


def try_date_resolver() -> Any | None:
    try:
        return _import("agent.scheduling.dates.MadridDateResolver")()
    except (ImportError, AttributeError):
        return None


def validate_national_id(raw: str) -> tuple[bool, str]:
    """Normalize DNI/NIE and re-derive the check letter. Never raises.

    The canonical implementation lives in the scheduling module; the local
    fallback below is only for boot order and performs the same check.
    """
    try:
        fn = _import("agent.scheduling.recorder.validate_national_id")
    except (ImportError, AttributeError):
        fn = _fallback_validate_national_id
    try:
        return True, fn(raw)
    except ValueError:
        return False, ""


def _fallback_validate_national_id(raw: str) -> str:
    """Self-contained copy of the check-letter rule, for boot-order safety only."""
    import re

    letters = "TRWAGMYFPDXBNJZSQVHLCKE"
    nie_prefix = {"X": "0", "Y": "1", "Z": "2"}
    clean = re.sub(r"[\s-]", "", (raw or "").upper())
    if not clean:
        raise ValueError("empty national id")
    if clean[0] in nie_prefix:
        digits, letter = clean[1:-1], clean[-1]
        if not digits.isdigit() or len(digits) != 7:
            raise ValueError(f"bad NIE shape: {raw!r}")
        number = int(nie_prefix[clean[0]] + digits)
        prefix = clean[0]
    else:
        digits, letter = clean[:-1], clean[-1]
        if not digits.isdigit() or len(digits) != 8:
            raise ValueError(f"bad DNI shape: {raw!r}")
        number = int(digits)
        prefix = ""
    if letter != letters[number % 23]:
        raise ValueError(f"check letter {letter!r} does not match digits")
    return prefix + digits + letter
