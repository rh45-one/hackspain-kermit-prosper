"""Streaming audio primitives for the Twilio <-> Gemini voice path.

This package exists for one reason: the Gemini Live path must convert
between the Twilio wire format (8 kHz µ-law, 20 ms frames) and Gemini's
PCM formats (16 kHz input, 24 kHz output) while streaming 20 ms chunks in
real time.

pipecat 1.11's built-in stream resamplers use python-soxr with quality
"VHQ", and python-soxr 1.0.0 VHQ buffers every chunk and only emits in
delayed bursts — verified empirically on this machine (a 20 ms 8 kHz chunk
resampled to 16 kHz produced zero output samples for the first chunks and
then a multi-chunk burst). That is unusable for telephony, so this package
implements its own drift-free streaming linear resampler, a µ-law codec
over the stdlib reference (`audioop`), bounded ring buffers with an
explicit overflow policy, and the Twilio <-> Gemini converter that ties
them together.

Everything here is offline, dependency-free (stdlib + numpy) and
deterministically testable against the Python audio reference.
"""
from agent.audio.buffers import BoundedRingBuffer
from agent.audio.codec import MuLawCodec
from agent.audio.converter import (
    GEMINI_INPUT_RATE,
    GEMINI_OUTPUT_RATE,
    TWILIO_FRAME_MS,
    TWILIO_RATE,
    TelephonyGeminiConverter,
)
from agent.audio.resampler import LinearStreamResampler

__all__ = [
    "GEMINI_INPUT_RATE",
    "GEMINI_OUTPUT_RATE",
    "TWILIO_FRAME_MS",
    "TWILIO_RATE",
    "BoundedRingBuffer",
    "LinearStreamResampler",
    "MuLawCodec",
    "TelephonyGeminiConverter",
]
