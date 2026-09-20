import json

import httpx
import pytest

from evaluator.api.judge import KEY_ENV_VARS, Judge, JudgeError, evidence


def clear_judge_key(monkeypatch):
    for name in KEY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def row():
    return {"ended": True, "transcript_events": [
        {"role": "caller", "text": "Mi DNI es 12345678Z y mi teléfono 600 123 456"},
        {"role": "agent", "text": "¿En qué puedo ayudarle?"},
    ], "actions": [{"patient_id": "sensitive-id"}], "submit_attempts": []}


def test_judge_evidence_minimizes_identifiers():
    serialized = json.dumps(evidence(row()))
    assert "12345678Z" not in serialized and "600 123 456" not in serialized
    assert "sensitive-id" not in serialized
    assert evidence(row())["transcript"][0]["index"] == 0


@pytest.mark.asyncio
async def test_judge_rejects_open_or_empty_calls(tmp_path, monkeypatch):
    clear_judge_key(monkeypatch)
    judge = Judge(tmp_path)
    with pytest.raises(JudgeError, match="abierta"):
        await judge.evaluate({"ended": False})
    with pytest.raises(JudgeError, match="transcripción"):
        await judge.evaluate({"ended": True})
    with pytest.raises(JudgeError, match="EVALUATOR_JUDGE_API_KEY"):
        await judge.evaluate(row())
    assert judge.status()["configured"] is False
    assert judge.status()["key_env"] == list(KEY_ENV_VARS)


def test_judge_key_prefers_the_neutral_name(tmp_path, monkeypatch):
    """The provider is chosen by the environment, not by the variable name."""
    monkeypatch.setenv("NAN_API_KEY", "legacy-key")
    monkeypatch.setenv("EVALUATOR_JUDGE_API_KEY", "neutral-key")
    assert Judge(tmp_path).key == "neutral-key"
    monkeypatch.delenv("EVALUATOR_JUDGE_API_KEY")
    assert Judge(tmp_path).key == "legacy-key"
    monkeypatch.setenv("EVALUATOR_JUDGE_API_KEY", "   ")
    assert Judge(tmp_path).key == "legacy-key"


@pytest.mark.asyncio
async def test_judge_cached_per_evidence_and_rubric(tmp_path, monkeypatch):
    monkeypatch.setenv("EVALUATOR_JUDGE_API_KEY", "test-key")
    responses = []
    async def post(self, url, **kwargs):
        responses.append(kwargs)
        content = {"outcome": "unknown", "quality": 3, "reason": "Falta el resultado final",
                   "evidence_indices": [1], "limitations": ["Conversación incompleta"]}
        return httpx.Response(200, request=httpx.Request("POST", url),
                              json={"choices": [{"message": {"content": json.dumps(content)}}]})
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    judge = Judge(tmp_path)
    result = await judge.evaluate(row())
    assert result["outcome"] == "unknown"
    assert await judge.evaluate(row()) == result
    assert len(responses) == 1
    changed = row()
    changed["transcript_events"].append({"role": "caller", "text": "Otra consulta"})
    assert judge.cached(changed) is None
    assert "test-key" not in json.dumps(result)


@pytest.mark.asyncio
async def test_judge_discards_invented_citations(tmp_path, monkeypatch):
    monkeypatch.setenv("EVALUATOR_JUDGE_API_KEY", "test-key")
    async def post(self, url, **kwargs):
        content = {"outcome": "pass", "quality": 5, "reason": "Correcto",
                   "evidence_indices": [100], "limitations": []}
        return httpx.Response(200, request=httpx.Request("POST", url),
                              json={"choices": [{"message": {"content": json.dumps(content)}}]})
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with pytest.raises(JudgeError, match="no existen"):
        await Judge(tmp_path).evaluate(row())
    assert not (tmp_path / "_judgments").exists()
