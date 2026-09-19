"""Audio utilities: µ-law codec, WAV output, SNR noise mixing, synth noise."""
from __future__ import annotations

import io
import math
import wave

from evaluator.harness.audio import (
    mix_with_noise,
    pcm_to_ulaw,
    rms,
    synth_noise,
    ulaw_to_pcm,
    ulaw_to_wav,
)


class TestUlawCodec:
    def test_roundtrip_small_signal(self):
        samples = [0, 100, -100, 500, -500, 1000, -1000]
        decoded = ulaw_to_pcm(pcm_to_ulaw(samples))
        for orig, got in zip(samples, decoded, strict=True):
            # µ-law is lossy; small signals keep ~±5% precision.
            assert abs(got - orig) <= max(30, abs(orig) * 0.08)

    def test_silence_byte_decodes_near_zero(self):
        assert abs(ulaw_to_pcm(b"\xff")[0]) <= 10

    def test_clip_at_extremes(self):
        assert len(pcm_to_ulaw([40000, -40000])) == 2  # clipped, no crash


class TestWav:
    def test_ulaw_to_wav_header(self):
        wav_bytes = ulaw_to_wav(b"\xff" * 160)
        with wave.open(io.BytesIO(wav_bytes)) as w:
            assert w.getframerate() == 8000
            assert w.getnchannels() == 1
            assert w.getsampwidth() == 2
            assert w.getnframes() == 160


class TestSynthNoise:
    def test_deterministic(self):
        assert synth_noise(400, seed=7) == synth_noise(400, seed=7)

    def test_seed_changes_output(self):
        assert synth_noise(400, seed=7) != synth_noise(400, seed=8)

    def test_nonzero_energy(self):
        assert rms(synth_noise(800, seed=1)) > 0


def _speech() -> list[bytes]:
    # Tone-ish PCM so the frames carry real energy.
    pcm = [int(12000 * math.sin(i / 10)) for i in range(320)]
    return [pcm_to_ulaw(pcm[:160]), pcm_to_ulaw(pcm[160:])]


class TestMixWithNoise:
    def test_output_same_shape(self):
        mixed = mix_with_noise(_speech(), [pcm_to_ulaw(synth_noise(160, seed=3))])
        assert len(mixed) == 2
        assert all(len(f) == 160 for f in mixed)

    def test_noise_changes_signal(self):
        speech = _speech()
        mixed = mix_with_noise(speech, [pcm_to_ulaw(synth_noise(160, seed=3))])
        assert mixed != speech

    def test_high_snr_barely_changes(self):
        speech = _speech()
        noise = [pcm_to_ulaw(synth_noise(160, seed=3))]
        quiet = mix_with_noise(speech, noise, snr_db=40.0)
        loud = mix_with_noise(speech, noise, snr_db=0.0)
        quiet_diff = sum(
            abs(a - b)
            for fa, fb in zip(speech, quiet, strict=True)
            for a, b in zip(ulaw_to_pcm(fa), ulaw_to_pcm(fb), strict=True)
        )
        loud_diff = sum(
            abs(a - b)
            for fa, fb in zip(speech, loud, strict=True)
            for a, b in zip(ulaw_to_pcm(fa), ulaw_to_pcm(fb), strict=True)
        )
        assert loud_diff > quiet_diff

    def test_empty_noise_is_noop(self):
        speech = _speech()
        assert mix_with_noise(speech, []) == speech


class TestUlawSeconds:
    def test_a_frame_is_twenty_milliseconds(self):
        from evaluator.harness.audio import ulaw_seconds

        assert ulaw_seconds(160) == 0.02
        assert ulaw_seconds(8000) == 1.0
        assert ulaw_seconds(0) == 0.0

    def test_it_uses_the_wire_sample_rate(self):
        from evaluator.harness.audio import ulaw_seconds

        assert ulaw_seconds(16000) == 2.0
