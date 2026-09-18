"""µ-law codec over the Python audio reference (stdlib audioop).

The Twilio wire carries 8 kHz µ-law; Gemini carries linear PCM16. Both
directions of the bridge encode/decode here, and the unit tests compare
byte-for-byte against ``audioop.ulaw2lin`` / ``audioop.lin2ulaw``, which
are the reference implementations pipecat itself uses.
"""
from __future__ import annotations

import audioop


class MuLawCodec:
    """8 kHz µ-law <-> int16 linear PCM codec (1 µ-law byte per sample)."""

    sample_rate = 8000

    def decode(self, ulaw: bytes) -> bytes:
        """Decode µ-law bytes to int16 little-endian linear PCM."""
        return audioop.ulaw2lin(ulaw, 2)

    def encode(self, pcm: bytes) -> bytes:
        """Encode int16 little-endian linear PCM to µ-law bytes."""
        return audioop.lin2ulaw(pcm, 2)
