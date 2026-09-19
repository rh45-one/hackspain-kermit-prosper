"""Gemini 3.8 Live voice core for the Prosper agent (OpenSpec D2–D4, D9).

Owns the three pieces the Gemini path needs on top of the existing Twilio
wire handling:

- :class:`GeminiProsperTwilioSerializer` — the Prosper-aware Twilio Media
  Streams serializer for the Gemini path: same `connected`/`start`/`stop`
  handling, same callSid/streamSid/from_number capture into the per-socket
  :class:`CallContext`, and never a Twilio REST hang-up. The wire stays at
  8 kHz; all rate conversion to and from Gemini happens in the bridge.
- :class:`GeminiInputBridge` / :class:`GeminiOutputBridge` — two
  direction-explicit frame processors sharing one per-socket converter.
  Pipecat moves frames downstream in both legs (``transport.input()`` to
  service, service to ``transport.output()``), so a single bidirectional
  bridge can never sit in both positions. The input bridge (between
  transport and service) converts Twilio 8 kHz PCM16 up to Gemini's 16 kHz;
  the output bridge (between service and transport) converts Gemini's 24 kHz
  back down to 8 kHz, through :mod:`agent.audio` (never through pipecat's
  python-soxr VHQ stream resampler, which buffers). Both reset the shared
  converter on interruption.
- :func:`create_gemini_live_service` — dependency-guarded factory for a
  per-socket :class:`GeminiLiveLLMService` pinned to ``gemini-3.8-live``,
  audio modality, the existing system prompt and the registry-validated
  ToolBox functions. ToolBox direct functions auto-register in pipecat
  1.11 with ``cancel_on_interruption=True`` — synchronous, blocking
  semantics: a side-effecting tool holds the turn until its validated
  result is back. The pinned model id is not an extended-thinking variant
  and no thinking configuration is set.

One factory call = one socket = one service instance; nothing is cached or
shared across sockets.
"""
from __future__ import annotations

import os
from typing import Any

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    TTSAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from agent.audio.converter import (
    GEMINI_INPUT_RATE,
    GEMINI_OUTPUT_RATE,
    TWILIO_RATE,
    TelephonyGeminiConverter,
)
from agent.voice.context import CallContext
from agent.voice.twilio import ProsperTwilioSerializer

# Guarded: importing pipecat's Gemini Live module requires google-genai,
# which must not be a hard dependency of this module (the factory is
# dependency-guarded and testable with fakes without it).
try:
    from pipecat.services.google.gemini_live.llm import GeminiModalities
except ImportError:  # pragma: no cover - exercised when google-genai is absent
    GeminiModalities = None

# Pinned audio host (OpenSpec D2/D3). Never a thinking variant: this id
# contains no "thinking" marker and the factory sets no thinking config.
GEMINI_LIVE_MODEL = "gemini-3.8-live"

__all__ = [
    "GEMINI_LIVE_MODEL",
    "GeminiInputBridge",
    "GeminiOutputBridge",
    "GeminiProsperTwilioSerializer",
    "create_gemini_live_service",
    "gemini_live_available",
]


class GeminiProsperTwilioSerializer(ProsperTwilioSerializer):
    """Twilio Media Streams serializer for the Gemini Live path.

    Inherits the whole Prosper wire behaviour from the cascade serializer:
    `connected`/`heartbeat` absorbed, `start` captures
    callSid/streamSid/from_number into the per-socket CallContext (the
    audit trail moves to the callSid), `stop` marks the call stopped,
    `media` decodes µ-law at the wire rate, and `auto_hang_up` stays off so
    no Twilio REST call is ever attempted.

    Gemini-path contract: the serializer emits/consumes PCM16 at the 8 kHz
    wire rate and ALL rate conversion (8k -> 16k in, 24k -> 8k out) happens
    in the :class:`GeminiInputBridge` / :class:`GeminiOutputBridge` pair.
    Setup therefore refuses any other
    rate: silently resampling here would engage the broken python-soxr VHQ
    stream path.
    """

    async def setup(self, setup: Any) -> None:
        await super().setup(setup)
        if getattr(self, "_sample_rate", 0) not in (0, TWILIO_RATE):
            raise ValueError(
                "GeminiProsperTwilioSerializer requires 8 kHz pipeline audio; "
                f"got {self._sample_rate}. Rate conversion belongs to "
                "TwilioGeminiAudioBridge, never to the serializer."
            )


class _AudioBridgeBase(FrameProcessor):
    """Shared plumbing for the two direction-explicit Gemini bridges.

    Pipecat pipeline reality: ``transport.input()`` emits
    :class:`InputAudioRawFrame` DOWNSTREAM toward the service, and the service
    emits :class:`TTSAudioRawFrame` DOWNSTREAM toward ``transport.output()``.
    One processor cannot sit both before and after the service, so the
    conversion is split into :class:`GeminiInputBridge` and
    :class:`GeminiOutputBridge`, sharing one per-socket converter.
    """

    def __init__(self, ctx: CallContext, converter: TelephonyGeminiConverter | None = None) -> None:
        super().__init__()
        self._ctx = ctx
        self.converter = converter or TelephonyGeminiConverter()

    @property
    def counters(self) -> dict[str, int]:
        """Flat counter snapshot for the per-call audit (shared converter)."""
        return self.converter.counters()

    async def _reset_on_interrupt(self, frame: Frame, direction: FrameDirection) -> bool:
        """Reset the shared converter on barge-in; True when handled."""
        if isinstance(frame, InterruptionFrame):
            self.converter.reset()
            self._ctx.audit("barge_in_reset", {"resets": self.converter.resets})
            await self.push_frame(frame, direction)
            return True
        return False


class GeminiInputBridge(_AudioBridgeBase):
    """Twilio-side audio -> Gemini input rate (16 kHz).

    Sits BETWEEN ``transport.input()`` and the Gemini service. Pipecat
    delivers input audio downstream, so conversion is applied for
    :class:`InputAudioRawFrame` on any direction: 8 kHz wire frames are
    resampled up, frames already at 16 kHz pass through, anything else is
    counted and dropped.

    Rate conversion and nothing else. It once carried a keep-alive that
    manufactured silence, a watchdog that committed turns by force, and a
    ladder of spoken nudges — all of it propping up Gemini's server-side
    VAD. Turns are decided locally now, so none of that has anything left to
    do, and the machinery had become the problem: the watchdog ended turns
    while callers were still thinking, and a live call has the agent reading
    "[Waiting for user response]" out loud.
    """

    def _convert(self, frame: Frame) -> Frame | None:
        if not isinstance(frame, InputAudioRawFrame):
            return None
        if frame.sample_rate == GEMINI_INPUT_RATE:
            return frame  # already Gemini's input rate
        if frame.sample_rate != TWILIO_RATE:
            self.converter.malformed_frames += 1
            logger.warning("{}: dropping input frame at unexpected rate {}", self.name, frame.sample_rate)
            return None
        if len(frame.audio) % 2:
            self.converter.malformed_frames += 1
            return None
        converted = self.converter.twilio_pcm_to_gemini(frame.audio)
        if not converted:
            return None
        return InputAudioRawFrame(audio=converted, sample_rate=GEMINI_INPUT_RATE, num_channels=1)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if await self._reset_on_interrupt(frame, direction):
            return
        converted = self._convert(frame)
        await self.push_frame(converted if converted is not None else frame, direction)


class GeminiOutputBridge(_AudioBridgeBase):
    """Gemini output audio (24 kHz) -> Twilio wire rate (8 kHz).

    Sits BETWEEN the Gemini service and ``transport.output()``. The service
    emits TTS audio downstream, so conversion is applied for
    :class:`TTSAudioRawFrame` on any direction: 24 kHz frames are resampled
    down, frames already at 8 kHz pass through, anything else is counted and
    dropped.
    """

    def _convert(self, frame: Frame) -> Frame | None:
        if not isinstance(frame, TTSAudioRawFrame):
            return None
        if frame.sample_rate == TWILIO_RATE:
            return frame  # already at the wire rate
        if frame.sample_rate != GEMINI_OUTPUT_RATE:
            self.converter.malformed_frames += 1
            logger.warning("{}: dropping output frame at unexpected rate {}", self.name, frame.sample_rate)
            return None
        if len(frame.audio) % 2:
            self.converter.malformed_frames += 1
            return None
        converted = self.converter.gemini_pcm_to_twilio(frame.audio)
        if not converted:
            return None
        return TTSAudioRawFrame(audio=converted, sample_rate=TWILIO_RATE, num_channels=1)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if await self._reset_on_interrupt(frame, direction):
            return
        converted = self._convert(frame)
        if converted is not None:
            await self.push_frame(converted, direction)
        else:
            await self.push_frame(frame, direction)


def gemini_live_available() -> bool:
    """True when the google-genai dependency is importable."""
    try:
        import google.genai  # noqa: F401 - availability probe

        return True
    except ImportError:
        return False


def _gemini_api_key(settings: Any) -> str:
    """Resolve the Google AI key from settings, falling back to the env."""
    key = getattr(settings, "gemini_api_key", "") or os.getenv("GEMINI_API_KEY", "")
    return str(key or "")


def _gemini_voice_id(settings: Any) -> str:
    """Resolve the Gemini voice, falling back to the service default."""
    return str(getattr(settings, "gemini_voice_id", "") or "Charon")


def _gemini_language(settings: Any) -> str | None:
    """The spoken language code, or None to let the model choose.

    None is the default, and it is the point: a pinned code is an accent.
    With ``es-ES`` pinned the agent answered an English caller in English
    but with a Spanish accent, because the voice was still configured for
    Spanish. Unset, the model picks the language AND the accent from what it
    hears, which is what a caller switching language actually needs.

    pipecat's own default is ``en-US``, which drags a Spanish call into
    English, so this is never simply left alone — it is explicitly cleared.
    Set GEMINI_LANGUAGE to pin one anyway.
    """
    return str(getattr(settings, "gemini_language", "") or "") or None


def create_gemini_live_service(
    settings: Any,
    toolbox: Any,
    *,
    service_cls: Any = None,
) -> Any | None:
    """Build one Gemini Live service for ONE socket. Never shared.

    Dependency-guarded: returns ``None`` (with a loud log) when the
    ``google-genai`` package is missing, so the host can roll back
    explicitly instead of crashing at import time.

    Args:
        settings: Application settings (reads ``gemini_api_key`` /
            ``gemini_voice_id``, falling back to ``GEMINI_API_KEY`` env).
        toolbox: The per-socket registry-validated
            :class:`~agent.brain.tools.ToolBox`; its bound methods are
            passed as direct functions, which pipecat 1.11 auto-registers
            with synchronous, turn-blocking semantics
            (``cancel_on_interruption=True``) — the required behaviour for
            side-effecting scheduling tools.
        service_cls: Override for the service class (test seam; defaults to
            the real ``GeminiLiveLLMService``).

    Returns:
        The service instance, or ``None`` when the dependency is missing.
    """
    from agent.brain import prompts

    if not gemini_live_available():
        logger.error(
            "google-genai is not installed; Gemini Live unavailable "
            "(explicit rollback to cascade is a configuration decision)"
        )
        return None

    if service_cls is None:
        from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService

        service_cls = GeminiLiveLLMService

    # The audio modality value; the enum comes from pipecat when its Gemini
    # module is importable, otherwise the wire value is used verbatim.
    audio_modality = GeminiModalities.AUDIO if GeminiModalities is not None else "AUDIO"

    api_key = _gemini_api_key(settings)
    if not api_key:
        logger.error("GEMINI_API_KEY not set; Gemini Live unavailable (no credentials)")
        return None

    # Settings pinned for the Prosper path: the exact model id (no
    # extended-thinking variant), audio modality only, no thinking config
    # — and one instance per socket, created by this call.
    #
    # Server-side VAD is OFF and the pipeline's own Silero decides the turns.
    #
    # Measured, this is worth about four seconds per exchange. Gemini's own
    # endpointing takes ~5 s of silence to close a caller turn; local VAD
    # closes it in under one. Over the ~24 exchanges these calls run, that is
    # the difference between finishing inside the three-minute cap and being
    # cut off mid-booking, which is how 15 of 20 calls died.
    #
    # It was tried once before and reverted, because a call lost the caller's
    # "Hello." and sat silent — with server VAD off, pipecat only forwards
    # audio while _user_is_speaking (llm.py:1746), so a missed onset buries
    # the turn. That risk was real and is now measured rather than feared:
    # Silero detects this telephony path at full volume, at -12 dB and at
    # -22 dB, for a long sentence and for a bare "Hello.". See
    # agent.voice.pipeline for the telephony VAD parameters that go with it.
    #
    # Gemini decides its own turns, with its own defaults. It is trained for
    # phone calls, it is the one listening to the audio, and every attempt to
    # help it here has cost more than it bought: a local detector left the
    # agent deaf when it missed an onset, a faster one cut callers off
    # mid-sentence, and a watchdog on top of that had the agent reading
    # "[Waiting for user response]" out loud.
    #
    # The number that justified all of it was misread. ~4.8 s was measured to
    # `turn_complete`, which marks the end of the MODEL's turn — endpointing
    # plus generating the whole reply — not how long Gemini waits to decide a
    # caller has finished. There was never a measurement saying it is slow.
    #
    # So: nothing is set here. If a real measurement ever shows the wait is
    # the problem, GeminiVADParams(silence_duration_ms=...) is the knob, and
    # it is still Gemini deciding.
    vad_params = None
    service = service_cls(
        api_key=api_key,
        settings=service_cls.Settings(
            model=GEMINI_LIVE_MODEL,
            modalities=audio_modality,
            voice=_gemini_voice_id(settings),
            # None clears pipecat's en-US default and leaves the choice to
            # the model; a value pins both language and accent.
            language=_gemini_language(settings),
            vad=vad_params,
        ),
        system_instruction=prompts.SYSTEM_PROMPT,
        tools=toolbox.tools(),
    )
    logger.info(
        "Gemini Live service created: model={} language={} turn_detection={} "
        "(per-socket instance)",
        GEMINI_LIVE_MODEL,
        _gemini_language(settings) or "elegido por el modelo",
        "gemini",
    )
    return service
