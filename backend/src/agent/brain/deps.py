"""Lazy access to the clinic and scheduling layers.

Worker modules may not exist yet during the build; tools degrade with an
explicit error for the LLM instead of crashing the call.
"""
from __future__ import annotations

from typing import Any

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


def try_clinic_client(settings: Any) -> Any | None:
    """Return a ProsperClient, or None when the clinic layer is not ready."""
    try:
        client_cls = _import("agent.clinic.client.ProsperClient")
    except (ImportError, AttributeError):
        return None
    return client_cls(settings)


def try_catalogue_cache() -> Any | None:
    try:
        return _import("agent.clinic.cache.CatalogueCache")()
    except (ImportError, AttributeError):
        return None


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
