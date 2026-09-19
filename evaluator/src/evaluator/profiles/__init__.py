"""Declarative agent profiles and the laboratory guard that polices them.

Public surface:

- `AgentProfile` and friends: the declaration schema (P0.1), with
  `from_declaration` refusing an incomplete profile and naming every gap.
- `ProfileCatalog`: the profiles this server declared, resolved by id.
- `assert_laboratory_profile` / `LaboratoryRefusal`: the refusals of P0.2 —
  port 7860, official destinations, occupied ports — each with its own message.
- `request_refusals`: the chat request allowlist, so a browser can ask for a
  profile id and nothing else.
"""
from evaluator.profiles.catalog import (
    LAB_CLINIC_URL,
    LAB_DATA_DIR,
    LAB_LAUNCH_ENV,
    LAB_OPS_PORT,
    LAB_VOICE_PORT,
    ProfileCatalog,
    cascade_profile,
    gemini_live_profile,
)
from evaluator.profiles.guard import (
    OFFICIAL_HOST_MARKERS,
    PRODUCTION_VOICE_PORT,
    LaboratoryRefusal,
    assert_laboratory_profile,
    destination_problems,
    laboratory_problems,
    port_is_free,
    port_problems,
)
from evaluator.profiles.requests import (
    FORBIDDEN_FIELD_MESSAGE,
    REQUEST_ALLOWED_FIELDS,
    REQUEST_FORBIDDEN_FIELDS,
    request_refusals,
)
from evaluator.profiles.schema import (
    AUDIO_SOURCES,
    ENGINES,
    AgentProfile,
    LaboratoryBinding,
    ProfileCapabilities,
    ProfileEndpoints,
    ProfileError,
    ProfileNotFound,
    ProfileValidationError,
    ProviderMetadata,
    looks_like_secret_value,
)

__all__ = [
    "AUDIO_SOURCES",
    "ENGINES",
    "FORBIDDEN_FIELD_MESSAGE",
    "LAB_CLINIC_URL",
    "LAB_DATA_DIR",
    "LAB_LAUNCH_ENV",
    "LAB_OPS_PORT",
    "LAB_VOICE_PORT",
    "OFFICIAL_HOST_MARKERS",
    "PRODUCTION_VOICE_PORT",
    "REQUEST_ALLOWED_FIELDS",
    "REQUEST_FORBIDDEN_FIELDS",
    "AgentProfile",
    "LaboratoryBinding",
    "LaboratoryRefusal",
    "ProfileCapabilities",
    "ProfileCatalog",
    "ProfileEndpoints",
    "ProfileError",
    "ProfileNotFound",
    "ProfileValidationError",
    "ProviderMetadata",
    "assert_laboratory_profile",
    "cascade_profile",
    "destination_problems",
    "gemini_live_profile",
    "laboratory_problems",
    "looks_like_secret_value",
    "port_is_free",
    "port_problems",
    "request_refusals",
]
