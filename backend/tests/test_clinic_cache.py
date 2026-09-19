"""Offline tests for the immutable catalogue cache."""
from __future__ import annotations

import pytest

from agent.clinic.cache import CatalogueCache
from agent.clinic.models import ClinicCatalogue
from tests.conftest import load_fixture


class FakeClinicClient:
    """Returns the fixture catalogue without any network."""

    async def get_clinic(self) -> dict:
        return load_fixture("clinic")


@pytest.fixture
async def cache() -> CatalogueCache:
    cache = CatalogueCache()
    await cache.warm(FakeClinicClient())
    return cache


async def test_warm_builds_indexes(cache: CatalogueCache):
    assert cache.warmed
    assert isinstance(cache.catalogue, ClinicCatalogue)
    assert len(cache.providers_by_id) == 3
    assert cache.providers_by_id["PR01"].name == "Dra. Ana Sáez"


async def test_catalogue_property_before_warm_raises():
    cache = CatalogueCache()
    with pytest.raises(RuntimeError):
        _ = cache.catalogue


async def test_warm_is_idempotent():
    cache = CatalogueCache()
    first = await cache.warm(FakeClinicClient())
    second = await cache.warm(FakeClinicClient())
    assert first == second  # same catalogue content, atomically republished
    assert cache.providers_by_id["PR01"] is second.providers[0]


# ---- accent-insensitive lookups ------------------------------------------
async def test_provider_lookup_folds_accents(cache: CatalogueCache):
    assert cache.provider_by_name("Sáez") is cache.providers_by_id["PR01"]
    assert cache.provider_by_name("saez") is cache.providers_by_id["PR01"]
    assert cache.provider_by_name("ÁLVARO CID") is cache.providers_by_id["PR03"]
    assert cache.provider_by_name("Iglesias") is cache.providers_by_id["PR02"]
    # Near-miss pair must not collide: Iglesia vs Iglesias.
    assert cache.provider_by_name("Iglesia") is None


async def test_specialty_lookup_folds_accents(cache: CatalogueCache):
    assert cache.specialty_by_name("Dermatología") is cache.specialties_by_id["dermatology"]
    assert cache.specialty_by_name("dermatologia") is cache.specialties_by_id["dermatology"]


async def test_specialty_lookup_accepts_spoken_spanish(cache: CatalogueCache):
    """Regression: a Spanish ask reached the tool as an unknown specialty.

    The catalogue names specialties in English; callers say "el médico de
    cabecera" or "el fisioterapeuta". On a live call find_availability
    answered "no specialty named 'médico de cabecera'" and the agent asked
    the caller to name their own specialty instead of offering a slot.
    """
    gp = cache.specialties_by_id["general"]
    for spoken in (
        "médico de cabecera",
        "medico de cabecera",
        "medicina general",
        "el médico de familia",
        "atención primaria",
    ):
        assert cache.specialty_by_name(spoken) is gp, spoken

    assert cache.specialty_by_name("fisioterapeuta") is cache.specialties_by_id["physiotherapy"]
    assert cache.specialty_by_name("dermatólogo") is cache.specialties_by_id["dermatology"]
    # The id itself still resolves, for a model that echoes it back verbatim.
    assert cache.specialty_by_name("physiotherapy") is cache.specialties_by_id["physiotherapy"]
    # An unknown ask stays unknown rather than resolving to something near it.
    assert cache.specialty_by_name("astrología") is None


async def test_location_and_plan_lookup(cache: CatalogueCache):
    assert cache.location_by_name("centro") is cache.locations_by_id["centro"]
    assert cache.plan_by_name("Sanitas") is cache.plans_by_id["sanitas"]
    assert cache.plan_by_name("unknown") is None


async def test_type_lookups(cache: CatalogueCache):
    assert cache.type_by_id("dermatology_review") is not None
    assert cache.type_by_name("dermatology review") is cache.types_by_id["dermatology_review"]


# ---- derived views --------------------------------------------------------
async def test_providers_for_specialty(cache: CatalogueCache):
    ids = [p.id for p in cache.providers_for_specialty("dermatology")]
    assert ids == ["PR02"]


async def test_providers_speaking_by_name_and_code(cache: CatalogueCache):
    catalan = {p.id for p in cache.providers_speaking("catalán")}
    assert catalan == {"PR01", "PR03"}
    # Same answer for the iso code, the accented name, or any case.
    assert {p.id for p in cache.providers_speaking("ca")} == catalan
    assert {p.id for p in cache.providers_speaking("Catalán")} == catalan
    assert {p.id for p in cache.providers_speaking("galego")} == {"PR03"}
    # Everyone speaks Spanish here.
    assert {p.id for p in cache.providers_speaking("español")} == {"PR01", "PR02", "PR03"}


async def test_provider_ids_at_location(cache: CatalogueCache):
    assert cache.provider_ids_at_location("sur") == {"PR03"}
    assert cache.provider_ids_at_location("centro") == {"PR01", "PR02"}
    assert cache.provider_ids_at_location("nowhere") == set()


async def test_nearest_locations_orders_by_distance(cache: CatalogueCache):
    # Getafe-ish point: Sur is closest, then Centro, then Norte.
    ordered = cache.nearest_locations(40.3080, -3.7300)
    ids = [loc.id for loc, _ in ordered]
    assert ids[0] == "sur"
    assert ids[-1] == "norte"
    distances = [d for _, d in ordered]
    assert distances == sorted(distances)


def test_a_generic_second_word_does_not_hide_the_plan(cache):
    """Three of the ten plans end in a word two of them share."""
    assert cache.plan_by_name("Sanitas Salud").id == "sanitas"
    assert cache.plan_by_name("ASISA").id == "asisa"


def test_a_shared_word_identifies_no_plan_on_its_own(cache):
    assert cache.plan_by_name("salud") is None
    assert cache.plan_by_name("seguros") is None


def test_particular_is_what_a_caller_calls_self_pay(cache):
    """The catalogue says 'Privado'; nobody on a telephone does."""
    for spoken in ("particular", "privada", "Privado"):
        assert cache.plan_by_name(spoken).id == "privado"


def test_an_invented_plan_still_resolves_to_nothing(cache):
    assert cache.plan_by_name("Sanitos Premium") is None
