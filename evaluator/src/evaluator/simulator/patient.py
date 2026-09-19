"""Rules-based simulated caller (plan §11, first version).

The patient has an intent, facts it knows, and canned behaviour. It never
sees `accepted_outcomes`, never invents data, and never accepts a proposal
just to end the call early. What it cannot interpret, it logs - a caller
that guesses makes the agent look broken for the wrong reason.

This drives the text adapter (`POST {text_url}/turns`); the voice path
still uses scripted `turns` until a TTS side exists.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from evaluator.models import Caller, Limits
from evaluator.normalize import fold

# Agent-utterance keyword → facts key the caller can answer with.
_KEY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "name": ("nombre", "llama", "apellido", "quién", "quien"),
    "national_id": ("dni", "nie", "documento", "identific"),
    "date_of_birth": ("nacimiento", "nació", "nacio", "nacido", "nacida", "edad", "años"),
    "phone": ("teléfono", "telefono", "número", "numero", "móvil", "movil"),
    "email": ("correo", "email", "mail", "electrónico", "electronico"),
    "insurer": ("seguro", "aseguradora", "póliza", "poliza", "mutua", "compañía", "compania"),
    "policies": ("otra póliza", "otro seguro", "segunda póliza", "más seguros", "mas seguros"),
    "wants": ("desea", "necesita", "quiere", "motivo", "puedo ayudar", "en qué", "en que"),
    "appointment": ("qué cita", "que cita", "cuál cita", "cual cita", "qué día", "que dia"),
    "prefer": ("prefiere", "horario", "qué día", "cuándo", "cuando"),
    "patient_name": ("nombre del paciente", "para quién", "para quien", "de su hijo", "del paciente"),
}

_OFFER_MARKERS = (
    "le viene",
    "le va",
    "propongo",
    "puedo ofrecer",
    "hay hueco",
    "tengo disponible",
    "disponible el",
    "el lunes a las",
    "¿le parece",
    "le parece",
    "primera cita disponible",
)
_CLOSING_MARKERS = (
    "algo más",
    "algo mas",
    "puedo ayudarle en",
    "queda reservada",
    "queda anulada",
    "queda cancelada",
    "confirmo la",
    "gracias por llamar",
    "que tenga buen día",
    "ha quedado",
)

_FACT_TEMPLATES = {
    "name": "Me llamo {value}.",
    "national_id": "Mi DNI es {value}.",
    "date_of_birth": "Nací el {value}.",
    "phone": "Mi teléfono es el {value}.",
    "email": "Mi correo es {value}.",
    "insurer": "Estoy con {value}.",
    "wants": "Quiero {value}.",
    "appointment": "Es {value}.",
    "prefer": "Prefiero {value}.",
    "patient_name": "Es para {value}.",
}


@dataclass
class PatientLog:
    """What the caller could not interpret - auditable after the run."""

    missed: list[str] = field(default_factory=list)
    revealed: list[str] = field(default_factory=list)
    turns_used: int = 0


class RulesPatient:
    """Deterministic caller driven by `caller.facts` + `caller.behavior`.

    `respond()` returns the caller's next utterance, or None to hang up.
    It answers only from its facts; an unknown question yields a repeat
    request and, after `max_repeats`, a polite goodbye. A caller that
    breaks character is a harness bug, so it never improvises.
    """

    def __init__(self, caller: Caller, limits: Limits | None = None) -> None:
        self.caller = caller
        self.facts = {k: v for k, v in caller.facts.items() if v is not None}
        self.behavior = caller.behavior
        self.limits = limits or Limits()
        self.log = PatientLog()
        self._corrections = list(self.behavior.corrections)
        self._misses = 0
        self._closing = False

    def opening(self) -> str | None:
        return self.caller.opening

    def respond(self, agent_text: str) -> str | None:
        self.log.turns_used += 1
        if self._closing or self.log.turns_used > self.limits.max_turns:
            return None
        t = fold(agent_text)

        # A queued correction is said once, at the first chance - the rules
        # caller cannot detect *what* the agent got wrong, only that the
        # scenario scheduled a correction.
        if self._corrections:
            return self._corrections.pop(0)

        if any(m in t for m in _CLOSING_MARKERS):
            self._closing = True
            return "Nada más, muchas gracias."

        answer = self._answer_fact(t)
        if answer is not None:
            self._misses = 0
            return answer

        if any(m in t for m in _OFFER_MARKERS):
            self._misses = 0
            if self.behavior.accept_first_offer:
                return "Sí, perfecto, me viene bien."
            prefer = self.facts.get("prefer")
            return f"Prefiero {prefer}." if prefer else "¿No hay otra opción?"

        # Unknown input: ask for a repeat, never invent.
        self._misses += 1
        self.log.missed.append(agent_text)
        if self._misses >= self.behavior.max_repeats:
            self._closing = True
            return "Perdone, mejor llamo otro día. Gracias."
        return "Perdone, ¿puede repetirlo?"

    def _answer_fact(self, t: str) -> str | None:
        """Answer an agent question from facts, or None if not recognised."""
        if not self.behavior.provide_identifier_when_asked:
            id_keys = {"name", "national_id", "date_of_birth"}
        else:
            id_keys = set()
        for key, synonyms in _KEY_SYNONYMS.items():
            if key in id_keys or not any(s in t for s in synonyms):
                continue
            value = self.facts.get(key)
            if key == "insurer" and self._second_policy_asked(t):
                policies = self.facts.get("policies")
                if policies:
                    self.log.revealed.append("policies")
                    return f"También tengo {policies[-1]}."
            if value is None:
                continue
            if key == "insurer":
                policies = self.facts.get("policies")
                if policies and self.behavior.reveal_second_policy_when_asked:
                    self.log.revealed.append("policies")
                    return f"Tengo {policies[0]}, y también {policies[-1]}."
            self.log.revealed.append(key)
            template = _FACT_TEMPLATES.get(key, "{value}")
            return template.format(value=value)
        return None

    @staticmethod
    def _second_policy_asked(t: str) -> bool:
        return bool(re.search(r"(otra|segunda|mas|más)\s+(p[oó]liza|seguro)", t))
