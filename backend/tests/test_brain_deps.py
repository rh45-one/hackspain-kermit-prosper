"""Offline tests for brain.deps: national-id gate, language normalization, and
the process-wide CatalogueCache (identity, idempotent warm, test isolation)."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent.brain import deps
from agent.brain.deps import CLOSED_REASONS, normalize_language, validate_national_id
from tests.conftest import load_fixture


class CountingClinicClient:
    """get_clinic counts fetches; returns the fixture catalogue."""

    def __init__(self) -> None:
        self.fetches = 0

    async def get_clinic(self) -> dict[str, Any]:
        self.fetches += 1
        return load_fixture("clinic")


@pytest.fixture(autouse=True)
def _isolated_cache():
    """Every test in this module starts and ends with a fresh cache."""
    deps.reset_catalogue_cache()
    yield
    deps.reset_catalogue_cache()


def test_validate_national_id_accepts_valid_dni():
    ok, normalized = validate_national_id("12345678Z")
    assert ok and normalized == "12345678Z"


def test_validate_national_id_accepts_spaced_nie():
    ok, normalized = validate_national_id("x-1234567-l")
    assert ok and normalized == "X1234567L"


def test_validate_national_id_never_raises_on_bad_letter():
    ok, normalized = validate_national_id("12345678K")
    assert ok is False
    assert normalized == ""


def test_validate_national_id_never_raises_on_bad_shape():
    ok, normalized = validate_national_id("hello")
    assert ok is False and normalized == ""
    ok, normalized = validate_national_id("")
    assert ok is False and normalized == ""


def test_closed_reasons_match_the_contract_vocabulary():
    # The eleven clinic rules plus the seven non-rule endings.
    assert len(CLOSED_REASONS) == 18
    for reason in (
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
    ):
        assert reason in CLOSED_REASONS


def test_normalize_language_names_and_codes():
    assert normalize_language("catalán") == "ca"
    assert normalize_language("Catalan") == "ca"
    assert normalize_language("español") == "es"
    assert normalize_language("Spanish") == "es"
    assert normalize_language("ca") == "ca"
    assert normalize_language(None) is None
    assert normalize_language("") is None


# ---- shared catalogue cache: identity, idempotent warm, isolation ----------


def test_try_catalogue_cache_returns_one_process_wide_instance():
    first = deps.try_catalogue_cache()
    second = deps.try_catalogue_cache()
    assert first is not None
    assert first is second


def test_reset_catalogue_cache_yields_a_fresh_instance():
    before = deps.try_catalogue_cache()
    deps.reset_catalogue_cache()
    after = deps.try_catalogue_cache()
    assert after is not before


async def test_toolbox_uses_the_warmed_shared_cache(tmp_path):
    """The cache warmed at startup is exactly the one tools see."""
    from agent.brain.tools import ToolBox

    client = CountingClinicClient()
    assert await deps.warm_shared_catalogue(client) is True

    toolbox = ToolBox(_HintCtx(tmp_path), _HintSettings())
    assert toolbox.cache is deps.get_shared_catalogue_cache()
    assert toolbox.cache.warmed
    assert toolbox.cache.catalogue.clinic_name == "Clínica Arenal"


async def test_warm_is_idempotent_single_fetch():
    client = CountingClinicClient()
    assert await deps.warm_shared_catalogue(client) is True
    assert await deps.warm_shared_catalogue(client) is True
    assert client.fetches == 1


async def test_concurrent_warm_performs_a_single_fetch():
    client = CountingClinicClient()
    results = await asyncio.gather(
        deps.warm_shared_catalogue(client),
        deps.warm_shared_catalogue(client),
        deps.warm_shared_catalogue(client),
    )
    assert results == [True, True, True]
    assert client.fetches == 1


async def test_isolation_after_reset_requires_rewarm():
    client = CountingClinicClient()
    await deps.warm_shared_catalogue(client)
    deps.reset_catalogue_cache()
    fresh = deps.try_catalogue_cache()
    assert fresh is not None
    assert fresh.warmed is False  # a reset cache is cold again


# ---- local stubs -----------------------------------------------------------
class _HintCtx:
    """Minimal ctx for ToolBox construction in identity tests."""

    def __init__(self, tmp_path) -> None:
        self.data_dir = str(tmp_path / "data")

    def audit(self, event: str, data: dict | None = None) -> None:  # pragma: no cover
        pass


class _HintSettings:
    prosper_api_base_url = "https://api.test"
    prosper_api_key = "pk-test"
    data_dir = "./data"
