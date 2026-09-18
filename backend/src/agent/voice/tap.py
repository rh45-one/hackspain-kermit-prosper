"""Pass-through frame processor that records the spoken conversation."""
from __future__ import annotations

from pipecat.frames.frames import Frame, InterimTranscriptionFrame, TextFrame, TranscriptionFrame
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
        elif isinstance(frame, TextFrame) and self._role == "assistant":
            self._ctx.add_transcript("assistant", frame.text)
        await self.push_frame(frame, direction)
