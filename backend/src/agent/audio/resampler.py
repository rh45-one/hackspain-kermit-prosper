"""Drift-free streaming linear resampler for int16 mono audio.

Why this exists: the Gemini Live path must resample Twilio 8 kHz µ-law to
Gemini 16 kHz PCM (input) and Gemini 24 kHz PCM back to 8 kHz (output) in
20 ms chunks, in real time. pipecat 1.11 builds its stream resamplers on
python-soxr with quality "VHQ", and python-soxr 1.0.0 VHQ buffers chunks
and only emits in delayed bursts — the agent would go deaf and mute. This
resampler is dependency-light (numpy only), emits output for every input
chunk, and keeps the sample grid exact across arbitrary chunk boundaries.

Design: output sample n sits at absolute input position ``n * in/out``.
Interpolation uses the two input samples surrounding that position; a
position beyond the last real sample of a chunk waits for the next chunk
(at most one input sample, <= 125 µs at 8 kHz) so it interpolates against
the true following sample instead of a clamped edge. The grid is exact:
cumulative output count matches cumulative input count deterministically
regardless of chunking, and chunked output equals whole-signal output.
"""
from __future__ import annotations

import numpy as np


class LinearStreamResampler:
    """Streaming linear-interpolation resampler for int16 little-endian mono."""

    def __init__(self, in_rate: int, out_rate: int) -> None:
        if in_rate <= 0 or out_rate <= 0:
            raise ValueError("sample rates must be positive")
        self.in_rate = int(in_rate)
        self.out_rate = int(out_rate)
        self._step = self.in_rate / self.out_rate  # input samples per output sample
        # Absolute input position of the next output sample.
        self._next_pos = 0.0
        # Absolute input index of the retained trailing sample.
        self._last_idx = -1
        self._last_value: float | None = None

    @property
    def bypassed(self) -> bool:
        """True when no conversion is needed (identical rates)."""
        return self.in_rate == self.out_rate

    def reset(self) -> None:
        """Drop all continuity state (barge-in / stream restart)."""
        self._next_pos = 0.0
        self._last_idx = -1
        self._last_value = None

    def resample(self, audio: bytes) -> bytes:
        """Resample one chunk of int16 little-endian mono bytes.

        Returns exactly ``round(len(samples_in_chunk_context) * out/in)``
        samples on the shared absolute grid, so cumulative output count
        tracks cumulative input count deterministically regardless of how
        the input is chunked.
        """
        if self.bypassed:
            return audio
        x = np.frombuffer(audio, dtype=np.int16).astype(np.float64)
        if x.size == 0:
            return b""

        if self._last_value is not None:
            buf = np.concatenate(([self._last_value], x))
            base = self._last_idx  # buf[0] IS the sample at absolute _last_idx
        else:
            buf = x
            base = 0

        # buf[i] sits at absolute input position base + i. Output positions
        # are absolute; a point past the last REAL sample (base + size - 1)
        # waits for the next chunk so it can interpolate against the true
        # following sample instead of a clamped one (<= 1 input sample,
        # <= 125 us at 8 kHz — inaudible, and it keeps the grid exact).
        last_real = base + buf.size - 1
        n_max = int(np.ceil((last_real - self._next_pos) / self._step)) + 2
        positions = self._next_pos - base + np.arange(n_max) * self._step
        keep = positions <= (last_real - base)
        positions = positions[keep]
        if positions.size == 0:
            self._last_value = float(buf[-1])
            self._last_idx = last_real
            return b""
        idx = np.floor(positions).astype(np.int64)
        frac = positions - idx
        idx_clamped = np.clip(idx, 0, buf.size - 1)
        next_clamped = np.clip(idx + 1, 0, buf.size - 1)
        out = buf[idx_clamped] * (1.0 - frac) + buf[next_clamped] * frac

        self._next_pos += positions.size * self._step
        self._last_value = float(buf[-1])
        self._last_idx = last_real
        return np.clip(out, -32768, 32767).astype(np.int16).tobytes()
