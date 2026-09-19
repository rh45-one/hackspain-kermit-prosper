"""Caller voice synthesis for the WS path (plan §11 voice branch).

Free, offline providers only - `espeak-ng` or `pico2wave`, invoked as
subprocesses so no paid service is ever required for local tests. PCM is
resampled to 8 kHz and µ-law-encoded so it can be played through
`wsclient` like any other caller audio.

Results are cached on disk by (provider, text) so repeated experiment
runs and repetitions do not re-synthesize: the caller voice stays
identical across candidates, which keeps the comparison fair.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import wave
from pathlib import Path

from evaluator.harness.audio import pcm_to_ulaw

FRAME_SAMPLES = 160  # 20 ms of 8 kHz µ-law
CACHE_DIR = Path(".tts-cache")


def provider_available(command: str) -> bool:
    return shutil.which(command) is not None


def _run(cmd: list[str]) -> bytes:
    proc = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {proc.stderr.decode(errors='replace')[:200]}")
    return proc.stdout


def _wav_to_pcm8k(wav_bytes: bytes) -> list[int]:
    """Decode a WAV (mono/stereo, 8/16-bit) and resample to 8 kHz 16-bit PCM.

    Pure-Python linear resampling - no audioop (deprecated in 3.12+).
    """
    import io

    with wave.open(io.BytesIO(wav_bytes)) as w:
        frames = w.readframes(w.getnframes())
        rate, width, channels = w.getframerate(), w.getsampwidth(), w.getnchannels()

    if width == 2:
        samples = [
            int.from_bytes(frames[i : i + 2], "little", signed=True)
            for i in range(0, len(frames) - 1, 2)
        ]
    elif width == 1:
        samples = [(b - 128) << 8 for b in frames]
    else:
        raise ValueError(f"unsupported WAV sample width: {width}")
    if channels == 2:
        samples = [
            (samples[i] + samples[i + 1]) // 2 for i in range(0, len(samples) - 1, 2)
        ]
    elif channels != 1:
        raise ValueError(f"unsupported WAV channels: {channels}")
    if rate != 8000:
        out_len = int(len(samples) * 8000 / rate)
        samples = [
            samples[min(int(i * rate / 8000), len(samples) - 1)] for i in range(out_len)
        ]
    return samples


def synthesize(
    text: str,
    provider: str,
    lang: str = "es",
    cache_dir: Path | str = CACHE_DIR,
) -> list[bytes]:
    """Synthesize `text` to 20 ms µ-law frames, cached by provider+text+lang.

    Raises RuntimeError when the provider binary is missing - callers should
    fall back to silence/fixtures rather than failing the evaluation, since
    a missing TTS is a rig limitation, not an agent failure.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f"{provider}|{lang}|{text}".encode()).hexdigest()[:16]
    cache_file = cache_dir / f"{key}.ulaw"
    if cache_file.exists():
        return _chunk(cache_file.read_bytes())

    if provider == "espeak-ng":
        wav = _run(
            ["espeak-ng", "-v", lang, "-s", "160", "--stdout", text]
        )
    elif provider == "pico2wave":
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            _run(["pico2wave", "-l", f"{lang}-{lang.upper()}", "-w", tmp_path, text])
            wav = Path(tmp_path).read_bytes()
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    else:
        raise ValueError(f"unknown tts provider: {provider!r} (espeak-ng|pico2wave)")

    pcm = _wav_to_pcm8k(wav)
    ulaw = pcm_to_ulaw(pcm)
    cache_file.write_bytes(ulaw)
    return _chunk(ulaw)


def _chunk(ulaw: bytes) -> list[bytes]:
    frames = [ulaw[i : i + FRAME_SAMPLES] for i in range(0, len(ulaw), FRAME_SAMPLES)]
    if frames and len(frames[-1]) < FRAME_SAMPLES:
        frames[-1] = frames[-1].ljust(FRAME_SAMPLES, b"\xff")
    return frames
