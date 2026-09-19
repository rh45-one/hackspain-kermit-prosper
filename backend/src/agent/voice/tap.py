"""Pass-through frame processor that records the spoken conversation."""
from __future__ import annotations

from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from agent.voice.context import CallContext


class TranscriptTap(FrameProcessor):
    """Audits caller transcriptions or assistant text depending on `role`."""

    def __init__(self, ctx: CallContext, role: str) -> None:
        super().__init__()
        self._ctx = ctx
        self._role = role

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame) and not isinstance(frame, InterimTranscriptionFrame):
            if self._role == "caller" or direction == FrameDirection.DOWNSTREAM:
                self._ctx.add_transcript(self._role, frame.text)
        elif isinstance(frame, LLMTextFrame) and self._role == "assistant":
            # LLMTextFrame only, never TextFrame at large: a speech-to-speech
            # service pushes the same chunk twice, once as LLMTextFrame and
            # once as TTSTextFrame (both TextFrame subclasses), which doubled
            # every assistant line in the audit and in Jev's snapshot. Both
            # engines emit LLMTextFrame, so this records each chunk once.
            self._ctx.add_transcript("assistant", frame.text)
        await self.push_frame(frame, direction)


class AudioOutputTap(FrameProcessor):
    """Records that the agent emitted audible audio without retaining it."""

    def __init__(self, ctx: CallContext) -> None:
        super().__init__()
        self._ctx = ctx

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSAudioRawFrame) and frame.audio:
            self._ctx.mark_pipeline_stage("assistant_audio_emitted")
        await self.push_frame(frame, direction)
