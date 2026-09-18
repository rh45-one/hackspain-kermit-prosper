"""Bounded ring buffer with an explicit overflow policy.

Used by the Twilio <-> Gemini converter to hold converted audio between
the producer (codec/resampler) and the consumer (Gemini session or Twilio
socket). Buffering is bounded by a fixed byte capacity sized in
milliseconds; on overflow the OLDEST audio is dropped (stale speech is
worth less than fresh speech on a phone call) and every dropped byte is
counted. Reads that find less data than requested count an underrun.
Nothing here can grow without bound.
"""
from __future__ import annotations

from collections import deque


class BoundedRingBuffer:
    """Fixed-capacity FIFO byte buffer with drop-oldest overflow policy."""

    def __init__(self, capacity_bytes: int, *, high_water_fraction: float = 0.9) -> None:
        if capacity_bytes <= 0:
            raise ValueError("capacity_bytes must be positive")
        if not 0.0 < high_water_fraction <= 1.0:
            raise ValueError("high_water_fraction must be in (0, 1]")
        self.capacity_bytes = int(capacity_bytes)
        self.high_water_bytes = int(capacity_bytes * high_water_fraction)
        self._chunks: deque[bytes] = deque()
        self._level = 0

        # Counters
        self.dropped_bytes = 0
        self.overflows = 0
        self.underruns = 0
        self.peak_level = 0

    def __len__(self) -> int:
        return self._level

    @property
    def is_high_water(self) -> bool:
        return self._level >= self.high_water_bytes

    def write(self, data: bytes) -> int:
        """Append bytes; drop the OLDEST audio when capacity is exceeded.

        Returns the number of bytes actually retained from ``data`` (0 when
        a chunk larger than the whole capacity is dropped entirely).
        """
        if not data:
            return 0
        retained = len(data)
        if retained > self.capacity_bytes:
            # A single chunk larger than the buffer: keep only its newest
            # bytes and count the rest as dropped.
            self.dropped_bytes += retained - self.capacity_bytes
            self.overflows += 1
            retained = self.capacity_bytes
            data = data[-self.capacity_bytes :]
            self._chunks.clear()
            self._level = 0
        elif self._level + retained > self.capacity_bytes:
            overflow = self._level + retained - self.capacity_bytes
            self.dropped_bytes += overflow
            self.overflows += 1
            while overflow > 0 and self._chunks:
                oldest = self._chunks[0]
                if len(oldest) <= overflow:
                    overflow -= len(oldest)
                    self._chunks.popleft()
                else:
                    self._chunks[0] = oldest[overflow:]
                    overflow = 0
        self._chunks.append(data)
        self._level = sum(len(c) for c in self._chunks)
        self.peak_level = max(self.peak_level, self._level)
        return retained

    def read(self, max_bytes: int) -> bytes:
        """Pop up to ``max_bytes`` oldest-first; count an underrun on shortfall."""
        if max_bytes <= 0:
            return b""
        if self._level < max_bytes:
            self.underruns += 1
        out = bytearray()
        while self._chunks and len(out) < max_bytes:
            need = max_bytes - len(out)
            chunk = self._chunks[0]
            if len(chunk) <= need:
                out += chunk
                self._chunks.popleft()
            else:
                out += chunk[:need]
                self._chunks[0] = chunk[need:]
        self._level = sum(len(c) for c in self._chunks)
        return bytes(out)

    def clear(self) -> None:
        """Drop everything (barge-in reset). Not counted as an overflow."""
        self._chunks.clear()
        self._level = 0
