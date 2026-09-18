"""Per-connection pipeline assembly.

One socket = one CallContext, one ToolBox, one Pipeline, one PipelineWorker.
Nothing here is shared across calls: Run All holds ten sockets open and
problem 2 bursts twenty.

Audio runs at the telephony wire rate end to end: Twilio Media Streams
carries 8 kHz µ-law, so the transport, pipeline params, VAD, Deepgram STT
and ElevenLabs TTS (pcm_8000) are all configured at 8 kHz. The serializer's
µ-law <-> PCM conversion then never resamples — see
agent.voice.twilio for the soxr evidence behind that constraint.
"""
from __future__ import annotations

from typing import Any

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from agent.brain import prompts
from agent.brain.tools import ToolBox
from agent.voice.context import CallContext
from agent.voice.tap import TranscriptTap
from agent.voice.twilio import ProsperTwilioSerializer

# Twilio Media Streams wire rate. 20 ms frames of 8 kHz µ-law.
TELEPHONY_SAMPLE_RATE = 8000

__all__ = ["TELEPHONY_SAMPLE_RATE", "build_worker", "phone_hint_greeting", "transport_params"]


def phone_hint_greeting(ctx: Any) -> str:
    """Developer context for the first turn.

    With a resolved hint, at most the patient's given name is used: caller id
    is a hint, never identification, so the model must still run
    lookup_patient (name plus date of birth or national id) before
    confirm_patient. Without a hint the greeting stays generic. Third-party
    callers are explicitly accounted for: the person answering may not be
    the patient.
    """
    given_name = (getattr(ctx, "phone_hint_match", None) or {}).get("given_name")
    if given_name:
        return (
            f"The phone is ringing. Caller id suggests the caller may be {given_name}; "
            f"greet them warmly by name. Caller id is only a hint, never identification: "
            f"do not read, confirm or reveal any record detail until lookup_patient has "
            f"matched their spoken name with their date of birth or national id and "
            f"confirm_patient has succeeded. The person on the line may not be the "
            f"patient; if their details do not match the hint, drop it silently and "
            f"continue normally. Ask how you can help."
        )
    return (
        "The phone is ringing. Greet the caller briefly in a polite "
        "Spanish clinic manner and ask how you can help. If a chart "
        "hint was provided, greet them personally without revealing "
        "any detail they have not confirmed."
    )


def transport_params(ctx: CallContext, settings: Any) -> FastAPIWebsocketParams:
    return FastAPIWebsocketParams(
        audio_in_enabled=True,
        audio_in_sample_rate=TELEPHONY_SAMPLE_RATE,
        audio_out_enabled=True,
        audio_out_sample_rate=TELEPHONY_SAMPLE_RATE,
        serializer=ProsperTwilioSerializer(ctx),
        session_timeout=settings.max_call_minutes * 60,
        add_wav_header=False,
    )


def build_worker(
    transport: FastAPIWebsocketTransport,
    ctx: CallContext,
    settings: Any,
    *,
    with_services: bool = True,
) -> PipelineWorker:
    """Assemble one pipeline. One call per invocation.

    ``with_services=False`` builds a transport-only pipeline (no Deepgram,
    ElevenLabs, Helmcode or VAD) for offline smoke tests and handshakes.
    """
    toolbox = ToolBox(ctx, settings)

    parts: list[Any] = [transport.input()]
    context: LLMContext | None = None
    assistant_aggregator = None

    if with_services:
        stt = DeepgramSTTService(
            api_key=settings.deepgram_api_key,
            sample_rate=TELEPHONY_SAMPLE_RATE,
            settings=DeepgramSTTService.Settings(
                model=settings.deepgram_stt_model,
                language=settings.deepgram_stt_language,
                smart_format=True,
            ),
        )

        tts = ElevenLabsTTSService(
            api_key=settings.elevenlabs_api_key,
            sample_rate=TELEPHONY_SAMPLE_RATE,
            settings=ElevenLabsTTSService.Settings(
                model=settings.elevenlabs_tts_model,
                voice=settings.elevenlabs_voice_id,
            ),
        )

        llm = OpenAILLMService(
            api_key=settings.helmcode_api_key,
            base_url=settings.helmcode_base_url,
            settings=OpenAILLMService.Settings(
                model=settings.agent_model,
                system_instruction=prompts.SYSTEM_PROMPT,
            ),
        )

        context = LLMContext(tools=toolbox.tools())
        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
        )

        parts += [
            stt,
            TranscriptTap(ctx, "caller"),
            user_aggregator,
            llm,
            TranscriptTap(ctx, "assistant"),
            tts,
        ]

    parts.append(transport.output())
    if assistant_aggregator is not None:
        parts.append(assistant_aggregator)

    pipeline = Pipeline(parts)

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=TELEPHONY_SAMPLE_RATE,
            audio_out_sample_rate=TELEPHONY_SAMPLE_RATE,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        idle_timeout_secs=180,  # harness cuts silent calls anyway
    )

    async def _end_call(reason: str) -> None:
        ctx.mark_stopped()
        ctx.audit("call_ended", {"reason": reason, "elapsed_s": round(ctx.elapsed_seconds(), 1)})
        # Posts a cancel on the worker bus; the runner (outside the pipeline
        # task tree) performs the actual teardown, so no deadlock here.
        await worker.cancel()

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport: Any, client: Any) -> None:
        ctx.audit("client_connected", {})
        # Caller-id hint: bounded wait for the harness `start` event, then a
        # private directory search. Never authenticates anyone; the hint only
        # personalises the greeting and never enters the confirmation registry.
        await toolbox.prepare_phone_hint()
        ctx.audit("greeting_prepared", {"hint_used": ctx.phone_hint_match is not None})
        if context is not None:
            context.add_message({"role": "developer", "content": phone_hint_greeting(ctx)})
            await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport: Any, client: Any) -> None:
        # Submission happens once, in the server endpoint's finally block —
        # not here, so a teardown race can never double-POST.
        await _end_call("client_disconnected")

    @transport.event_handler("on_session_timeout")
    async def on_session_timeout(transport: Any, client: Any) -> None:
        await _end_call("session_timeout")

    return worker
