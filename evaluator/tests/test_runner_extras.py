"""Runner wiring: turn assembly (noise/interrupt/TTS), usage fetch."""
from __future__ import annotations

import json
import socket
from pathlib import Path

import httpx
import pytest

from evaluator.models import Caller, ExperimentConfig, NoiseSpec, Oracle, Outcome, Scenario, Turn
from evaluator.runner.experiment import _fetch_usage, _scenario_turns, serve_in_thread


def _scenario(**kw) -> Scenario:
    return Scenario(
        id="t-001",
        problem_id="simple_booking",
        caller=Caller(opening="hola"),
        oracle=Oracle(accepted_outcomes=[Outcome(actions=[{"action": "NO_ACTION"}])]),
        **kw,
    )


class TestIsolation:
    def test_server_refuses_an_occupied_port(self):
        from fastapi import FastAPI

        with socket.create_server(("127.0.0.1", 0)) as occupied:
            port = occupied.getsockname()[1]
            with pytest.raises(OSError):
                serve_in_thread(FastAPI(), "127.0.0.1", port)

    def test_server_releases_its_port_when_stopped(self):
        from fastapi import FastAPI

        handle = serve_in_thread(FastAPI(), "127.0.0.1", 0)
        address = handle.listener.getsockname()
        handle.stop()
        assert not handle.thread.is_alive()
        with socket.create_server(address):
            pass

    def test_smoke_configs_only_use_local_doubles(self):
        root = Path(__file__).resolve().parent.parent
        for name in ("smoke", "switchboard"):
            config = ExperimentConfig.load(str(root / "experiments" / f"{name}.yaml"))
            assert config.clinic_port == 18090
            for candidate in config.candidates:
                assert candidate.kind == "double"
                assert candidate.port in (18770, 18771, 18772)
                assert candidate.start_command is None
                assert candidate.ws_url is None
                assert candidate.text_url is None

    def test_external_template_does_not_target_the_shared_agent(self):
        path = Path(__file__).resolve().parent.parent / "experiments" / "agent-local.yaml"
        config = ExperimentConfig.load(str(path))
        assert config.clinic_port == 18090
        candidate = config.candidates[0]
        assert candidate.ws_url == "ws://127.0.0.1:17860/ws"
        assert candidate.start_command is None
        assert candidate.env["PROSPER_API_BASE_URL"] == "http://127.0.0.1:18090"


class TestScenarioTurns:
    def test_silence_when_no_audio(self, tmp_path):
        s = _scenario(turns=[Turn(hold_ms=0)])
        turns = _scenario_turns(s, tmp_path / "s.yaml")
        assert len(turns) == 1
        assert not turns[0].interrupt_on_agent_audio
        assert all(len(f) == 160 for f in turns[0].frames)

    def test_interrupt_flag_propagates(self, tmp_path):
        s = _scenario(turns=[Turn(interrupt_on_agent_audio=True)])
        turns = _scenario_turns(s, tmp_path / "s.yaml")
        assert turns[0].interrupt_on_agent_audio

    def test_noise_changes_frames(self, tmp_path):
        audio = tmp_path / "clip.ulaw"
        # Non-silent speech so SNR mixing has energy to scale against.
        import math

        from evaluator.harness.audio import pcm_to_ulaw

        audio.write_bytes(
            pcm_to_ulaw([int(9000 * math.sin(i / 8)) for i in range(1600)])
        )
        clean = _scenario(turns=[Turn(audio="clip.ulaw", hold_ms=0)])
        noisy = _scenario(
            turns=[Turn(audio="clip.ulaw", hold_ms=0,
                        noise=NoiseSpec(synth="brown", snr_db=5.0))]
        )
        t_clean = _scenario_turns(clean, tmp_path / "a.yaml")
        t_noisy = _scenario_turns(noisy, tmp_path / "b.yaml")
        assert t_noisy[0].frames != t_clean[0].frames
        assert len(t_noisy[0].frames) == len(t_clean[0].frames)

    def test_noise_deterministic(self, tmp_path):
        audio = tmp_path / "clip.ulaw"
        import math

        from evaluator.harness.audio import pcm_to_ulaw

        audio.write_bytes(
            pcm_to_ulaw([int(9000 * math.sin(i / 8)) for i in range(1600)])
        )
        s = _scenario(
            turns=[Turn(audio="clip.ulaw", hold_ms=0,
                        noise=NoiseSpec(synth="brown", snr_db=5.0))]
        )
        a = _scenario_turns(s, tmp_path / "a.yaml")
        b = _scenario_turns(s, tmp_path / "a.yaml")
        assert a[0].frames == b[0].frames

    def test_tts_falls_back_to_silence(self, tmp_path):
        # No TTS binary configured → the turn must still produce frames.
        s = _scenario(turns=[Turn(text="hola", tts=True)])
        turns = _scenario_turns(s, tmp_path / "s.yaml", tts_command=None)
        assert len(turns[0].frames) > 0


class TestFetchUsage:
    async def test_no_url_returns_unknown(self):
        async with httpx.AsyncClient() as http:
            cost, usage = await _fetch_usage(None, "c1", http)
        assert cost is None and usage == {}

    async def test_unreachable_returns_unknown(self):
        async with httpx.AsyncClient() as http:
            cost, usage = await _fetch_usage("http://127.0.0.1:1", "c1", http)
        assert cost is None and usage == {}

    async def test_parses_cost(self):
        from fastapi import FastAPI

        app = FastAPI()

        @app.get("/usage/calls/{call_id}")
        def u(call_id: str):
            return {"call_id": call_id, "cost": 0.042, "usage": {"audio_seconds": 12}}

        h = serve_in_thread(app, "127.0.0.1", 18999)
        try:
            async with httpx.AsyncClient() as http:
                cost, usage = await _fetch_usage("http://127.0.0.1:18999/usage", "c1", http)
            assert cost == 0.042
            assert usage["audio_seconds"] == 12
        finally:
            h.stop()


class TestReportEvidence:
    def test_report_links_audio(self, tmp_path):
        run = tmp_path / "run"
        (run / "evidence").mkdir(parents=True)
        (run / "evidence" / "x.caller.wav").write_bytes(b"RIFF")
        manifest = {
            "run_id": "r", "experiment": "e", "rules_version": "v",
            "dataset": "d", "dataset_hash": "h", "candidates": [{"name": "A"}],
        }
        (run / "manifest.json").write_text(json.dumps(manifest))
        case = {
            "case_id": "A/s1/r0", "call_id": "c", "scenario_id": "s1",
            "problem_id": "simple_booking", "candidate": "A", "repetition": 0,
            "verdict": "pass", "duration_s": 1.0,
            "audio": {"caller": "evidence/x.caller.wav"},
            "interrupts": [{"turn": 0, "at_ms": 100, "agent_tail_ms": 50}],
        }
        (run / "cases.jsonl").write_text(json.dumps(case) + "\n")

        from evaluator.report.render import render_report

        out = render_report(run)
        page = out.read_text()
        assert 'href="evidence/x.caller.wav"' in page
        assert "barge-in" in page
