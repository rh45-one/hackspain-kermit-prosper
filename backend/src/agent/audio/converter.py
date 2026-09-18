"""Stateful, bounded Twilio <-> Gemini streaming audio converter.

Wire formats (OpenSpec D4):

- Twilio Media Streams: 8 kHz µ-law, 20 ms frames (160 µ-law bytes).
- Gemini Live input: linear PCM16 at 16 kHz.
- Gemini Live output: linear PCM16 at 24 kHz.

The converter offers both usage modes:

- **Direct chunk conversion** (``twilio_ulaw_to_gemini`` /
  ``gemini_pcm_to_twilio_ulaw`` and the PCM-only variants) for frame-level
  wiring, where the caller pushes one chunk and takes the converted bytes
  immediately. Output is available for every chunk — no delayed bursts.
- **Queued bounded mode** (``submit_*`` / ``read_*``) where converted
  audio lands in per-direction :class:`BoundedRingBuffer` s with a
  high-water mark and a drop-oldest overflow policy, for producer/consumer
  wiring whose rates differ momentarily.

Every conversion, drop and reset is counted (samples, seconds, frames,
malformed frames, drops, resets) for the per-call metrics.
"""
from __future__ import annotations

import numpy as np

from agent.audio.buffers import BoundedRingBuffer
from agent.audio.codec import MuLawCodec
from agent.audio.resampler import LinearStreamResampler

TWILIO_RATE = 8000
GEMINI_INPUT_RATE = 16000
GEMINI_OUTPUT_RATE = 24000
TWILIO_FRAME_MS = 20
BYTES_PER_TWILIO_FRAME = TWILIO_RATE * TWILIO_FRAME_MS // 1000  # 160 µ-law bytes


class TelephonyGeminiConverter:
    """Streaming Twilio µ-law <-> Gemini PCM16 converter with bounded buffers."""

    def __init__(
        self,
        *,
        buffer_ms: int = 200,
        high_water_fraction: float = 0.9,
    ) -> None:
        bytes_per_ms_in = BYTES_PER_TWILIO_FRAME / TWILIO_FRAME_MS  # µ-law: 1 B/sample
        bytes_per_ms_out = GEMINI_INPUT_RATE * 2 / 1000  # PCM16: 2 B/sample
        # Twilio -> Gemini holds Gemini-rate PCM16 awaiting the session.
        self.gemini_input = BoundedRingBuffer(
            capacity_bytes=int(buffer_ms * bytes_per_ms_out),
            high_water_fraction=high_water_fraction,
        )
        # Gemini -> Twilio holds Twilio-rate µ-law awaiting the socket.
        self.twilio_output = BoundedRingBuffer(
            capacity_bytes=int(buffer_ms * bytes_per_ms_in),
            high_water_fraction=high_water_fraction,
        )
        self._to_gemini = LinearStreamResampler(TWILIO_RATE, GEMINI_INPUT_RATE)
        self._from_gemini = LinearStreamResampler(GEMINI_OUTPUT_RATE, TWILIO_RATE)
        self._codec = MuLawCodec()

        # ---- counters (cumulative for the lifetime of the call) ----------
        self.gemini_input_samples_out = 0
        self.gemini_samples_in = 0
        self.twilio_samples_out = 0
        self.malformed_frames = 0
        self.resets = 0

    # ---- cumulative durations (seconds, float) ---------------------------
    @property
    def twilio_samples_in(self) -> int:
        """Twilio-rate input samples, derived from the Gemini grid (8k = 16k/2)."""
        return self.gemini_input_samples_out * TWILIO_RATE // GEMINI_INPUT_RATE

    @property
    def twilio_frames_in(self) -> int:
        """20 ms Twilio frames received, derived from the sample count."""
        return self.twilio_samples_in // BYTES_PER_TWILIO_FRAME

    @property
    def twilio_input_seconds(self) -> float:
        return self.twilio_samples_in / TWILIO_RATE

    @property
    def gemini_input_seconds(self) -> float:
        return self.gemini_input_samples_out / GEMINI_INPUT_RATE

    @property
    def gemini_output_seconds(self) -> float:
        return self.gemini_samples_in / GEMINI_OUTPUT_RATE

    @property
    def twilio_output_seconds(self) -> float:
        return self.twilio_samples_out / TWILIO_RATE

    def counters(self) -> dict[str, int]:
        """Flat PII-free counter snapshot for the per-call audit."""
        return {
            "gemini_input_samples": self.gemini_input_samples_out,
            "gemini_output_samples": self.gemini_samples_in,
            "twilio_output_samples": self.twilio_samples_out,
            "malformed_frames": self.malformed_frames,
            "input_dropped_bytes": self.gemini_input.dropped_bytes,
            "output_dropped_bytes": self.twilio_output.dropped_bytes,
            "output_overflows": self.twilio_output.overflows,
            "input_overflows": self.gemini_input.overflows,
            "underruns": self.twilio_output.underruns + self.gemini_input.underruns,
            "resets": self.resets,
        }

    @staticmethod
    def _even_bytes(pcm: bytes) -> bytes:
        return pcm[: len(pcm) - (len(pcm) % 2)]

    # ---- direct chunk conversion ----------------------------------------
    def twilio_pcm_to_gemini(self, pcm8k: bytes) -> bytes:
        """Resample Twilio-rate PCM16 (8 kHz) up to Gemini input rate (16 kHz)."""
        clean = self._even_bytes(pcm8k)
        if len(clean) != len(pcm8k):
            self.malformed_frames += 1
        out = self._to_gemini.resample(clean)
        self.gemini_input_samples_out += len(out) // 2
        return out

    def gemini_pcm_to_twilio(self, pcm24k: bytes) -> bytes:
        """Resample Gemini output (24 kHz) down to Twilio rate (8 kHz)."""
        clean = self._even_bytes(pcm24k)
        if len(clean) != len(pcm24k):
            self.malformed_frames += 1
        out = self._from_gemini.resample(clean)
        self.gemini_samples_in += len(clean) // 2
        self.twilio_samples_out += len(out) // 2
        return out

    def twilio_ulaw_to_gemini(self, ulaw: bytes) -> bytes:
        """Twilio 20 ms µ-law frame -> Gemini PCM16 @ 16 kHz."""
        return self.twilio_pcm_to_gemini(self._codec.decode(ulaw))

    def gemini_pcm_to_twilio_ulaw(self, pcm24k: bytes) -> bytes:
        """Gemini PCM16 @ 24 kHz -> Twilio µ-law @ 8 kHz."""
        return self._codec.encode(self.gemini_pcm_to_twilio(pcm24k))

    # ---- queued bounded mode ---------------------------------------------
    def submit_twilio_frame(self, ulaw: bytes) -> int:
        """Convert one Twilio µ-law chunk and queue it for Gemini."""
        converted = self.twilio_ulaw_to_gemini(ulaw)
        return self.gemini_input.write(converted)

    def read_gemini_input(self, max_bytes: int) -> bytes:
        """Drain converted Twilio audio for the Gemini session."""
        return self.gemini_input.read(max_bytes)

    def submit_gemini_audio(self, pcm24k: bytes) -> int:
        """Convert one Gemini PCM chunk and queue it for Twilio."""
        converted = self.gemini_pcm_to_twilio_ulaw(pcm24k)
        return self.twilio_output.write(converted)

    def read_twilio_output(self, max_bytes: int) -> bytes:
        """Drain µ-law audio for the Twilio socket."""
        return self.twilio_output.read(max_bytes)

    # ---- lifecycle --------------------------------------------------------
    def reset(self) -> None:
        """Interruption/barge-in: drop queued audio and resampler continuity.

        Cumulative counters survive the reset; only stream state is cleared.
        """
        self._to_gemini.reset()
        self._from_gemini.reset()
        self.gemini_input.clear()
        self.twilio_output.clear()
        self.resets += 1

    @property
    def is_high_water(self) -> bool:
        """True when either direction has reached its high-water mark."""
        return self.gemini_input.is_high_water or self.twilio_output.is_high_water


def ulaw_energy(ulaw: bytes) -> float:
    """RMS energy of decoded µ-law bytes (test/diagnostic helper)."""
    x = np.frombuffer(MuLawCodec().decode(ulaw), dtype=np.int16).astype(np.float64)
    if x.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(x * x)))
