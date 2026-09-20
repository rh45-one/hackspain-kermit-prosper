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


def test_existing_clinic_is_verified_without_rebinding(tmp_path):
    from evaluator.clinic.dataset import Dataset
    from evaluator.clinic.server import create_app
    from evaluator.runner.experiment import verify_clinic

    dataset = Dataset.load(Path(__file__).parents[1] / "data/clinic_dataset.json")
    server = serve_in_thread(create_app(dataset), "127.0.0.1", 0)
    url = f"http://127.0.0.1:{server.listener.getsockname()[1]}"
    try:
        verify_clinic(url, dataset, "pk-local-eval")
        changed = Dataset({**dataset.raw, "meta": {"version": "different"}})
        with pytest.raises(ValueError, match="dataset"):
            verify_clinic(url, changed, "pk-local-eval")
        assert httpx.get(f"{url}/api/v1/health").status_code == 200
    finally:
        server.stop()


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
        for name in ("smoke", "switchboard", "smoke-text"):
            config = ExperimentConfig.load(str(root / "experiments" / f"{name}.yaml"))
            assert config.clinic_port == 18090
            for candidate in config.candidates:
                assert candidate.kind == "double"
                assert candidate.port in (18770, 18771, 18772)
                assert candidate.start_command is None
                assert candidate.ws_url is None
                # The text smoke talks to the double it starts, nothing else.
                assert candidate.text_url in (
                    None,
                    f"http://127.0.0.1:{candidate.port}",
                )

    def test_no_experiment_targets_the_scored_voice_server(self):
        """Port 7860 carries the scored calls; nothing here may point at it."""
        root = Path(__file__).resolve().parent.parent
        for path in sorted((root / "experiments").glob("*.yaml")):
            text = path.read_text(encoding="utf-8")
            assert ":7860" not in text, f"{path.name} targets the scored server"

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
        turns, rig_errors = _scenario_turns(s, tmp_path / "s.yaml")
        assert len(turns) == 1
        assert not turns[0].interrupt_on_agent_audio
        assert all(len(f) == 160 for f in turns[0].frames)
        assert rig_errors == []  # a turn with no text asks for nothing

    def test_text_turn_without_voice_is_a_rig_error(self, tmp_path):
        """A spoken line played as silence is a rig defect, never a verdict."""
        s = _scenario(turns=[Turn(text="hola", hold_ms=0)])
        _, rig_errors = _scenario_turns(s, tmp_path / "s.yaml")
        assert rig_errors and "silence" in rig_errors[0]

    def test_interrupt_flag_propagates(self, tmp_path):
        s = _scenario(turns=[Turn(interrupt_on_agent_audio=True)])
        turns, _ = _scenario_turns(s, tmp_path / "s.yaml")
        assert turns[0].interrupt_on_agent_audio

    def test_hold_is_adaptive_on_the_voice_path(self, tmp_path):
        """The caller waits for the agent to stop talking before speaking."""
        s = _scenario(turns=[Turn(text="hola", tts=True, hold_ms=1200)])
        turns, _ = _scenario_turns(s, tmp_path / "s.yaml", tts_command="espeak-ng")
        assert turns[0].hold_ms == 1200
        assert turns[0].max_hold_ms > turns[0].hold_ms

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
        t_clean, _ = _scenario_turns(clean, tmp_path / "a.yaml")
        t_noisy, _ = _scenario_turns(noisy, tmp_path / "b.yaml")
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
        a, _ = _scenario_turns(s, tmp_path / "a.yaml")
        b, _ = _scenario_turns(s, tmp_path / "a.yaml")
        assert a[0].frames == b[0].frames

    def test_tts_without_provider_is_a_rig_error(self, tmp_path):
        # No TTS configured → frames still exist, but the case must be
        # invalidated rather than scored against an agent fed silence.
        s = _scenario(turns=[Turn(text="hola", tts=True)])
        turns, rig_errors = _scenario_turns(s, tmp_path / "s.yaml", tts_command=None)
        assert len(turns[0].frames) > 0
        assert rig_errors and "tts_command" in rig_errors[0]

    def test_tts_missing_binary_is_a_rig_error(self, tmp_path):
        s = _scenario(turns=[Turn(text="hola", tts=True)])
        _, rig_errors = _scenario_turns(s, tmp_path / "s.yaml", tts_command="no-such-tts")
        assert rig_errors and "TTS failed" in rig_errors[0]


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

    def test_report_is_readable_without_the_schema(self, tmp_path):
        """The bench is the gate now: non-authors read this page."""
        run = tmp_path / "run"
        run.mkdir()
        manifest = {
            "run_id": "r", "experiment": "e", "rules_version": "v",
            "dataset": "d", "dataset_hash": "h", "candidates": [{"name": "A"}],
        }
        (run / "manifest.json").write_text(json.dumps(manifest))
        case = {
            "case_id": "A/np-001/r0", "call_id": "c", "scenario_id": "np-001",
            "problem_id": "new_patient", "candidate": "A", "repetition": 0,
            "verdict": "fail", "failure_signal": "record_mismatch",
            "categories": ["identity_error"], "duration_s": 1.0,
            "field_diffs": [
                {"verb": "BOOK", "field": "policy_id",
                 "expected": "mapfre", "got": "sanitas"}
            ],
            "submitted": [{"action": "BOOK", "patient_id": "P1", "provider_id": "PR1",
                           "location_id": "centro", "appointment_type_id": "review",
                           "slot": "2026-09-21T09:00:00+02:00", "policy_id": "sanitas"}],
        }
        (run / "cases.jsonl").write_text(json.dumps(case) + "\n")

        from evaluator.report.render import render_report

        page = render_report(run).read_text()
        assert "INCORRECTA" in page and "record_mismatch" not in page
        assert "identificó mal al paciente" in page  # not "identity_error"
        assert "plan / póliza" in page  # not "policy_id"
        assert "paciente nuevo" in page  # not just "new_patient"
        # The shape of a real loss: almost right, and still zero points.
        assert "1 de 6 campos mal" in page

    def test_report_separates_stable_from_flaky(self, tmp_path):
        """1/3 and 3/3 are not the same result and must not read the same."""
        run = tmp_path / "run"
        run.mkdir()
        manifest = {
            "run_id": "r", "experiment": "e", "rules_version": "v",
            "dataset": "d", "dataset_hash": "h", "candidates": [{"name": "A"}],
        }
        (run / "manifest.json").write_text(json.dumps(manifest))

        def case(scenario, rep, verdict):
            return {
                "case_id": f"A/{scenario}/r{rep}", "call_id": "c",
                "scenario_id": scenario, "problem_id": "simple_booking",
                "candidate": "A", "repetition": rep, "verdict": verdict,
                "duration_s": 1.0,
            }

        cases = [
            case("steady", 0, "pass"), case("steady", 1, "pass"),
            case("broken", 0, "fail"), case("broken", 1, "fail"),
            case("flaky", 0, "pass"), case("flaky", 1, "fail"),
        ]
        (run / "cases.jsonl").write_text(
            "\n".join(json.dumps(c) for c in cases) + "\n"
        )

        from evaluator.report.render import render_report

        page = render_report(run).read_text()
        assert "Estabilidad por escenario" in page
        assert "INESTABLE" in page
        assert "1 de 3 escenarios" in page  # the noise band, spelled out
        assert "una sola ejecución no" in page
        assert "siempre incorrecta" in page

    def test_report_omits_stability_with_one_repetition(self, tmp_path):
        run = tmp_path / "run"
        run.mkdir()
        (run / "manifest.json").write_text(json.dumps({
            "run_id": "r", "experiment": "e", "rules_version": "v",
            "dataset": "d", "dataset_hash": "h", "candidates": [{"name": "A"}],
        }))
        (run / "cases.jsonl").write_text(json.dumps({
            "case_id": "A/s/r0", "call_id": "c", "scenario_id": "s",
            "problem_id": "simple_booking", "candidate": "A", "repetition": 0,
            "verdict": "pass", "duration_s": 1.0,
        }) + "\n")

        from evaluator.report.render import render_report

        assert "Estabilidad por escenario" not in render_report(run).read_text()

    def test_report_warns_about_the_fixture(self, tmp_path):
        """A green local run is not a point: the report has to say so."""
        run = tmp_path / "run"
        run.mkdir()
        manifest = {
            "run_id": "r", "experiment": "e", "rules_version": "v",
            "dataset": "d", "dataset_hash": "h", "candidates": [{"name": "A"}],
            "dataset_profile": {
                "name": "seed-v1",
                "note": "No es la clínica oficial",
                "counts": {"patients": 6, "providers": 7},
            },
        }
        (run / "manifest.json").write_text(json.dumps(manifest))
        case = {
            "case_id": "A/s1/r0", "call_id": "c", "scenario_id": "s1",
            "problem_id": "simple_booking", "candidate": "A", "repetition": 0,
            "verdict": "pass", "duration_s": 1.0, "checks_not_run": ["leak_check"],
        }
        (run / "cases.jsonl").write_text(json.dumps(case) + "\n")

        from evaluator.report.render import render_report

        page = render_report(run).read_text()
        assert "no es el veredicto oficial" in page.lower()
        assert "No es la clínica oficial" in page
        assert "~3.000" in page  # real clinic size, next to the fixture's 6
        # The unevaluated check is printed, and in Spanish.
        assert "comprobación de privacidad" in page


class TestVariantMatrix:
    """One candidate block, several environments: the matrix expands, not the config."""

    def test_variants_become_their_own_candidates_with_merged_env(self):
        from evaluator.models import CandidateConfig, expand_candidates

        base = CandidateConfig(
            name="agent",
            ws_url="ws://127.0.0.1:17860/ws",
            env={"PROSPER_API_BASE_URL": "http://127.0.0.1:18090", "SHARED": "yes"},
            variants={"a": {"PROMPT": "v1"}, "b": {"PROMPT": "v2", "SHARED": "no"}},
        )
        expanded = expand_candidates([base])
        assert [c.name for c in expanded] == ["agent-a", "agent-b"]
        assert expanded[0].env["PROMPT"] == "v1"
        assert expanded[0].env["SHARED"] == "yes"  # base env survives
        assert expanded[1].env["SHARED"] == "no"  # the variant wins
        assert all(c.variants == {} for c in expanded)  # no re-expansion
        assert all(c.ws_url == base.ws_url for c in expanded)

    def test_a_candidate_without_variants_passes_through(self):
        from evaluator.models import CandidateConfig, expand_candidates

        plain = CandidateConfig(name="solo", kind="double", port=18770)
        assert expand_candidates([plain]) == [plain]

    def test_duplicate_names_are_refused(self):
        from evaluator.models import CandidateConfig, expand_candidates

        candidates = [
            CandidateConfig(name="agent", variants={"a": {"X": "1"}}),
            CandidateConfig(name="agent-a"),
        ]
        with pytest.raises(ValueError, match="duplicados"):
            expand_candidates(candidates)

    def test_config_load_expands_the_matrix(self, tmp_path):
        config = tmp_path / "matrix.yaml"
        config.write_text(
            """
name: matrix
clinic_dataset: ../data/clinic_dataset.json
candidates:
  - name: agent
    ws_url: ws://127.0.0.1:17860/ws
    env:
      PROSPER_API_BASE_URL: http://127.0.0.1:18090
    variants:
      sin-memoria:
        PROMPT_VARIANT: none
      con-memoria:
        PROMPT_VARIANT: history
scenarios:
  - mini.yaml
""",
            encoding="utf-8",
        )
        loaded = ExperimentConfig.load(str(config))
        assert [c.name for c in loaded.candidates] == ["agent-sin-memoria", "agent-con-memoria"]
        assert loaded.candidates[1].env == {
            "PROSPER_API_BASE_URL": "http://127.0.0.1:18090",
            "PROMPT_VARIANT": "history",
        }

    def test_the_run_manifest_carries_no_variant_matrix(self, tmp_path):
        """The manifest describes what ran, so `variants` must already be flat.

        A reader of `manifest.json` sees one row per configuration that
        actually executed; a nested template would let a report show a
        candidate that never ran.
        """
        config = tmp_path / "matrix.yaml"
        config.write_text(
            """
name: matrix
clinic_dataset: ../data/clinic_dataset.json
candidates:
  - name: agent
    ws_url: ws://127.0.0.1:17860/ws
    variants:
      a: {PROMPT_VARIANT: none}
scenarios:
  - mini.yaml
""",
            encoding="utf-8",
        )
        loaded = ExperimentConfig.load(str(config))
        dumped = [c.model_dump(exclude={"start_command"}) for c in loaded.candidates]
        assert dumped == [
            {**dumped[0], "name": "agent-a", "env": {"PROMPT_VARIANT": "none"}, "variants": {}}
        ]
