"""Deterministic tests for the Twilio <-> Gemini streaming converter.

Every conversion is compared against the Python audio reference (stdlib
audioop for µ-law, an independent whole-signal linear-interpolation
reference for resampling). No network, no model, no pipecat pipeline.
"""
from __future__ import annotations

import audioop
import math

import numpy as np
import pytest

from agent.audio.codec import MuLawCodec
from agent.audio.converter import (
    BYTES_PER_TWILIO_FRAME,
    GEMINI_INPUT_RATE,
    GEMINI_OUTPUT_RATE,
    TWILIO_RATE,
    TelephonyGeminiConverter,
)
from agent.audio.resampler import LinearStreamResampler


def sine_pcm(seconds: float, rate: int, freq: float = 440.0, amplitude: int = 8000) -> bytes:
    """Deterministic int16 mono sine PCM."""
    n = int(seconds * rate)
    t = np.arange(n) / rate
    x = (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.int16)
    return x.tobytes()


def reference_linear_resample(pcm: bytes, in_rate: int, out_rate: int) -> bytes:
    """Independent whole-signal linear-interpolation reference.

    Same grid as LinearStreamResampler: output sample n sits at input
    position n * in/out, clamped to the last sample. A stream that never
    sees a future sample emits every grid point p <= (n-1); a single
    one-shot call may additionally emit one clamped tail point p in
    (n-1, n) — hence the ``<= 1`` tail tolerance asserted in the tests.
    """
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    if in_rate == out_rate or x.size == 0:
        return pcm
    n_out = math.floor((x.size - 1) * out_rate / in_rate) + 1
    pos = np.arange(n_out) * in_rate / out_rate
    idx = np.floor(pos).astype(np.int64)
    frac = pos - idx
    idx = np.clip(idx, 0, x.size - 1)
    nxt = np.clip(idx + 1, 0, x.size - 1)
    out = x[idx] * (1 - frac) + x[nxt] * frac
    return np.clip(out, -32768, 32767).astype(np.int16).tobytes()


def ulaw_frames(seconds: float, freq: float = 300.0) -> list[bytes]:
    """A signal as a list of 20 ms 8 kHz µ-law frames (the wire shape)."""
    pcm = sine_pcm(seconds, TWILIO_RATE, freq)
    ulaw = audioop.lin2ulaw(pcm, 2)
    return [ulaw[i : i + BYTES_PER_TWILIO_FRAME] for i in range(0, len(ulaw), BYTES_PER_TWILIO_FRAME)]


# ---- codec vs the Python audio reference ---------------------------------


def test_mulaw_codec_matches_audioop_reference():
    pcm = sine_pcm(0.05, TWILIO_RATE)
    codec = MuLawCodec()

    ulaw = codec.encode(pcm)
    assert ulaw == audioop.lin2ulaw(pcm, 2)
    assert codec.decode(ulaw) == audioop.ulaw2lin(ulaw, 2)


# ---- resampler: chunk-boundary invariance and reference agreement --------


@pytest.mark.parametrize("in_rate,out_rate", [(TWILIO_RATE, GEMINI_INPUT_RATE), (GEMINI_OUTPUT_RATE, TWILIO_RATE)])
def test_resampler_is_chunk_boundary_invariant(in_rate, out_rate):
    """Chunked streaming must equal one-shot streaming, byte for byte."""
    pcm = sine_pcm(0.5, in_rate)

    one_shot = LinearStreamResampler(in_rate, out_rate).resample(pcm)

    resampler = LinearStreamResampler(in_rate, out_rate)
    streamed = b""
    rng = np.random.default_rng(42)  # deterministic arbitrary chunking
    pos = 0
    while pos < len(pcm):
        size = 2 * int(rng.integers(1, 333))  # odd sample counts, arbitrary boundaries
        streamed += resampler.resample(pcm[pos : pos + size])
        pos += size

    # Chunked streaming equals the one-shot and the independent whole-signal
    # reference exactly: the grid is absolute and boundary-independent.
    reference = reference_linear_resample(pcm, in_rate, out_rate)
    assert streamed == reference
    assert one_shot == reference


@pytest.mark.parametrize("in_rate,out_rate", [(TWILIO_RATE, GEMINI_INPUT_RATE), (GEMINI_OUTPUT_RATE, TWILIO_RATE)])
def test_resampler_matches_whole_signal_reference(in_rate, out_rate):
    pcm = sine_pcm(0.3, in_rate)
    one_shot = LinearStreamResampler(in_rate, out_rate).resample(pcm)
    assert one_shot == reference_linear_resample(pcm, in_rate, out_rate)


def test_resampler_emits_output_for_every_chunk_no_delayed_bursts():
    """The soxr VHQ failure mode: zero output for the first chunks.

    Per-chunk output may differ from 640 by at most the withheld tail
    sample; the cumulative grid stays exact (320k - 1 samples after k
    frames, one pending tail point).
    """
    resampler = LinearStreamResampler(TWILIO_RATE, GEMINI_INPUT_RATE)
    pcm = sine_pcm(0.1, TWILIO_RATE)
    frames = [pcm[i * 320 : (i + 1) * 320] for i in range(5)]
    cumulative = 0
    for i, frame in enumerate(frames):
        out = resampler.resample(frame)
        assert len(out) >= 638  # immediate output, never a delayed burst
        cumulative += len(out) // 2
        assert cumulative == 320 * (i + 1) - 1  # exact grid, one tail pending


def test_resampler_bypass_and_reset():
    bypass = LinearStreamResampler(8000, 8000)
    assert bypass.bypassed
    assert bypass.resample(b"\x01\x02") == b"\x01\x02"

    resampler = LinearStreamResampler(TWILIO_RATE, GEMINI_INPUT_RATE)
    resampler.resample(sine_pcm(0.05, TWILIO_RATE))
    resampler.reset()
    # After reset the stream starts from a fresh grid: refeeding the same
    # signal produces the same output as a fresh resampler.
    signal = sine_pcm(0.05, TWILIO_RATE)
    assert resampler.resample(signal) == LinearStreamResampler(TWILIO_RATE, GEMINI_INPUT_RATE).resample(signal)


# ---- converter: direct conversion -----------------------------------------


def test_twilio_ulaw_to_gemini_matches_reference_chain():
    ulaw = b"".join(ulaw_frames(0.2))
    converter = TelephonyGeminiConverter()

    converted = converter.twilio_ulaw_to_gemini(ulaw)

    expected = reference_linear_resample(audioop.ulaw2lin(ulaw, 2), TWILIO_RATE, GEMINI_INPUT_RATE)
    assert converted == expected
    # 1600 input samples -> 3199 output samples on the exact grid (one
    # pending tail point waits for a next chunk that never comes).
    assert len(converted) == 2 * (2 * len(ulaw) - 1)


def test_gemini_pcm_to_twilio_ulaw_matches_reference_chain():
    pcm24 = sine_pcm(0.2, GEMINI_OUTPUT_RATE)
    converter = TelephonyGeminiConverter()

    converted = converter.gemini_pcm_to_twilio_ulaw(pcm24)

    expected_pcm8 = reference_linear_resample(pcm24, GEMINI_OUTPUT_RATE, TWILIO_RATE)
    expected_ulaw = audioop.lin2ulaw(expected_pcm8, 2)
    # Down 3x the grid never lands inside the final input sample interval,
    # so one-shot equals the reference exactly here.
    assert converted == expected_ulaw
    assert len(converted) == len(pcm24) * TWILIO_RATE // GEMINI_OUTPUT_RATE // 2


def test_direct_conversion_streams_frame_by_frame_without_delay():
    """Each 20 ms frame in yields its converted bytes immediately."""
    converter = TelephonyGeminiConverter()
    frames = ulaw_frames(0.4)
    assert all(len(f) == BYTES_PER_TWILIO_FRAME for f in frames)

    per_frame_outputs = [converter.twilio_ulaw_to_gemini(f) for f in frames]
    assert all(len(out) >= 638 for out in per_frame_outputs)  # ~20 ms @ 16 kHz, immediate

    # Streaming per frame equals the whole-signal reference exactly.
    joined = b"".join(per_frame_outputs)
    reference = reference_linear_resample(
        audioop.ulaw2lin(b"".join(frames), 2), TWILIO_RATE, GEMINI_INPUT_RATE
    )
    assert joined == reference


# ---- converter: queued bounded mode ---------------------------------------


def test_submit_twilio_frame_is_available_immediately():
    """Anti-soxr acceptance: no delayed bursts, output flows per frame."""
    converter = TelephonyGeminiConverter()
    frames = ulaw_frames(0.2)

    for frame in frames:
        converter.submit_twilio_frame(frame)
        got = converter.read_gemini_input(1 << 20)
        assert len(got) >= 638  # 20 ms of 16 kHz PCM16, immediately, no burst lag


def test_cumulative_sample_counts_and_durations():
    converter = TelephonyGeminiConverter()
    in_seconds = 1.5
    for frame in ulaw_frames(in_seconds):
        converter.submit_twilio_frame(frame)

    # Cumulative counts stay on the exact grid minus the one pending tail
    # point that waits for a next chunk.
    assert converter.gemini_input_samples_out == int(in_seconds * GEMINI_INPUT_RATE) - 1
    assert converter.twilio_samples_in == int(in_seconds * TWILIO_RATE) - 1
    assert converter.twilio_frames_in == int(in_seconds * 1000 / 20) - 1
    # Durations agree across the conversion boundary within one sample.
    assert abs(converter.twilio_input_seconds - in_seconds) <= 1 / TWILIO_RATE
    assert abs(converter.gemini_input_seconds - converter.twilio_input_seconds) <= 1 / TWILIO_RATE

    out_seconds = 0.8
    converter.submit_gemini_audio(sine_pcm(out_seconds, GEMINI_OUTPUT_RATE))
    assert converter.gemini_samples_in == int(out_seconds * GEMINI_OUTPUT_RATE)
    assert converter.twilio_samples_out == int(out_seconds * TWILIO_RATE)
    assert math.isclose(converter.gemini_output_seconds, converter.twilio_output_seconds, rel_tol=1e-9)


def test_output_high_water_overflow_drops_oldest_and_counts():
    # 200 ms output buffer: 160 µ-law bytes per 20 ms -> 1600 bytes capacity.
    converter = TelephonyGeminiConverter(buffer_ms=200)
    assert converter.twilio_output.capacity_bytes == 1600
    # Never read the output: fill it 3x over.
    for _ in range(30):
        converter.submit_gemini_audio(sine_pcm(0.02, GEMINI_OUTPUT_RATE))

    assert converter.twilio_output.dropped_bytes > 0
    assert converter.twilio_output.overflows > 0
    assert len(converter.twilio_output) == 1600  # hard capacity, never grows
    assert converter.twilio_output.peak_level == 1600
    # The freshest audio survives: a full drain returns exactly the capacity.
    drained = converter.read_twilio_output(1 << 20)
    assert len(drained) == 1600


def test_read_underrun_is_counted_not_fatal():
    converter = TelephonyGeminiConverter()
    converter.submit_twilio_frame(ulaw_frames(0.02)[0])

    got = converter.read_gemini_input(1 << 20)
    assert got  # immediate output for the first frame
    # Reading again with nothing queued: short read + underrun counter
    # (the initial >= max_bytes read counts one, the empty read adds one).
    assert converter.read_gemini_input(640) == b""
    assert converter.gemini_input.underruns == 2


def test_interruption_reset_clears_state_and_counts():
    converter = TelephonyGeminiConverter()
    for frame in ulaw_frames(0.1):
        converter.submit_twilio_frame(frame)
    converter.submit_gemini_audio(sine_pcm(0.1, GEMINI_OUTPUT_RATE))
    assert len(converter.gemini_input) > 0 and len(converter.twilio_output) > 0

    converter.reset()

    assert len(converter.gemini_input) == 0
    assert len(converter.twilio_output) == 0
    assert converter.resets == 1
    # Cumulative counters survive the reset (exact grid minus tail point).
    assert converter.twilio_samples_in == 799
    # And the resamplers start a fresh grid afterwards.
    fresh = TelephonyGeminiConverter()
    signal = ulaw_frames(0.05)
    assert [converter.twilio_ulaw_to_gemini(f) for f in signal] == [
        fresh.twilio_ulaw_to_gemini(f) for f in signal
    ]


def test_malformed_frames_are_counted_not_raised():
    converter = TelephonyGeminiConverter()

    # Odd-length PCM16 payload (a torn byte): dropped, counted, no raise.
    assert len(converter.gemini_pcm_to_twilio(b"\x01\x02\x03")) == 2  # 1 sample + dropped tail
    assert converter.malformed_frames == 1
    assert len(converter.twilio_pcm_to_gemini(b"\x01\x02\x03")) == 2
    assert converter.malformed_frames == 2

    # Empty payloads are no-ops, not errors.
    assert converter.twilio_ulaw_to_gemini(b"") == b""
    assert converter.gemini_pcm_to_twilio_ulaw(b"") == b""


def test_buffer_high_water_mark_flags_before_capacity():
    buf = TelephonyGeminiConverter(buffer_ms=100).twilio_output
    assert buf.capacity_bytes == 800
    assert not buf.is_high_water
    buf.write(b"\x00" * 720)  # exactly the 0.9 high-water mark
    assert buf.is_high_water
