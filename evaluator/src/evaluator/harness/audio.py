"""µ-law / PCM helpers: codec, WAV (de)serialisation, noise mixing.

Self-contained - no audioop (deprecated) and no native deps. 8 kHz mono is
the only format the wire contract speaks.
"""
from __future__ import annotations

import io
import math
import wave

BIAS = 0x84
_CLIP = 32635

# G.711 µ-law encoder segment upper bounds (canonical seg_end table): a
# biased sample belongs to the first segment whose bound it fits under.
_EXP_LUT = [255, 511, 1023, 2047, 4095, 8191, 16383, 32767]


def _decode_byte(b: int) -> int:
    b = ~b & 0xFF
    sign = b & 0x80
    exp = (b >> 4) & 0x07
    mant = b & 0x0F
    sample = ((mant << 3) + BIAS) << exp
    sample -= BIAS
    return -sample if sign else sample


def _encode_sample(s: int) -> int:
    sign = 0x80 if s < 0 else 0
    s = min(abs(s), _CLIP) + BIAS
    exp = 7
    # First segment whose upper bound holds the biased sample.
    while exp > 0 and s <= _EXP_LUT[exp - 1]:
        exp -= 1
    mant = (s >> (exp + 3)) & 0x0F
    return ~(sign | (exp << 4) | mant) & 0xFF


def ulaw_to_pcm(data: bytes) -> list[int]:
    return [_decode_byte(b) for b in data]


def pcm_to_ulaw(samples: list[int]) -> bytes:
    return bytes(_encode_sample(s) for s in samples)


def ulaw_to_wav(data: bytes, rate: int = 8000) -> bytes:
    """µ-law bytes → PCM16 WAV bytes (players + STT tools want WAV)."""
    samples = ulaw_to_pcm(data)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(s.to_bytes(2, "little", signed=True) for s in samples))
    return buf.getvalue()


def wav_to_ulaw(wav_bytes: bytes) -> bytes:
    """PCM16 WAV bytes → µ-law bytes. Only uncompressed 8-bit/16-bit mono WAVs."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() not in (1, 2):
            raise ValueError("expected mono 8/16-bit PCM WAV")
        frames = w.readframes(w.getnframes())
        if w.getsampwidth() == 1:
            # unsigned 8-bit → signed
            samples = [b - 128 for b in frames]
            samples = [s << 8 for s in samples]
        else:
            samples = [
                int.from_bytes(frames[i : i + 2], "little", signed=True)
                for i in range(0, len(frames), 2)
            ]
    return pcm_to_ulaw(samples)


def rms(samples: list[int]) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def mix_with_noise(
    speech_frames: list[bytes],
    noise_frames: list[bytes],
    snr_db: float = 5.0,
) -> list[bytes]:
    """Overlay noise on speech at a target SNR (plan §15: 5 dB textures).

    Mixing happens in the linear PCM domain - µ-law is companded, so the
    bytes can't be summed directly. Noise frames loop as needed.
    """
    if not noise_frames:
        return speech_frames
    speech_pcm = [ulaw_to_pcm(f) for f in speech_frames]
    noise_pcm = [ulaw_to_pcm(f) for f in noise_frames]
    noise_flat = [s for frame in noise_pcm for s in frame]
    noise_rms = rms(noise_flat)
    if noise_rms == 0:
        return speech_frames

    out: list[bytes] = []
    n_idx = 0
    for frame in speech_pcm:
        speech_rms = rms(frame)
        target = speech_rms / (10 ** (snr_db / 20)) if speech_rms else 0
        scale = target / noise_rms if noise_rms else 0
        mixed = []
        for s in frame:
            n = noise_flat[n_idx % len(noise_flat)]
            n_idx += 1
            mixed.append(int(max(-32768, min(32767, s + n * scale))))
        out.append(pcm_to_ulaw(mixed))
    return out


def synth_noise(n_samples: int, seed: int = 0, kind: str = "brown") -> list[int]:
    """Deterministic synthetic noise (brownian-ish) for tests and demos.

    Real challenge textures (street/TV/room/car) belong in `audio/` as
    recorded assets - this is only the local approximation.
    """
    samples = []
    state = seed or 1
    acc = 0.0
    for _ in range(n_samples):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        white = ((state >> 16) & 0x7FFF) / 16384 - 1.0
        acc += white * 0.02
        acc *= 0.998
        samples.append(int(acc * 16000))
    return samples
