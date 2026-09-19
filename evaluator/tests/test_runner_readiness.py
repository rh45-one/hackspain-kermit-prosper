"""The run plan and the readiness gate: fairness and attribution before scoring.

Two failures this guards against, both of which cost a real A/B comparison:

- Firing cases at a candidate the runner just started. It raced its own
  startup, and those calls were scored against the model.
- Running each candidate's block to completion. A backend that drifts during
  the run favours whoever went last, which is the effect being measured.

Both are checked here without starting an agent or touching the network.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from evaluator.models import (
    CandidateConfig,
    ExperimentConfig,
    Scenario,
)
from evaluator.runner.experiment import case_plan
from evaluator.runner.readiness import (
    Readiness,
    ready_url_for,
    wait_for_candidate,
    wait_for_ready,
)


def _candidate(name: str, **kwargs) -> CandidateConfig:
    defaults = {"name": name, "ws_url": "ws://127.0.0.1:17860/ws"}
    return CandidateConfig(**{**defaults, **kwargs})


class TestReadyUrl:
    def test_derives_healthz_from_ws_url(self):
        assert ready_url_for(_candidate("a")) == "http://127.0.0.1:17860/healthz"

    def test_secure_scheme_maps_to_https(self):
        cand = _candidate("a", ws_url="wss://agent.example.com/ws")
        assert ready_url_for(cand) == "https://agent.example.com/healthz"

    def test_explicit_url_wins(self):
        cand = _candidate("a", ready_url="http://127.0.0.1:9999/ping")
        assert ready_url_for(cand) == "http://127.0.0.1:9999/ping"

    def test_no_ws_url_means_nothing_to_probe(self):
        assert ready_url_for(_candidate("a", ws_url=None)) is None


async def test_ready_when_the_agent_answers():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"status": "ok"}))
    readiness = await wait_for_ready(
        "http://127.0.0.1:17860/healthz", 2.0, transport=transport, poll_s=0.01
    )
    assert readiness.ready is True
    assert readiness.detail == "HTTP 200"
    assert "listo" in readiness.describe()


async def test_a_missing_health_route_is_still_a_live_agent():
    transport = httpx.MockTransport(lambda request: httpx.Response(404))
    readiness = await wait_for_ready(
        "http://127.0.0.1:17860/healthz", 2.0, transport=transport, poll_s=0.01
    )
    assert readiness.ready is True
    assert readiness.detail == "HTTP 404"


async def test_a_500_is_not_ready():
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    readiness = await wait_for_ready(
        "http://127.0.0.1:17860/healthz", 0.2, transport=transport, poll_s=0.01
    )
    assert readiness.ready is False
    assert "503" in readiness.detail


async def test_refused_connection_times_out_with_the_cause():

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    readiness = await wait_for_ready(
        "http://127.0.0.1:17860/healthz", 0.2, transport=httpx.MockTransport(refuse), poll_s=0.01
    )
    assert readiness.ready is False
    assert "ConnectError" in readiness.detail
    assert readiness.waited_s >= 0.2
    assert "NO responde" in readiness.describe()


async def test_it_keeps_polling_until_the_agent_comes_up():
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] < 3 else httpx.Response(200)

    readiness = await wait_for_ready(
        "http://127.0.0.1:17860/healthz", 2.0, transport=httpx.MockTransport(flaky), poll_s=0.01
    )
    assert readiness.ready is True
    assert calls["n"] == 3


def test_candidate_without_ws_url_is_never_ready():
    readiness = wait_for_candidate(_candidate("a", ws_url=None, ready_url=None))
    assert readiness.ready is False
    assert readiness.waited_s == 0.0
    assert "sin ws_url" in readiness.detail


def test_manifest_shape_is_flat_and_complete():
    readiness = Readiness(ready=True, url="http://x/healthz", waited_s=1.25, detail="HTTP 200")
    assert readiness.as_manifest() == {
        "ready": True,
        "url": "http://x/healthz",
        "waited_s": 1.25,
        "detail": "HTTP 200",
    }


SCENARIOS = Path(__file__).resolve().parent.parent / "scenarios"


def _scenario(scenario_id: str) -> Scenario:
    """A real scenario file: inventing one would drift from the schema."""
    return Scenario.load(str(SCENARIOS / "simple_booking" / f"{scenario_id}.yaml"))


def _config(candidates: list[CandidateConfig], repetitions: int = 1) -> ExperimentConfig:
    return ExperimentConfig(
        name="plan-test",
        clinic_dataset="../data/clinic_dataset.json",
        repetitions=repetitions,
        candidates=candidates,
        scenarios=["../scenarios/**/*.yaml"],
    )


class TestCasePlan:
    def test_candidate_varies_fastest_so_no_one_goes_last(self):
        config = _config([_candidate("a"), _candidate("b"), _candidate("c")])
        scenarios = [(_scenario("sb-001"), Path("s1.yaml")), (_scenario("sb-002"), Path("s2.yaml"))]
        order = [(cand.name, scenario.id) for _, scenario, _, cand in case_plan(config, scenarios)]
        assert order == [
            ("a", "sb-001"),
            ("b", "sb-001"),
            ("c", "sb-001"),
            ("a", "sb-002"),
            ("b", "sb-002"),
            ("c", "sb-002"),
        ]

    def test_every_repetition_still_sees_every_candidate(self):
        config = _config([_candidate("a"), _candidate("b")], repetitions=2)
        scenarios = [(_scenario("sb-001"), Path("s1.yaml"))]
        plan = case_plan(config, scenarios)
        assert [(rep, cand.name) for rep, _, _, cand in plan] == [
            (0, "a"),
            (0, "b"),
            (1, "a"),
            (1, "b"),
        ]

    def test_plan_covers_every_combination_exactly_once(self):
        config = _config([_candidate("a"), _candidate("b")], repetitions=2)
        scenarios = [(_scenario("sb-001"), Path("s1.yaml")), (_scenario("sb-002"), Path("s2.yaml"))]
        keys = {
            (rep, scenario.id, cand.name) for rep, scenario, _, cand in case_plan(config, scenarios)
        }
        assert len(keys) == 2 * 2 * 2


@pytest.mark.parametrize("bad", ["ws://127.0.0.1:17860/ws", "not-a-url"])
def test_derivation_never_invents_a_scheme(bad):
    cand = _candidate("a", ws_url=bad)
    url = ready_url_for(cand)
    assert url is None or url.startswith("http")
