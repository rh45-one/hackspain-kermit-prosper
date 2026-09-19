"""The voice path with a real caller voice, not two seconds of silence.

`tts: true` on every scenario turn only means something if the synthesised
speech reaches the wire and the caller waits for the agent to stop talking
before the next line. Both are asserted here against the test double.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from evaluator.clinic.dataset import Dataset
from evaluator.clinic.server import create_app as create_clinic_app
from evaluator.harness import tts as tts_mod
from evaluator.harness.double_agent import create_app as create_double_app
from evaluator.harness.wsclient import SILENCE_FRAME, PlayTurn, dial, silence
from evaluator.models import Caller, Oracle, Outcome, Scenario, Turn
from evaluator.runner.experiment import _scenario_turns, serve_in_thread

DATASET = Path(__file__).resolve().parent.parent / "data" / "clinic_dataset.json"
KEY = "pk-local-eval"
CLINIC_PORT = 18997
DOUBLE_PORT = 18998

requires_espeak = pytest.mark.skipif(
    not tts_mod.provider_available("espeak-ng"),
    reason="espeak-ng not installed (brew install espeak-ng)",
)


@pytest.fixture
def rig():
    dataset = Dataset.load(DATASET)
    clinic = serve_in_thread(create_clinic_app(dataset, api_key=KEY), "127.0.0.1", CLINIC_PORT)
    double = serve_in_thread(
        create_double_app(f"http://127.0.0.1:{CLINIC_PORT}", api_key=KEY),
        "127.0.0.1",
        DOUBLE_PORT,
    )
    yield
    double.stop()
    clinic.stop()


@requires_espeak
class TestSynthesisedCaller:
    def test_every_shipped_scenario_synthesises(self, tmp_path):
        """No scenario may silently fall back to silence on the voice path."""
        root = Path(__file__).resolve().parent.parent / "scenarios"
        paths = sorted(root.glob("**/*.yaml"))
        assert paths
        for path in paths:
            scenario = Scenario.load(str(path))
            turns, rig_errors = _scenario_turns(scenario, path, tts_command="espeak-ng")
            assert rig_errors == [], f"{scenario.id}: {rig_errors}"
            assert all(t.frames for t in turns)

    async def test_speech_reaches_the_wire(self, rig):
        scenario = Scenario(
            id="v-001",
            problem_id="simple_booking",
            caller=Caller(opening="hola"),
            turns=[Turn(text="Buenos días, quiero una cita.", tts=True, hold_ms=0)],
            oracle=Oracle(accepted_outcomes=[Outcome(actions=[{"action": "NO_ACTION"}])]),
        )
        turns, rig_errors = _scenario_turns(
            scenario, Path("scenarios/v/v-001.yaml"), tts_command="espeak-ng"
        )
        assert rig_errors == []
        ev = await dial(
            f"ws://127.0.0.1:{DOUBLE_PORT}/ws",
            uuid.uuid4().hex,
            turns,
            after_send_idle_s=0.2,
        )
        assert ev.error is None
        # More than a second of audio, and it is not µ-law silence.
        assert len(ev.caller_audio) > 8000
        assert set(ev.caller_audio) != set(SILENCE_FRAME)


class TestAdaptiveHold:
    async def test_hold_waits_while_the_agent_talks(self, rig):
        """The double never stops talking: the caller holds to the cap."""
        ev = await dial(
            f"ws://127.0.0.1:{DOUBLE_PORT}/ws",
            uuid.uuid4().hex,
            [PlayTurn(silence(100), hold_ms=100, quiet_ms=400, max_hold_ms=900)],
            after_send_idle_s=0.1,
        )
        assert ev.error is None
        # 5 utterance frames + roughly the 900 ms cap in silence frames.
        assert ev.frames_sent > 30

    async def test_fixed_hold_when_not_adaptive(self, rig):
        """max_hold_ms = 0 keeps the old fixed pause, cap included."""
        ev = await dial(
            f"ws://127.0.0.1:{DOUBLE_PORT}/ws",
            uuid.uuid4().hex,
            [PlayTurn(silence(100), hold_ms=200, max_hold_ms=0)],
            after_send_idle_s=0.1,
        )
        assert ev.error is None
        assert 12 <= ev.frames_sent <= 20  # 5 frames + ~10 of hold
