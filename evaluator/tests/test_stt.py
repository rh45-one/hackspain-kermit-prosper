"""STT selection and transport, verified without network or real credentials.

Every case runs against `httpx.MockTransport`, so the suite pins the request
shape and the failure modes of both providers while never leaving the machine
and never needing a key. The suite also pins the rule that matters most: a
placeholder in a copied `.env` is not a credential, and an unusable key must
never look like a silent caller.
"""
from __future__ import annotations

import io
import wave

import httpx
import pytest

from evaluator.harness.audio import pcm_to_ulaw
from evaluator.harness.stt import (
    DeepgramTranscriber,
    NullTranscriber,
    OpenAICompatTranscriber,
    TranscriptionError,
    transcriber_from_env,
    usable_key,
)

DEEPGRAM_OK = {
    "results": {
        "channels": [{"alternatives": [{"transcript": "  Hola, ¿en qué puedo ayudarle?  "}]}]
    }
}
DEEPGRAM_SILENCE = {"results": {"channels": [{"alternatives": [{"transcript": ""}]}]}}
UTTERANCE = pcm_to_ulaw([0, 4000, -4000, 8000] * 200)


def _recorder(handler):
    """MockTransport plus the list of requests it saw."""
    requests: list[httpx.Request] = []

    def _handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return httpx.MockTransport(_handle), requests


def _wav_shape(body: bytes) -> tuple[int, int, int, int]:
    with wave.open(io.BytesIO(body), "rb") as handle:
        return (
            handle.getnchannels(),
            handle.getsampwidth(),
            handle.getframerate(),
            handle.getnframes(),
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("sk-real-key", "sk-real-key"),
        ("  sk-padded  ", "sk-padded"),
        ("sk-hke_REPLACE_ME", None),
        ("your-key-here", None),
        ("changeme", None),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_only_a_real_looking_key_counts_as_configured(value, expected):
    assert usable_key(value) == expected


async def test_auto_without_a_key_stays_audio_only():
    transcriber = transcriber_from_env({})
    assert isinstance(transcriber, NullTranscriber)
    assert "DEEPGRAM_API_KEY" in transcriber.reason
    assert await transcriber.transcribe(UTTERANCE) == ""
    await transcriber.aclose()


async def test_auto_treats_a_placeholder_as_missing():
    transcriber = transcriber_from_env({"DEEPGRAM_API_KEY": "sk-hke_REPLACE_ME"})
    assert isinstance(transcriber, NullTranscriber)
    await transcriber.aclose()


async def test_auto_selects_deepgram_when_the_key_is_real():
    transcriber = transcriber_from_env({"DEEPGRAM_API_KEY": "dg-real-key"})
    assert isinstance(transcriber, DeepgramTranscriber)
    await transcriber.aclose()


async def test_disabled_provider_is_explicit():
    transcriber = transcriber_from_env({"EVALUATOR_STT_PROVIDER": "none"})
    assert isinstance(transcriber, NullTranscriber)
    assert "disabled" in transcriber.reason
    await transcriber.aclose()


@pytest.mark.parametrize("provider", ["deepgram", "openai-compat", "helmcode"])
async def test_naming_a_provider_without_a_usable_key_raises(provider):
    with pytest.raises(TranscriptionError):
        transcriber_from_env({"EVALUATOR_STT_PROVIDER": provider}, transport=None)


async def test_unknown_provider_raises():
    with pytest.raises(TranscriptionError) as error:
        transcriber_from_env({"EVALUATOR_STT_PROVIDER": "whisper-on-prem"})
    assert "unknown EVALUATOR_STT_PROVIDER" in str(error.value)


async def test_deepgram_request_shape_and_transcript():
    transport, requests = _recorder(lambda request: httpx.Response(200, json=DEEPGRAM_OK))
    transcriber = DeepgramTranscriber("dg-real-key", transport=transport)
    try:
        text = await transcriber.transcribe(UTTERANCE)
    finally:
        await transcriber.aclose()

    assert text == "Hola, ¿en qué puedo ayudarle?"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.headers["Authorization"] == "Token dg-real-key"
    assert request.headers["Content-Type"] == "audio/wav"
    assert request.url.params["model"] == "nova-3"
    assert request.url.params["language"] == "multi"
    assert request.url.params["smart_format"] == "true"
    assert request.url.params["punctuate"] == "true"
    channels, width, rate, frames = _wav_shape(request.content)
    assert (channels, width, rate) == (1, 2, 8000)
    assert frames == len(UTTERANCE)


async def test_deepgram_language_and_model_can_be_overridden_per_call():
    transport, requests = _recorder(lambda request: httpx.Response(200, json=DEEPGRAM_OK))
    transcriber = DeepgramTranscriber("dg-real-key", model="nova-2", transport=transport)
    try:
        await transcriber.transcribe(UTTERANCE, language="es")
    finally:
        await transcriber.aclose()
    assert requests[0].url.params["model"] == "nova-2"
    assert requests[0].url.params["language"] == "es"


async def test_deepgram_empty_audio_makes_no_request():
    transport, requests = _recorder(lambda request: httpx.Response(500, text="should not run"))
    transcriber = DeepgramTranscriber("dg-real-key", transport=transport)
    try:
        assert await transcriber.transcribe(b"") == ""
    finally:
        await transcriber.aclose()
    assert requests == []


async def test_deepgram_silence_is_an_empty_transcript_not_an_error():
    transport, _ = _recorder(lambda request: httpx.Response(200, json=DEEPGRAM_SILENCE))
    transcriber = DeepgramTranscriber("dg-real-key", transport=transport)
    try:
        assert await transcriber.transcribe(UTTERANCE) == ""
    finally:
        await transcriber.aclose()


async def test_deepgram_error_names_the_status_and_never_the_key():
    transport, _ = _recorder(lambda request: httpx.Response(401, text="invalid credentials"))
    transcriber = DeepgramTranscriber("dg-real-key", transport=transport)
    try:
        with pytest.raises(TranscriptionError) as error:
            await transcriber.transcribe(UTTERANCE)
    finally:
        await transcriber.aclose()
    message = str(error.value)
    assert "deepgram 401" in message
    assert "invalid credentials" in message
    assert "dg-real-key" not in message


async def test_deepgram_rejects_a_placeholder_key_instead_of_building_a_client():
    with pytest.raises(TranscriptionError):
        DeepgramTranscriber("sk-hke_REPLACE_ME")


async def test_openai_compat_posts_multipart_and_parses_text():
    transport, requests = _recorder(
        lambda request: httpx.Response(200, json={"text": "  Buenas tardes  "})
    )
    transcriber = OpenAICompatTranscriber(
        "sk-helmcode-real", "https://api.helmcode.com/v1", transport=transport
    )
    try:
        text = await transcriber.transcribe(UTTERANCE)
    finally:
        await transcriber.aclose()

    assert text == "Buenas tardes"
    request = requests[0]
    assert request.url.path == "/v1/audio/transcriptions"
    assert request.headers["Authorization"] == "Bearer sk-helmcode-real"
    assert "multipart/form-data" in request.headers["Content-Type"]
    assert b'name="model"' in request.content
    assert b"whisper-1" in request.content
    assert b'filename="agent.wav"' in request.content


async def test_openai_compat_error_is_explicit():
    transport, _ = _recorder(lambda request: httpx.Response(404, text="no such model"))
    transcriber = OpenAICompatTranscriber(
        "sk-helmcode-real", "https://api.helmcode.com/v1", transport=transport
    )
    try:
        with pytest.raises(TranscriptionError) as error:
            await transcriber.transcribe(UTTERANCE)
    finally:
        await transcriber.aclose()
    assert "openai-compat 404" in str(error.value)


async def test_explicit_key_override_wins_over_the_project_variable():
    transport, requests = _recorder(lambda request: httpx.Response(200, json=DEEPGRAM_OK))
    transcriber = transcriber_from_env(
        {
            "EVALUATOR_STT_PROVIDER": "deepgram",
            "EVALUATOR_STT_API_KEY": "dg-dedicated",
            "DEEPGRAM_API_KEY": "dg-project",
            "EVALUATOR_STT_MODEL": "nova-2",
        },
        transport=transport,
    )
    try:
        await transcriber.transcribe(UTTERANCE)
    finally:
        await transcriber.aclose()
    assert requests[0].headers["Authorization"] == "Token dg-dedicated"
    assert requests[0].url.params["model"] == "nova-2"


async def test_helmcode_provider_reads_its_own_base_url():
    transport, requests = _recorder(lambda request: httpx.Response(200, json={"text": "hola"}))
    transcriber = transcriber_from_env(
        {
            "EVALUATOR_STT_PROVIDER": "openai-compat",
            "HELMCODE_API_KEY": "sk-hke-real",
            "HELMCODE_BASE_URL": "https://api.helmcode.com/v1",
        },
        transport=transport,
    )
    assert isinstance(transcriber, OpenAICompatTranscriber)
    try:
        assert await transcriber.transcribe(UTTERANCE) == "hola"
    finally:
        await transcriber.aclose()
    assert requests[0].url.host == "api.helmcode.com"


async def test_aclose_closes_the_underlying_client():
    transcriber = DeepgramTranscriber("dg-real-key")
    client = transcriber._client
    assert not client.is_closed
    await transcriber.aclose()
    assert client.is_closed
