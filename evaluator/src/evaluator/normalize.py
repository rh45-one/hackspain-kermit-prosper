"""Field normalization per docs/prosper/normalization.md (scoring tolerance table).

The official scorer normalizes only where a human voice was in the loop:
REGISTER demographics and the appointment slot. Ids are compared exactly.
Everything here is deterministic - no LLM is involved in judging.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")

# Spanish DNI/NIE check letters, position = digits % 23.
_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"


def fold(value: str) -> str:
    """Unicode NFKD, combining marks stripped, case folded.

    Deliberately folds "ñ" to "n" - matches the scorer's simplification.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def norm_national_id(value: str) -> str:
    """DNI/NIE: drop every non-alphanumeric char, uppercase.

    `12345678-Z` → `12345678Z`; `x-1234567-l` → `X1234567L`.
    """
    return re.sub(r"[^0-9A-Za-z]", "", value).upper()


def national_id_check_ok(value: str) -> bool:
    """True when the letter matches the digits (DNI or NIE check letter)."""
    norm = norm_national_id(value)
    if not norm:
        return False
    if norm[0] in "XYZ":  # NIE: leading letter maps to 0/1/2
        digits = "012"["XYZ".index(norm[0])] + norm[1:-1]
        letter = norm[-1]
    else:
        digits, letter = norm[:-1], norm[-1]
    if not digits.isdigit() or not letter.isalpha():
        return False
    return _DNI_LETTERS[int(digits) % 23] == letter


def norm_person_name(value: str) -> str:
    """Accent-stripped, case-folded, whitespace-collapsed name."""
    return re.sub(r"\s+", " ", fold(value)).strip()


def norm_surnames(value: str) -> frozenset[str]:
    """Surnames compare as a set - order does not matter."""
    return frozenset(norm_person_name(value).split())


def norm_phone(value: str) -> str:
    """Fold to the nine national digits: country code and separators out."""
    digits = re.sub(r"\D", "", value)
    if len(digits) > 9:
        if digits.startswith("0034"):
            digits = digits[4:]
        elif digits.startswith("34"):
            digits = digits[2:]
        else:
            digits = digits[-9:]
    return digits


def norm_email(value: str) -> str:
    """All whitespace stripped, case folded."""
    return re.sub(r"\s+", "", value).lower()


def norm_slot(value: str) -> str:
    """ISO datetime → Europe/Madrid, seconds truncated to the minute."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError(f"slot lacks timezone offset: {value!r}")
    return dt.astimezone(MADRID).replace(second=0, microsecond=0).isoformat()


def norm_enum(value: str) -> str:
    """Free-text enums: folded, lowercase, non-alphanumeric runs to '_'."""
    return re.sub(r"[^0-9a-z]+", "_", fold(value)).strip("_")
