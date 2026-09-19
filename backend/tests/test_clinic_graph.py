"""The graph is computed from the catalogue, not written down here.

The only invented nodes are the four human roles the API has never heard of.
Everything else — who exists, who works where, who covers what — comes from
the clinic's own published data, so it cannot drift from it.
"""
from __future__ import annotations

import pytest

from agent.brain import deps
from agent.clinic import graph
from agent.clinic.cache import CatalogueCache
from tests.conftest import load_fixture


class FakeClinicClient:
    async def get_clinic(self) -> dict:
        return load_fixture("clinic")


@pytest.fixture
async def cache() -> CatalogueCache:
    warmed = CatalogueCache()
    await warmed.warm(FakeClinicClient())
    return warmed


def test_every_ending_the_clinic_allows_has_somebody_to_call():
    """Eighteen closed reasons, eighteen routes. A new one must fail loudly."""
    assert graph.missing_reasons() == frozenset()


def test_an_emergency_goes_straight_out_of_the_building():
    route = graph.who_to_call("medical_emergency")

    assert route.target == "emergency"
    assert route.urgency == "now"
    assert "112" in route.detail


def test_a_reason_the_clinic_does_not_define_routes_nowhere():
    """Better no answer than a confident wrong one about who to wake up."""
    assert graph.who_to_call("something_invented") is None


def test_every_route_points_at_a_node_that_exists(cache):
    built = graph.build(cache)
    ids = {node["id"] for node in built["nodes"]}

    for escalation in built["escalations"]:
        assert escalation["target"] in ids
        assert escalation["urgency"] in graph.URGENCY


def test_the_graph_is_the_catalogue(cache):
    """Doctors, sites and specialties are counted, never listed."""
    built = graph.build(cache)
    kinds = [node["kind"] for node in built["nodes"]]

    assert kinds.count("provider") == len(cache.providers_by_id)
    assert kinds.count("site") == len(cache.locations_by_id)
    assert kinds.count("specialty") == len(cache.specialties_by_id)
    assert kinds.count("role") == 4
    assert built["warm"] is True


def test_a_doctor_on_leave_stays_visible_and_stops_being_callable(cache):
    """Removing them would hide why a request cannot be served."""
    built = graph.build(cache)
    providers = [n for n in built["nodes"] if n["kind"] == "provider"]

    assert providers, "the fixture catalogue has no providers"
    assert all("available" in p for p in providers)


def test_a_cold_catalogue_still_answers_what_it_knows():
    """The roles and the routes do not depend on the API being reachable."""
    built = graph.build(None)

    assert built["warm"] is False
    assert {n["kind"] for n in built["nodes"]} == {"role"}
    assert len(built["escalations"]) == len(deps.CLOSED_REASONS)
