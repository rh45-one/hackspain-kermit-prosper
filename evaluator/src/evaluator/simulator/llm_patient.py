"""Restricted-LLM simulated caller (plan §11, second version).

The LLM gives the rules caller a natural voice: it may paraphrase and
hold a conversation, but it is bound to the scenario's `caller.facts`
and `caller.behavior` exactly like `RulesPatient`. It NEVER receives
`oracle.accepted_outcomes`, never invents identifiers, and falls back
to the deterministic rules patient when the provider is unreachable or
misbehaves - an LLM outage must not invalidate an evaluation.

The endpoint is OpenAI-compatible (`POST /v1/chat/completions`), so any
local model (Ollama, llama.cpp, vLLM) works without paid services.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from evaluator.models import Caller, Limits
from evaluator.simulator.patient import PatientLog, RulesPatient

_SYSTEM = """\
Eres {persona} en una llamada telefónica con una clínica. Hablas en {lang}.
Responde SOLO como el paciente, en una o dos frases cortas y naturales.

REGLAS ESTRICTAS:
- Usa ÚNICAMENTE los datos de la sección DATOS. Nunca inventes nombres,
  DNIs, teléfonos, fechas ni datos médicos que no estén ahí.
- Si el agente pregunta algo para lo que no tienes dato, di que no lo
  sabes o pide que repita la pregunta.
- {behavior}
- No aceptes una propuesta solo por acabar la llamada antes.
- Si el agente se despide o confirma que ha terminado, responde con una
  despedida breve.
"""


def _behavior_text(caller: Caller) -> str:
    b = caller.behavior
    rules = []
    if not b.provide_identifier_when_asked:
        rules.append("No des tu nombre ni tu DNI aunque te lo pidan.")
    if b.reveal_second_policy_when_asked:
        rules.append("Si te preguntan por el seguro, menciona todas tus pólizas.")
    else:
        rules.append("Solo menciona una segunda póliza si te preguntan por ella.")
    if b.accept_first_offer:
        rules.append("Acepta la primera fecha u hora que te propongan.")
    else:
        rules.append("No aceptes la primera propuesta; pide alternativas.")
    for c in b.corrections:
        rules.append(f"En algún momento debes decir: «{c}».")
    return "\n- ".join(rules) if rules else "Compórtate con naturalidad."


class LLMPatient:
    """Caller driven by an LLM, constrained by facts + behaviour.

    Same interface as `RulesPatient` (`opening()`, `respond()`), plus an
    auditable `log` and a `fell_back` flag so the case result can record
    that the deterministic patient took over mid-call.
    """

    def __init__(
        self,
        caller: Caller,
        limits: Limits | None = None,
        language: str = "es",
        timeout_s: float = 10.0,
    ) -> None:
        if caller.llm is None:
            raise ValueError("LLMPatient requires caller.llm config")
        self.caller = caller
        self.llm = caller.llm
        self.limits = limits or Limits()
        self.timeout_s = timeout_s
        self.log = PatientLog()
        self.fell_back = False
        self._fallback = RulesPatient(caller, limits)
        self._history: list[dict[str, str]] = []
        self._closing = False
        facts = "\n".join(f"- {k}: {v}" for k, v in caller.facts.items() if v is not None)
        lang = {"es": "español", "en": "inglés", "ca": "catalán"}.get(language, language)
        self._system = _SYSTEM.format(
            persona=caller.persona,
            lang=lang,
            behavior=_behavior_text(caller),
        ) + f"\nDATOS:\n{facts or '(sin datos)'}\n"

    def opening(self) -> str | None:
        return self.caller.opening

    def respond(self, agent_text: str) -> str | None:
        self.log.turns_used += 1
        if self._closing or self.log.turns_used > self.limits.max_turns:
            return None
        if self.fell_back:
            return self._fallback.respond(agent_text)

        self._history.append({"role": "user", "content": agent_text})
        try:
            reply = self._chat()
        except Exception:  # noqa: BLE001 - provider failure → rules patient
            self.fell_back = True
            return self._fallback.respond(agent_text)
        self._history.append({"role": "assistant", "content": reply})
        if self._looks_like_closing(reply):
            self._closing = True
        return reply

    def _chat(self) -> str:
        headers = {"Content-Type": "application/json"}
        if self.llm.key_env and os.environ.get(self.llm.key_env):
            headers["Authorization"] = f"Bearer {os.environ[self.llm.key_env]}"
        payload: dict[str, Any] = {
            "model": self.llm.model,
            "temperature": self.llm.temperature,
            "max_tokens": self.llm.max_tokens,
            "messages": [
                {"role": "system", "content": self._system},
                *self._history[-12:],
            ],
        }
        if self.llm.seed is not None:
            payload["seed"] = self.llm.seed
        with httpx.Client(timeout=self.timeout_s) as client:
            resp = client.post(self.llm.endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()
        if not text:
            raise RuntimeError("empty LLM reply")
        return text

    @staticmethod
    def _looks_like_closing(text: str) -> bool:
        t = text.lower()
        return any(m in t for m in ("adiós", "adios", "gracias", "hasta luego", "nada más"))


def make_patient(caller: Caller, limits: Limits | None = None, language: str = "es"):
    """LLM patient when configured, rules patient otherwise."""
    if caller.llm is not None:
        return LLMPatient(caller, limits, language=language)
    return RulesPatient(caller, limits)
