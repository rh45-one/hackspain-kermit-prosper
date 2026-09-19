"""Declarative agent profiles: what the lab may talk to, and how we know.

A profile is a *declaration*, not a running process. It says which engine is
under test, which endpoints speak to it, what evidence the lab can actually
expect from it, and which environment variables hold its credentials — by
**name only**, never by value. The evaluator's environment holds the values;
nothing in this package ever carries one.

Two rules make the declaration useful rather than decorative:

- A profile that contradicts itself does not load. `AgentProfile.from_declaration`
  refuses it and names **every** field at fault in one message, so an operator
  fixes the config once instead of one error per attempt.
- `start_command` is server-owned material. It belongs to whoever wrote the
  config file on this machine; a request body can never supply it (see
  `evaluator.profiles.requests`).
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

# Engines the lab knows. `cascade` and `gemini_live` are the two real engines of
# the external agent (env `VOICE_ENGINE`); `double` is the evaluator's own test
# double and `external` is an agent driven by its owner. A name outside this list
# is a typo or a new engine nobody wired: either way the profile is refused.
ENGINES = ("cascade", "gemini_live", "external", "double")

# How the lab would obtain call audio, if it can. There is no recording writer
# in the external agent today, so a profile that claims audio must say where the
# audio comes from; claiming capture with no source is the failure mode this
# field exists to prevent.
AUDIO_SOURCES = ("none", "client_capture", "server_recording")

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")

# Values that look like credentials. Used to refuse a secret pasted into an
# environment block: the error names the variable and never repeats the value.
_SECRET_VALUE_PATTERNS = (
    re.compile(r"^(sk|pk|dg|hf|ghp|xox[abp]|AIza|eyJ)[-_A-Za-z0-9.]{8,}$"),
    re.compile(r"^[A-Za-z0-9+/]{40,}={0,2}$"),
    re.compile(r"^[0-9a-fA-F]{32,}$"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def looks_like_secret_value(value: Any) -> bool:
    """True when a string looks like a credential rather than a setting."""
    if not isinstance(value, str):
        return False
    return any(pattern.match(value.strip()) for pattern in _SECRET_VALUE_PATTERNS)


class ProfileError(ValueError):
    """Base class for profile problems that an operator has to fix."""


class ProfileValidationError(ProfileError):
    """An incomplete or contradictory declaration, with every field named."""

    def __init__(self, profile_id: str, problems: list[str]) -> None:
        self.profile_id = profile_id
        self.problems = list(problems)
        detail = "; ".join(self.problems)
        super().__init__(f"perfil '{profile_id}' inválido: {detail}")


class ProfileNotFound(ProfileError):
    """A profile id nobody declared on this server."""


class ProfileEndpoints(BaseModel):
    """Where the lab reaches the agent. Absent means the capability is absent."""

    ws_url: str | None = None  # voice WebSocket, contract ws://host/ws
    text_url: str | None = None  # base URL of the text adapter (POST {text_url}/turns)
    usage_url: str | None = None  # GET {usage_url}/calls/{call_id} -> {cost, usage}


class ProfileCapabilities(BaseModel):
    """What this agent can do, and what the lab can therefore expect to measure.

    These are claims the rest of the lab reads: they decide whether audio is
    reported as absent or as never-measured, and whether a case can be scored
    against an expected outcome at all.
    """

    text: bool = False
    voice: bool = False
    audio_capture: bool = False
    audio_source: str = "none"  # one of AUDIO_SOURCES
    transcript: bool = False
    usage_telemetry: bool = False  # cost/usage endpoint exposed by the agent
    expected_outcome: bool = False  # scenarios declare accepted outcomes for it


class ProviderMetadata(BaseModel):
    """What is behind the profile: vendor stack, docs and plain-language notes."""

    name: str = ""
    stack: list[str] = Field(default_factory=list)
    docs: str | None = None
    notes: str = ""


class LaboratoryBinding(BaseModel):
    """Server-side material the lab needs to drive this profile.

    Never rendered to a browser as a path: the console asks for a profile id and
    the server resolves these. `submit_key` is the local receiver's shared key
    (`pk-local-eval`), a fixture of this package, not a provider credential.
    """

    voice_port: int = 17860
    clinic_url: str = "http://127.0.0.1:18090"
    submit_key: str = "pk-local-eval"
    data_dir: str | None = None  # where the agent writes DATA_DIR/calls/*.jsonl
    scenario: str | None = None  # optional server-side scenario used to score a session
    agent_audit_dir: str | None = None
    tts: str = "espeak-ng"
    stt: str | None = None
    launch_hint: str = ""  # documentation for the operator; never executed here


class AgentProfile(BaseModel):
    """One declarative agent profile.

    Loading is explicit (`from_declaration`, `ProfileCatalog`): a partially
    declared profile can be inspected through `problems()` — so a config
    preflight can show every gap at once — but it cannot be loaded by accident.
    """

    id: str = ""
    engine: str = ""
    version: str = ""
    endpoints: ProfileEndpoints = Field(default_factory=ProfileEndpoints)
    capabilities: ProfileCapabilities = Field(default_factory=ProfileCapabilities)
    providers: ProviderMetadata = Field(default_factory=ProviderMetadata)
    # purpose -> ENVIRONMENT VARIABLE NAME. Never a value.
    credentials: dict[str, str] = Field(default_factory=dict)
    # Non-secret environment the operator starts the agent with (ports, flags).
    launch_env: dict[str, str] = Field(default_factory=dict)
    laboratory: LaboratoryBinding = Field(default_factory=LaboratoryBinding)
    # Server-owned: declared in the config file on this machine, refused from a
    # request body. The evaluator never builds it from browser input.
    start_command: str | None = None
    notes: str = ""

    def problems(self) -> list[str]:
        """Every missing or contradictory field, in declaration order.

        The list is the contract: an operator reads it once and knows what to
        fix. Each entry names the field (dotted, as declared) and, when the
        problem is a contradiction, both sides of it.
        """
        problems: list[str] = []
        if not self.id.strip():
            problems.append("id: falta el identificador del perfil")
        elif not _ID_PATTERN.match(self.id):
            problems.append(
                f"id: {self.id!r} no es válido (minúsculas, dígitos, '.', '-', '_')"
            )
        if not self.engine.strip():
            problems.append("engine: falta el motor")
        elif self.engine not in ENGINES:
            problems.append(
                f"engine: {self.engine!r} es desconocido (válidos: {', '.join(ENGINES)})"
            )
        if not self.version.strip():
            problems.append("version: falta la versión del perfil")
        if not self.providers.name.strip():
            problems.append("providers.name: falta el proveedor o el stack del perfil")

        caps = self.capabilities
        endpoints = self.endpoints
        if caps.voice and not endpoints.ws_url:
            problems.append("endpoints.ws_url: falta (capabilities.voice = true lo requiere)")
        if caps.text and not endpoints.text_url:
            problems.append("endpoints.text_url: falta (capabilities.text = true lo requiere)")
        if caps.usage_telemetry and not endpoints.usage_url:
            problems.append(
                "endpoints.usage_url: falta (capabilities.usage_telemetry = true lo requiere)"
            )
        if caps.transcript and not (endpoints.ws_url or endpoints.text_url):
            problems.append(
                "capabilities.transcript: declarada sin endpoints.ws_url ni endpoints.text_url"
            )
        if caps.audio_capture and caps.audio_source not in AUDIO_SOURCES:
            problems.append(
                f"capabilities.audio_source: {caps.audio_source!r} es desconocido "
                f"(válidos: {', '.join(AUDIO_SOURCES)})"
            )
        elif caps.audio_capture and caps.audio_source == "none":
            problems.append(
                "capabilities.audio_capture: declarada sin forma de obtener el audio "
                "(capabilities.audio_source = none)"
            )
        elif not caps.audio_capture and caps.audio_source != "none":
            problems.append(
                "capabilities.audio_capture: false contradice "
                f"capabilities.audio_source = {caps.audio_source!r}"
            )
        if endpoints.ws_url and not caps.voice:
            problems.append(
                "capabilities.voice: false contradice endpoints.ws_url declarado"
            )
        if endpoints.text_url and not caps.text:
            problems.append(
                "capabilities.text: false contradice endpoints.text_url declarado"
            )
        if endpoints.usage_url and not caps.usage_telemetry:
            problems.append(
                "capabilities.usage_telemetry: false contradice endpoints.usage_url declarado"
            )

        for purpose, name in sorted(self.credentials.items()):
            if not isinstance(name, str) or not _ENV_NAME_PATTERN.match(name):
                problems.append(
                    f"credentials.{purpose}: debe ser el NOMBRE de una variable de entorno "
                    "(p. ej. PROSPER_API_KEY), nunca su valor"
                )
        for key, value in sorted(self.launch_env.items()):
            if not _ENV_NAME_PATTERN.match(key or ""):
                problems.append(f"launch_env: {key!r} no es un nombre de variable de entorno")
            if looks_like_secret_value(value):
                problems.append(
                    f"launch_env.{key}: parece contener un valor de credencial; declará la "
                    "referencia en credentials y dejá el valor fuera del perfil"
                )
        return problems

    @property
    def is_complete(self) -> bool:
        return not self.problems()

    @classmethod
    def from_declaration(cls, data: dict[str, Any]) -> AgentProfile:
        """Load one profile, refusing an incomplete or contradictory one.

        Shape errors (a string where a list belongs) still raise pydantic's
        own error; semantic gaps raise `ProfileValidationError`, which names
        every offending field and never includes a credential value.
        """
        profile = cls.model_validate(data)
        problems = profile.problems()
        if problems:
            raise ProfileValidationError(profile.id or str(data.get("id") or "?"), problems)
        return profile

    def public_view(self) -> dict[str, Any]:
        """The browser-safe view: no credentials, no paths, no command.

        A screen may show which env var a profile needs and whether the lab can
        start the process; it never receives the value, the audit directory, the
        scenario path or the command line.
        """
        return {
            "id": self.id,
            "engine": self.engine,
            "version": self.version,
            "endpoints": self.endpoints.model_dump(),
            "capabilities": self.capabilities.model_dump(),
            "providers": self.providers.model_dump(),
            "credentials": sorted(set(self.credentials.values())),
            "laboratory": {
                "voice_port": self.laboratory.voice_port,
                "tts": self.laboratory.tts,
                "has_start_command": bool(self.start_command),
                "scores_scenario": bool(self.laboratory.scenario),
                "has_agent_audit_dir": bool(self.laboratory.agent_audit_dir),
            },
            "notes": self.notes,
        }
