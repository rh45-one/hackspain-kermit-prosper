"""Offline tests for the Gemini Live voice core.

Covers the Gemini-path serializer (wire identity handling, no REST hang-up,
8 kHz rate guard), the Twilio <-> Gemini audio bridge (rate conversion,
interruption reset, malformed frames), and the dependency-guarded factory
(settings pinned to gemini-3.8-live, audio modality, existing prompt and
ToolBox, per-socket instances) exercised through a fake service class. No
network, no credentials; google-genai is absent in this environment, which
is exactly what the dependency guard must handle.
"""
from __future__ import annotations

import json
from typing import ClassVar

import pytest
from pipecat.clocks.system_clock import SystemClock
from pipecat.frames.frames import (
    InputAudioRawFrame,
    InterruptionFrame,
    TTSAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessorSetup
from pipecat.utils.asyncio.task_manager import TaskManager

from agent.audio.converter import TelephonyGeminiConverter
from agent.brain import prompts
from agent.voice.context import CallContext
from agent.voice.gemini_live import (
    GEMINI_LIVE_MODEL,
    GeminiInputBridge,
    GeminiOutputBridge,
    GeminiProsperTwilioSerializer,
    create_gemini_live_service,
    gemini_live_available,
)


def make_ctx(tmp_path) -> CallContext:
    return CallContext(data_dir=str(tmp_path / "data"))


async def make_serializer(tmp_path) -> tuple[GeminiProsperTwilioSerializer, CallContext]:
    ctx = make_ctx(tmp_path)
    serializer = GeminiProsperTwilioSerializer(ctx)
    await serializer.setup(
        FrameProcessorSetup(
            clock=SystemClock(),
            task_manager=TaskManager(),
            pipeline_worker=None,
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
        )
    )
    return serializer, ctx


def start_message(call_sid: str = "CA-gemini") -> dict:
    return {
        "event": "start",
        "start": {
            "callSid": call_sid,
            "streamSid": "SM-gemini",
            "customParameters": {"call_id": call_sid, "from_number": "+34612345678"},
        },
        "sequenceNumber": "1",
    }


# ---- serializer: identity and lifecycle -----------------------------------


async def test_start_captures_identity_and_no_rest_hangup(tmp_path):
    serializer, ctx = await make_serializer(tmp_path)

    assert await serializer.deserialize(json.dumps(start_message())) is None
    assert await serializer.deserialize(json.dumps({"event": "connected"})) is None
    assert await serializer.deserialize(json.dumps({"event": "stop"})) is None

    assert ctx.call_id == "CA-gemini"
    assert ctx.stream_sid == "SM-gemini"
    assert ctx.from_number == "+34612345678"
    assert ctx.stopped is True
    assert (tmp_path / "data" / "calls" / "CA-gemini.jsonl").exists()
    # EndFrame is a safe no-op: auto_hang_up stays off, no Twilio REST call.
    from pipecat.frames.frames import EndFrame

    assert await serializer.serialize(EndFrame()) is None


async def test_serializer_refuses_non_wire_rate(tmp_path):
    """Rate conversion belongs to the bridge; a misconfigured pipeline fails fast."""
    ctx = make_ctx(tmp_path)
    serializer = GeminiProsperTwilioSerializer(ctx)
    with pytest.raises(ValueError, match="8 kHz"):
        await serializer.setup(
            FrameProcessorSetup(
                clock=SystemClock(),
                task_manager=TaskManager(),
                pipeline_worker=None,
                audio_in_sample_rate=16000,
                audio_out_sample_rate=16000,
            )
        )


# ---- audio bridge -----------------------------------------------------------


def test_input_bridge_upscales_twilio_audio_to_gemini_rate(tmp_path):
    ctx = make_ctx(tmp_path)
    bridge = GeminiInputBridge(ctx)

    frame = InputAudioRawFrame(audio=b"\x00\x10" * 160, sample_rate=8000, num_channels=1)
    converted = bridge._convert(frame)

    assert converted is not None
    assert converted.sample_rate == 16000
    assert len(converted.audio) >= 638  # ~20 ms at 16 kHz, streamed immediately


def test_output_bridge_downscales_gemini_audio_to_wire_rate(tmp_path):
    ctx = make_ctx(tmp_path)
    bridge = GeminiOutputBridge(ctx)

    frame = TTSAudioRawFrame(audio=b"\x00\x10" * 480, sample_rate=24000, num_channels=1)
    converted = bridge._convert(frame)

    assert converted is not None
    assert converted.sample_rate == 8000
    assert len(converted.audio) == 320  # 160 samples of µ-law-ready PCM16 (20 ms)


def test_bridges_pass_through_correct_rates_and_non_audio(tmp_path):
    ctx = make_ctx(tmp_path)
    in_bridge = GeminiInputBridge(ctx)
    out_bridge = GeminiOutputBridge(ctx)

    gemini_rate = InputAudioRawFrame(audio=b"\x00\x10" * 320, sample_rate=16000, num_channels=1)
    assert in_bridge._convert(gemini_rate) is gemini_rate

    wire_rate = TTSAudioRawFrame(audio=b"\x00\x10" * 160, sample_rate=8000, num_channels=1)
    assert out_bridge._convert(wire_rate) is wire_rate

    text = InterruptionFrame()  # non-audio frame handled in process_frame
    assert in_bridge._convert(text) is None
    assert out_bridge._convert(text) is None

    # The wrong kind of audio frame is passed through untouched by each side.
    stray_tts = TTSAudioRawFrame(audio=b"\x00\x10" * 480, sample_rate=24000, num_channels=1)
    assert in_bridge._convert(stray_tts) is None
    stray_in = InputAudioRawFrame(audio=b"\x00\x10" * 160, sample_rate=8000, num_channels=1)
    assert out_bridge._convert(stray_in) is None


async def test_bridge_resets_on_interruption(tmp_path):
    ctx = make_ctx(tmp_path)
    converter = TelephonyGeminiConverter()
    in_bridge = GeminiInputBridge(ctx, converter)
    await in_bridge.process_frame(
        InputAudioRawFrame(audio=b"\x00\x10" * 160, sample_rate=8000, num_channels=1),
        FrameDirection.DOWNSTREAM,
    )
    assert converter.gemini_input_samples_out > 0

    await in_bridge.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)

    assert converter.resets == 1
    assert len(converter.gemini_input) == 0
    assert in_bridge.counters["resets"] == 1
    assert ctx.stopped is False  # a barge-in never ends the call


def test_bridge_counts_malformed_frames_without_raising(tmp_path):
    ctx = make_ctx(tmp_path)
    converter = TelephonyGeminiConverter()
    in_bridge = GeminiInputBridge(ctx, converter)
    out_bridge = GeminiOutputBridge(ctx, converter)

    torn = InputAudioRawFrame(audio=b"\x00\x10\x00", sample_rate=8000, num_channels=1)
    assert in_bridge._convert(torn) is None
    odd_rate = InputAudioRawFrame(audio=b"\x00\x10" * 160, sample_rate=44100, num_channels=1)
    assert in_bridge._convert(odd_rate) is None
    bad_out = TTSAudioRawFrame(audio=b"\x00\x10\x00", sample_rate=24000, num_channels=1)
    assert out_bridge._convert(bad_out) is None

    assert in_bridge.counters["malformed_frames"] == 3
    assert out_bridge.counters == in_bridge.counters  # shared converter


# ---- end-to-end frame direction (the integration defect) --------------------


class _CapturingInput(GeminiInputBridge):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.pushed: list = []

    async def push_frame(self, frame, direction=None):
        self.pushed.append(frame)


class _CapturingOutput(GeminiOutputBridge):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.pushed: list = []

    async def push_frame(self, frame, direction=None):
        self.pushed.append(frame)


async def test_frame_direction_end_to_end_through_both_bridges(tmp_path):
    """The coordinator-found integration defect, guarded forever.

    Both pipecat legs flow DOWNSTREAM: transport.input() -> [input bridge] ->
    Gemini service, and Gemini service -> [output bridge] -> transport.
    8 kHz InputAudio must REACH Gemini as 16 kHz and 24 kHz TTSAudio must
    REACH the transport leg as 8 kHz.
    """
    ctx = make_ctx(tmp_path)
    converter = TelephonyGeminiConverter()
    in_bridge = _CapturingInput(ctx, converter)
    out_bridge = _CapturingOutput(ctx, converter)
    downstream = FrameDirection.DOWNSTREAM

    await in_bridge.process_frame(
        InputAudioRawFrame(audio=b"\x00\x10" * 160, sample_rate=8000, num_channels=1),
        downstream,
    )
    audio_out = [f for f in in_bridge.pushed if isinstance(f, InputAudioRawFrame)]
    assert audio_out, "input bridge must forward the converted frame"
    assert audio_out[-1].sample_rate == 16000
    assert len(audio_out[-1].audio) >= 638  # ~20 ms at 16 kHz

    await out_bridge.process_frame(
        TTSAudioRawFrame(audio=b"\x00\x10" * 480, sample_rate=24000, num_channels=1),
        downstream,
    )
    tts_out = [f for f in out_bridge.pushed if isinstance(f, TTSAudioRawFrame)]
    assert tts_out, "output bridge must forward the converted frame"
    assert tts_out[-1].sample_rate == 8000
    assert len(tts_out[-1].audio) == 320  # 160 samples of PCM16 (20 ms)

    # Interruption resets the SHARED converter through either bridge.
    await in_bridge.process_frame(InterruptionFrame(), downstream)
    assert converter.resets == 1
    await out_bridge.process_frame(InterruptionFrame(), downstream)
    assert converter.resets == 2


# ---- dependency-guarded factory ---------------------------------------------


class FakeSettings:
    model_config: ClassVar[dict] = {"extra": "allow"}

    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


class FakeGeminiService:
    """Constructor-recording fake; never touches the network."""

    Settings = FakeSettings
    instances: ClassVar[list[FakeGeminiService]] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        FakeGeminiService.instances.append(self)


class _SettingsStub:
    gemini_api_key = "fake-key"
    gemini_voice_id = "Aoede"


class _ToolboxStub:
    def __init__(self) -> None:
        self.tools = lambda: [self._tool]

    def _tool(self) -> None:  # pragma: no cover - shape only
        """A tool."""


def test_factory_is_dependency_guarded():
    """This environment has no google-genai: the factory must return None."""
    if gemini_live_available():
        pytest.skip("google-genai installed; guard path not reachable here")
    assert create_gemini_live_service(_SettingsStub(), _ToolboxStub()) is None


def test_factory_pins_model_modality_prompt_and_tools(monkeypatch):
    import agent.voice.gemini_live as gl

    monkeypatch.setattr(gl, "gemini_live_available", lambda: True)
    FakeGeminiService.instances = []
    toolbox = _ToolboxStub()

    service = create_gemini_live_service(_SettingsStub(), toolbox, service_cls=FakeGeminiService)

    assert isinstance(service, FakeGeminiService)
    kwargs = service.kwargs
    assert kwargs["api_key"] == "fake-key"
    settings = kwargs["settings"]
    assert settings.model == GEMINI_LIVE_MODEL == "gemini-3.8-live"
    assert str(settings.modalities) == "AUDIO"  # audio modality, not text
    assert not hasattr(settings, "thinking") or settings.thinking is None
    assert kwargs["system_instruction"] == prompts.SYSTEM_PROMPT
    assert kwargs["tools"] == toolbox.tools()  # registry-validated ToolBox


def test_factory_hands_the_turns_to_local_vad(monkeypatch):
    """Server VAD off, because its endpointing is too slow for this clock.

    Gemini takes ~5 s of silence to close a caller turn. Local VAD closes one
    in under a second, and over the ~24 exchanges these calls run that is the
    difference between finishing inside the three-minute cap and being cut off
    — 15 of 20 calls died on that cap.

    This was tried and reverted once, when a call lost the caller's "Hello.":
    with server VAD off, pipecat forwards audio only while _user_is_speaking
    (llm.py:1746), so a missed onset buries the turn. The risk is now measured
    instead of feared — Silero detects this telephony path at full volume, at
    -12 dB and at -22 dB, for a long sentence and for a bare "Hello." — and
    the matching analyzer lives in agent.voice.pipeline. The two halves are
    one decision; neither is safe alone.
    """
    import agent.voice.gemini_live as gl

    if gl.GeminiVADParams is None:  # pragma: no cover - needs google-genai
        pytest.skip("google-genai absent; GeminiVADParams unavailable")

    monkeypatch.setattr(gl, "gemini_live_available", lambda: True)
    FakeGeminiService.instances = []

    service = create_gemini_live_service(
        _SettingsStub(), _ToolboxStub(), service_cls=FakeGeminiService
    )

    vad = service.kwargs["settings"].vad
    assert vad is not None, "VAD must be configured explicitly, not left at the default"
    assert vad.disabled is True


def test_factory_pins_the_spoken_language_to_spanish(monkeypatch):
    """Regression: a Spanish caller answered in English after one turn.

    pipecat leaves ``speech_config.language_code`` at ``en-US``. On a live
    call the agent greeted in Spanish and then switched to English for the
    rest of the conversation, mishearing the caller's constraints with it.
    The clinic is in Madrid, so the wire default is Spanish; the system
    prompt still governs following a caller into another language.
    """
    import agent.voice.gemini_live as gl

    monkeypatch.setattr(gl, "gemini_live_available", lambda: True)
    FakeGeminiService.instances = []

    service = create_gemini_live_service(
        _SettingsStub(), _ToolboxStub(), service_cls=FakeGeminiService
    )
    assert service.kwargs["settings"].language == "es-ES"

    # Overridable per deployment, for the multilingual problems.
    configured = _SettingsStub()
    configured.gemini_language = "ca-ES"
    service = create_gemini_live_service(
        configured, _ToolboxStub(), service_cls=FakeGeminiService
    )
    assert service.kwargs["settings"].language == "ca-ES"


def test_factory_creates_one_instance_per_socket(monkeypatch):
    import agent.voice.gemini_live as gl

    monkeypatch.setattr(gl, "gemini_live_available", lambda: True)
    FakeGeminiService.instances = []

    first = create_gemini_live_service(_SettingsStub(), _ToolboxStub(), service_cls=FakeGeminiService)
    second = create_gemini_live_service(_SettingsStub(), _ToolboxStub(), service_cls=FakeGeminiService)

    assert first is not second
    assert len(FakeGeminiService.instances) == 2  # never cached, never shared


def test_factory_requires_credentials(monkeypatch):
    import agent.voice.gemini_live as gl

    monkeypatch.setattr(gl, "gemini_live_available", lambda: True)
    FakeGeminiService.instances = []
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    keyless = _SettingsStub()
    keyless.gemini_api_key = ""
    assert create_gemini_live_service(keyless, _ToolboxStub(), service_cls=FakeGeminiService) is None
    assert FakeGeminiService.instances == []

    # Env fallback works when the settings object has no key attribute.
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    bare = object()
    service = create_gemini_live_service(bare, _ToolboxStub(), service_cls=FakeGeminiService)
    assert service is not None and service.kwargs["api_key"] == "env-key"
