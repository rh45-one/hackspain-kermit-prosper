"""Agent speech → text for the manual tester (design D10 voice branch).

The tester drives the caller side with local TTS; reading the agent's replies
back as text needs a speech-to-text pass over the audio the agent sent. The
agent speaks 8 kHz µ-law, so `ulaw_to_wav` builds exactly the payload the
pre-recorded endpoints expect: no local model, no new dependency.

Which provider is used is decided by environment only, from this package's own
namespace (`EVALUATOR_STT_*`) with the project's provider keys as fallback.
Nothing here reads `backend/.env`, so the evaluator stays independent of the
agent's checkout.

Two rules that matter more than the transport:

- `auto` never guesses a credential: a placeholder (`...REPLACE_ME`) is not a
  key, and `none` keeps the tester audio-only instead of failing.
- A configured provider that answers with an error raises. An empty
  transcript and an unusable key must never look the same.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

import httpx

from evaluator.harness.audio import ulaw_to_wav

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
OPENAI_COMPAT_MODEL = "whisper-1"

# Non-empty is not the same as configured: these markers mean "not filled in".
_PLACEHOLDER_MARKERS = ("replace", "your_", "your-", "changeme", "example", "xxx")


class TranscriptionError(RuntimeError):
    """The provider was chosen, configured and still could not transcribe."""


def usable_key(value: str | None) -> str | None:
    """Return the key when it looks real, otherwise None.

    A copied `.env` ships `sk-hke_REPLACE_ME`; treating that as a credential
    turns a 401 into a mysterious empty transcript.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    lowered = stripped.lower()
    if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        return None
    return stripped


@runtime_checkable
class Transcriber(Protocol):
    """Turns one utterance of agent audio into text."""

    name: str

    async def transcribe(self, ulaw: bytes, language: str | None = None) -> str: ...

    async def aclose(self) -> None: ...


class NullTranscriber:
    """Audio-only mode: the tester prints agent audio and saves it as WAV."""

    name = "none"

    def __init__(self, reason: str = "no STT provider configured") -> None:
        self.reason = reason

    async def transcribe(self, ulaw: bytes, language: str | None = None) -> str:
        return ""

    async def aclose(self) -> None:
        return None


class DeepgramTranscriber:
    """Deepgram pre-recorded API over the agent's own 8 kHz µ-law audio.

    The WAV container carries the format, so the request needs no `encoding`
    or `sample_rate` parameters and stays valid whatever the agent sends.
    """

    name = "deepgram"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "nova-3",
        language: str = "multi",
        base_url: str = DEEPGRAM_URL,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not usable_key(api_key):
            raise TranscriptionError("deepgram needs a real API key, not a placeholder")
        self.model = model
        self.language = language
        self.base_url = base_url
        self._client = httpx.AsyncClient(
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Token {api_key.strip()}"},
        )

    async def transcribe(self, ulaw: bytes, language: str | None = None) -> str:
        if not ulaw:
            return ""
        response = await self._client.post(
            self.base_url,
            params={
                "model": self.model,
                "language": language or self.language,
                "smart_format": "true",
                "punctuate": "true",
            },
            content=ulaw_to_wav(ulaw),
            headers={"Content-Type": "audio/wav"},
        )
        if response.status_code != 200:
            raise TranscriptionError(
                f"deepgram {response.status_code}: {response.text[:200]}"
            )
        return _deepgram_transcript(response.json())

    async def aclose(self) -> None:
        await self._client.aclose()


class OpenAICompatTranscriber:
    """Any OpenAI-compatible `/audio/transcriptions` host (Helmcode whisper).

    Kept next to the Deepgram client on purpose: the design names a Helmcode
    `whisper` transcription fallback, and a fallback that needs a code change
    is not a fallback.
    """

    name = "openai-compat"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        *,
        model: str = OPENAI_COMPAT_MODEL,
        language: str = "es",
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not usable_key(api_key):
            raise TranscriptionError("openai-compat needs a real API key, not a placeholder")
        if not base_url:
            raise TranscriptionError("openai-compat needs a base URL")
        self.model = model
        self.language = language
        self.url = f"{base_url.rstrip('/')}/audio/transcriptions"
        self._client = httpx.AsyncClient(
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key.strip()}"},
        )

    async def transcribe(self, ulaw: bytes, language: str | None = None) -> str:
        if not ulaw:
            return ""
        response = await self._client.post(
            self.url,
            data={"model": self.model, "language": language or self.language},
            files={"file": ("agent.wav", ulaw_to_wav(ulaw), "audio/wav")},
        )
        if response.status_code != 200:
            raise TranscriptionError(
                f"{self.name} {response.status_code}: {response.text[:200]}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            return ""
        return str(payload.get("text", "")).strip()

    async def aclose(self) -> None:
        await self._client.aclose()


def _deepgram_transcript(payload: Any) -> str:
    """First alternative of the first channel; empty audio is not an error."""
    try:
        alternatives = payload["results"]["channels"][0]["alternatives"]
        text = alternatives[0]["transcript"]
    except (KeyError, IndexError, TypeError):
        return ""
    return str(text).strip()


def transcriber_from_env(
    env: Mapping[str, str] | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Transcriber:
    """Build the configured transcriber, or explain why the tester is audio-only.

    `EVALUATOR_STT_PROVIDER` is `auto` (default), `none`, `deepgram` or
    `openai-compat`. `auto` picks Deepgram only when a usable key is present;
    naming a provider explicitly without a usable key raises.
    """
    source = os.environ if env is None else env
    provider = source.get("EVALUATOR_STT_PROVIDER", "auto").strip().lower()
    model = source.get("EVALUATOR_STT_MODEL")
    language = source.get("EVALUATOR_STT_LANGUAGE")
    override = usable_key(source.get("EVALUATOR_STT_API_KEY"))

    if provider in ("", "none", "off"):
        return NullTranscriber("STT disabled by EVALUATOR_STT_PROVIDER")

    if provider == "auto":
        deepgram_key = override or usable_key(source.get("DEEPGRAM_API_KEY"))
        if deepgram_key:
            return DeepgramTranscriber(
                deepgram_key,
                model=model or "nova-3",
                language=language or "multi",
                transport=transport,
            )
        return NullTranscriber(
            "no usable DEEPGRAM_API_KEY; set EVALUATOR_STT_PROVIDER to choose a provider"
        )

    if provider == "deepgram":
        key = override or usable_key(source.get("DEEPGRAM_API_KEY"))
        if not key:
            raise TranscriptionError(
                "EVALUATOR_STT_PROVIDER=deepgram needs EVALUATOR_STT_API_KEY "
                "or a real DEEPGRAM_API_KEY"
            )
        return DeepgramTranscriber(
            key,
            model=model or "nova-3",
            language=language or "multi",
            transport=transport,
        )

    if provider in ("openai-compat", "helmcode"):
        key = override or usable_key(source.get("HELMCODE_API_KEY"))
        base_url = source.get("EVALUATOR_STT_BASE_URL") or source.get("HELMCODE_BASE_URL", "")
        if not key:
            raise TranscriptionError(
                "EVALUATOR_STT_PROVIDER=openai-compat needs EVALUATOR_STT_API_KEY "
                "or a real HELMCODE_API_KEY"
            )
        return OpenAICompatTranscriber(
            key,
            base_url,
            model=model or OPENAI_COMPAT_MODEL,
            language=language or "es",
            transport=transport,
        )

    raise TranscriptionError(f"unknown EVALUATOR_STT_PROVIDER: {provider!r}")
