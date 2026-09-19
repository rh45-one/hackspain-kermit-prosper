"""TTS: cache layout, WAV decode/resample, provider fallback contract."""
from __future__ import annotations

import hashlib
import io
import wave

import pytest

from evaluator.harness import tts
from evaluator.harness.audio import pcm_to_ulaw


def _make_wav(rate: int = 16000, n: int = 800, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            (i % 400 - 200).to_bytes(2, "little", signed=True)
            for i in range(n * channels)
        )
        w.writeframes(frames)
    return buf.getvalue()


class TestWavDecode:
    def test_resamples_to_8k(self):
        pcm = tts._wav_to_pcm8k(_make_wav(rate=16000, n=800))
        assert len(pcm) == 400  # half the samples at half the rate

    def test_keeps_8k_unchanged(self):
        pcm = tts._wav_to_pcm8k(_make_wav(rate=8000, n=320))
        assert len(pcm) == 320

    def test_stereo_to_mono(self):
        pcm = tts._wav_to_pcm8k(_make_wav(rate=8000, n=200, channels=2))
        assert len(pcm) == 200


class TestChunk:
    def test_pads_tail(self):
        frames = tts._chunk(b"\xff" * 200)
        assert len(frames) == 2
        assert len(frames[1]) == 160

    def test_empty(self):
        assert tts._chunk(b"") == []


class TestSynthesizeFallback:
    def test_unknown_provider_raises(self, tmp_path):
        with pytest.raises(ValueError, match="unknown tts provider"):
            tts.synthesize("hola", "not-a-provider", cache_dir=tmp_path)

    def test_cache_hit_skips_provider(self, tmp_path, monkeypatch):
        # Pre-seed the cache entry synthesize() would produce, then prove
        # it returns the cached bytes without invoking the binary.
        text, provider, lang = "hola", "espeak-ng", "es"
        key = hashlib.sha256(f"{provider}|{lang}|{text}".encode()).hexdigest()[:16]
        cached = pcm_to_ulaw([0] * 160)
        (tmp_path / f"{key}.ulaw").write_bytes(cached)

        def boom(*args, **kwargs):
            raise AssertionError("provider must not run on cache hit")

        monkeypatch.setattr(tts, "_run", boom)
        frames = tts.synthesize(text, provider, lang=lang, cache_dir=tmp_path)
        assert b"".join(frames) == cached


class TestProviderDetection:
    def test_missing_binary(self):
        assert tts.provider_available("definitely-not-a-real-binary-xyz") is False

    def test_existing_binary(self):
        assert tts.provider_available("python3") is True
