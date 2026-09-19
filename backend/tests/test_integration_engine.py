"""Offline integration tests: engine selection, Gemini wiring, Jev flow.

No network, no credentials: the Gemini service is injected through
``gemini_service_factory`` and Pipeline/PipelineWorker are recorded with
fakes, so build_worker's real assembly logic runs end to end without any
external dependency. The 20-socket test is lightweight (no audio, no API).
"""
from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import pytest
from pipecat.frames.frames import Frame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from agent.orgs import DEFAULT_ORG_ID
from agent.voice import pipeline as pl
from agent.voice.context import CallContext
from agent.voice.gemini_live import GeminiInputBridge, GeminiOutputBridge


class EngineSettings:
    """Programmatic settings stub covering every knob the pipeline reads."""

    def __init__(self, *, voice_engine: str = "cascade", gemini_api_key: str = "") -> None:
        self.voice_engine = voice_engine
        self.gemini_api_key = gemini_api_key
        self.gemini_voice_id = "Charon"
        self.prosper_api_key = ""
        self.prosper_api_base_url = "https://api.test"
        self.typesafe_api_key = ""
        self.jev_timeout_seconds = 0.3
        self.jev_min_confidence = 0.5
        self.max_call_minutes = 3
        self.data_dir = "./data"
        # cascade-path service knobs (only touched when with_services=True)
        self.deepgram_api_key = ""
        self.deepgram_stt_model = "nova-3"
        self.deepgram_stt_language = "multi"
        self.elevenlabs_api_key = ""
        self.elevenlabs_voice_id = ""
        self.elevenlabs_tts_model = "eleven_turbo_v2_5"
        self.helmcode_api_key = "fake-helmcode-key"
        self.helmcode_base_url = "https://api.test/v1"
        self.agent_model = "deepseek-v4-flash"


class FakeTransport:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}
        self.input_processor = FrameProcessor()
        self.output_processor = FrameProcessor()

    def event_handler(self, name: str):
        def register(fn):
            self.handlers[name] = fn
            return fn

        return register

    def input(self) -> FrameProcessor:
        return self.input_processor

    def output(self) -> FrameProcessor:
        return self.output_processor


class FakePipeline:
    built: ClassVar[list[list[Any]]] = []

    def __init__(self, parts: list[Any]) -> None:
        self.parts = parts
        FakePipeline.built.append(parts)


class FakeWorker:
    def __init__(self, pipeline: Any, params: Any = None, idle_timeout_secs: int = 0) -> None:
        self.pipeline = pipeline
        self.queued: list[list[Frame]] = []
        self.cancel_count = 0

    async def queue_frames(self, frames: list[Frame]) -> None:
        self.queued.append(frames)

    async def cancel(self) -> None:
        self.cancel_count += 1


class RecordedGeminiService:
    instances: ClassVar[list[RecordedGeminiService]] = []

    class Settings:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        RecordedGeminiService.instances.append(self)


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    monkeypatch.setattr(pl, "Pipeline", FakePipeline)
    monkeypatch.setattr(pl, "PipelineWorker", FakeWorker)
    FakePipeline.built = []
    RecordedGeminiService.instances = []
    yield


def make_ctx(tmp_path, call_id: str) -> CallContext:
    return CallContext(data_dir=str(tmp_path / "data"), call_id=call_id)


def build(tmp_path, call_id: str, settings: Any):
    transport = FakeTransport()
    worker = pl.build_worker(
        transport,
        make_ctx(tmp_path, call_id),
        settings,
        gemini_service_factory=RecordedGeminiService,
    )
    return transport, worker


# ---- engine selection --------------------------------------------------------
async def test_default_engine_is_cascade(tmp_path):
    build(tmp_path, "CA-cascade", EngineSettings())

    # The cascade path is structurally unchanged: no Gemini bridges present.
    parts = FakePipeline.built[-1]
    assert not any(isinstance(p, (GeminiInputBridge, GeminiOutputBridge)) for p in parts)


async def test_invalid_engine_fails_fast(tmp_path):
    with pytest.raises(ValueError):
        pl.resolve_voice_engine(EngineSettings(voice_engine="whisper"))


async def test_gemini_without_key_fails_fast(tmp_path):
    """Requested gemini_live without GEMINI_API_KEY must not start as cascade."""
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        pl.resolve_voice_engine(EngineSettings(voice_engine="gemini_live", gemini_api_key=""))


async def test_engine_choice_is_audited_per_socket(tmp_path):
    build(tmp_path, "CA-audit", EngineSettings())
    blob = (tmp_path / "data" / DEFAULT_ORG_ID / "calls" / "CA-audit.jsonl").read_text(encoding="utf-8")
    assert '"event": "engine_selected"' in blob
    assert '"engine": "cascade"' in blob


# ---- Gemini pipeline wiring ---------------------------------------------------
async def test_gemini_engine_builds_bridged_pipeline(tmp_path):
    settings = EngineSettings(voice_engine="gemini_live", gemini_api_key="k")
    _transport, _worker = build(tmp_path, "CA-gemini", settings)

    parts = FakePipeline.built[-1]
    kinds = [type(p).__name__ for p in parts]
    # input -> user aggregator -> caller tap -> input bridge -> service ->
    # output bridge -> assistant tap -> output -> assistant aggregator.
    # The aggregators are required: the LLMContextFrame they emit is what
    # sets the service's _ready_for_realtime_input flag. The user aggregator
    # sits BEFORE the bridge because it owns the local VAD analyzer, which
    # must see the wire-rate 8 kHz frames the pipeline is configured for; the
    # caller tap sits AFTER it because the aggregator consumes the upstream
    # user TranscriptionFrames the tap needs to record.
    assert kinds == [
        "FrameProcessor",
        "LLMUserAggregator",
        "TranscriptTap",
        "GeminiInputBridge",
        "RecordedGeminiService",
        "GeminiOutputBridge",
        "TranscriptTap",
        "FrameProcessor",
        "LLMAssistantAggregator",
    ]
    service = next(p for p in parts if isinstance(p, RecordedGeminiService))
    assert service.kwargs["api_key"] == "k"

    toolbox_service = RecordedGeminiService.instances[-1]
    assert toolbox_service.kwargs["tools"] == service.kwargs["tools"]


async def test_no_second_turn_detector_runs_in_our_process(tmp_path):
    """One thing decides when a caller has finished, and it is Gemini.

    A local analyzer here was tried twice. The first time a missed onset left
    the agent deaf; the second it drove turns fast enough to cut callers off
    mid-sentence. Gemini is trained for this and is the one listening — a
    second detector is one more thing to be wrong.
    """
    settings = EngineSettings(voice_engine="gemini_live", gemini_api_key="k")
    build(tmp_path, "CA-vad", settings)

    parts = FakePipeline.built[-1]
    user_agg = next(p for p in parts if type(p).__name__ == "LLMUserAggregator")
    assert user_agg._params.vad_analyzer is None


async def test_caller_tap_sits_where_upstream_transcriptions_reach_it(tmp_path):
    """Regression: a whole call recorded with zero caller turns.

    The Gemini service pushes user TranscriptionFrames UPSTREAM, and
    LLMUserAggregator consumes TranscriptionFrame without forwarding it. A
    caller tap placed ahead of the aggregator therefore never sees one: the
    audit trail held only assistant lines and assess_current_turn had no
    caller text to assess. The tap has to sit between the aggregator and the
    service, and the frames must survive the bridge in between.
    """
    from pipecat.frames.frames import TranscriptionFrame
    from pipecat.utils.time import time_now_iso8601

    settings = EngineSettings(voice_engine="gemini_live", gemini_api_key="k")
    ctx = make_ctx(tmp_path, "CA-tap")
    pl.build_worker(
        FakeTransport(), ctx, settings, gemini_service_factory=RecordedGeminiService
    )

    parts = FakePipeline.built[-1]
    user_agg = next(p for p in parts if type(p).__name__ == "LLMUserAggregator")
    caller_tap = next(p for p in parts if type(p).__name__ == "TranscriptTap")
    service = next(p for p in parts if isinstance(p, RecordedGeminiService))
    assert parts.index(user_agg) < parts.index(caller_tap) < parts.index(service)

    # The upstream leg the service actually uses: bridge, then tap.
    bridge = next(p for p in parts if isinstance(p, GeminiInputBridge))
    frame = TranscriptionFrame(text="quiero una cita", user_id="", timestamp=time_now_iso8601())
    await bridge.process_frame(frame, FrameDirection.UPSTREAM)
    await caller_tap.process_frame(frame, FrameDirection.UPSTREAM)
    assert any(t["role"] == "caller" for t in ctx.transcript)


async def test_assistant_text_is_recorded_once_per_chunk(tmp_path):
    """A speech-to-speech service emits each chunk as LLMTextFrame AND
    TTSTextFrame; both are TextFrames, so the tap used to log it twice."""
    from pipecat.frames.frames import AggregationType, LLMTextFrame, TTSTextFrame

    from agent.voice.tap import TranscriptTap

    ctx = make_ctx(tmp_path, "CA-dup")
    tap = TranscriptTap(ctx, "assistant")
    await tap.process_frame(LLMTextFrame("Perfecto."), FrameDirection.DOWNSTREAM)
    await tap.process_frame(
        TTSTextFrame("Perfecto.", aggregated_by=AggregationType.SENTENCE),
        FrameDirection.DOWNSTREAM,
    )
    assert [t["text"] for t in ctx.transcript if t["role"] == "assistant"] == ["Perfecto."]


async def test_gemini_tools_come_from_the_registry_validated_toolbox(tmp_path):
    from agent.brain.tools import ToolBox

    settings = EngineSettings(voice_engine="gemini_live", gemini_api_key="k")
    _transport, _ = build(tmp_path, "CA-tools", settings)
    service = RecordedGeminiService.instances[-1]
    names = {getattr(t, "__name__", "") for t in service.kwargs["tools"]}
    assert "assess_current_turn" in names  # Gemini-only advisory tool exposed
    assert "book_appointment" in names

    # Cross-check: a direct ToolBox for the same engine registers the same set.
    toolbox = ToolBox(make_ctx(tmp_path, "CA-tools2"), settings)
    assert toolbox.engine == "gemini_live"
    assert any(t.__name__ == "assess_current_turn" for t in toolbox.tools())
    await toolbox.aclose()


async def test_gemini_greeting_flows_through_context_aggregator(tmp_path):
    settings = EngineSettings(voice_engine="gemini_live", gemini_api_key="k")
    transport, worker = build(tmp_path, "CA-greet", settings)

    await transport.handlers["on_client_connected"](transport, None)

    from pipecat.frames.frames import LLMRunFrame

    frames = [f for batch in worker.queued for f in batch]
    assert any(isinstance(f, LLMRunFrame) for f in frames), (
        "Gemini path must trigger the greeting through LLMRunFrame"
    )
    # The greeting rides in the shared LLMContext as a developer message:
    # the user aggregator turns it into the LLMContextFrame that both
    # speaks the greeting and unlocks the service's realtime input gate.
    parts = FakePipeline.built[-1]
    user_agg = next(
        p for p in parts if type(p).__name__ == "LLMUserAggregator"
    )
    messages = user_agg._context.messages
    assert messages[-1]["role"] == "developer"
    assert "phone is ringing" in messages[-1]["content"]


async def test_per_socket_isolation_across_engines(tmp_path):
    settings = EngineSettings(voice_engine="gemini_live", gemini_api_key="k")
    t1, _ = build(tmp_path, "CA-iso-1", settings)
    t2, _ = build(tmp_path, "CA-iso-2", settings)

    parts1, parts2 = FakePipeline.built[-2], FakePipeline.built[-1]
    bridges1 = [p for p in parts1 if isinstance(p, GeminiInputBridge)]
    bridges2 = [p for p in parts2 if isinstance(p, GeminiInputBridge)]
    assert bridges1[0].converter is not bridges2[0].converter
    assert RecordedGeminiService.instances[-2] is not RecordedGeminiService.instances[-1]
    # Distinct contexts per socket, as everywhere else in the pipeline.
    assert t1 is not t2


async def test_interruption_resets_the_shared_converter(tmp_path):
    settings = EngineSettings(voice_engine="gemini_live", gemini_api_key="k")
    build(tmp_path, "CA-barge", settings)
    parts = FakePipeline.built[-1]
    in_bridge = next(p for p in parts if isinstance(p, GeminiInputBridge))
    out_bridge = next(p for p in parts if isinstance(p, GeminiOutputBridge))
    assert in_bridge.converter is out_bridge.converter

    from pipecat.frames.frames import InputAudioRawFrame, InterruptionFrame

    await in_bridge.process_frame(
        InputAudioRawFrame(audio=b"\x00\x10" * 160, sample_rate=8000, num_channels=1),
        FrameDirection.DOWNSTREAM,
    )
    assert in_bridge.converter.gemini_input_samples_out > 0
    await in_bridge.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
    assert in_bridge.converter.resets == 1
    assert len(in_bridge.converter.gemini_input) == 0


async def test_teardown_is_idempotent_and_releases_sidecars(tmp_path):
    settings = EngineSettings(voice_engine="gemini_live", gemini_api_key="k")
    transport, worker = build(tmp_path, "CA-end", settings)

    await transport.handlers["on_client_disconnected"](transport, None)
    await transport.handlers["on_client_disconnected"](transport, None)

    blob = (tmp_path / "data" / DEFAULT_ORG_ID / "calls" / "CA-end.jsonl").read_text(encoding="utf-8")
    assert blob.count('"event": "socket_stop"') == 1  # mark_stopped is once-only
    assert worker.cancel_count == 2  # cancel is safe to repeat; flush is not


async def test_exactly_once_flush_guard_survives_engine_change(tmp_path):
    """The submitted flag lives on the CallContext, not on the engine."""
    ctx = make_ctx(tmp_path, "CA-flush")
    ctx.submitted = True
    from agent.voice.flush import flush_call

    # Simulate the server's finally block racing twice: the first call marks
    # submitted, the second must be a no-op.
    await flush_call(ctx, EngineSettings())
    assert ctx.submitted is True
    queued_before = list(ctx.queued_actions)
    await flush_call(ctx, EngineSettings())
    assert ctx.queued_actions == queued_before


async def test_twenty_lightweight_concurrent_sockets_on_gemini(tmp_path):
    settings = EngineSettings(voice_engine="gemini_live", gemini_api_key="k")

    async def one(i: int) -> str:
        transport = FakeTransport()
        call_id = f"CA-burst-{i}"
        worker = pl.build_worker(
            transport,
            make_ctx(tmp_path, call_id),
            settings,
            gemini_service_factory=RecordedGeminiService,
        )
        await transport.handlers["on_client_connected"](transport, None)
        await transport.handlers["on_client_disconnected"](transport, None)
        return call_id, worker

    results = await asyncio.gather(*(one(i) for i in range(20)))
    assert len({call_id for call_id, _ in results}) == 20
    assert len({id(w) for _, w in results}) == 20
    services = RecordedGeminiService.instances[-20:]
    assert len({id(s) for s in services}) == 20  # one service per socket
