"""Which organisation a call, a trace and a catalogue belong to.

Stdlib only, and deliberately small. `voice/context.py` imports it and must
not grow a dependency on the settings layer, so nothing here reads the
environment. Everything else multi-tenancy eventually needs — credentials per
clinic, users, memberships — is still ahead of us: this module is the
identifier itself and the two rules that make it safe to use.

The two rules:

1. An org id becomes a directory name under DATA_DIR, so it is a bare slug or
   it is rejected. A trace path is built from it on every single call.
2. One organisation is the default, and a process that never mentions an
   organisation behaves exactly as it did before there were any. That is what
   keeps this change plumbing rather than a change of behaviour.
"""
from __future__ import annotations

import re
from contextvars import ContextVar, Token

# The clinic this repository was built for. Also the id the readers fall back
# to, so a console with no session still answers for the one clinic we serve.
DEFAULT_ORG_ID = "clinica-arenal"

# No dots, no slashes, nothing that can walk out of the volume.
_ORG_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")


class InvalidOrgId(ValueError):
    """An org id that may not become a path segment."""


def normalize_org_id(raw: str | None) -> str:
    """Canonical id for ``raw``; the default organisation when it is empty.

    Raises InvalidOrgId for anything non-empty that cannot be a directory
    name. Callers that take the value from a request must translate that into
    a 400 — never into a path.
    """
    value = (raw or "").strip().lower()
    if not value:
        return DEFAULT_ORG_ID
    if not _ORG_ID.fullmatch(value):
        raise InvalidOrgId(f"invalid organisation id: {raw!r}")
    return value


# ---- the organisation the current task is serving -------------------------
# A ContextVar and not a global: one process answers several calls at once and
# each socket runs in its own task, so a value set inside a call is visible to
# everything that call spawns and to nothing else.
#
# It exists for one reason: `brain/tools.py` reaches for its catalogue with
# `deps.try_catalogue_cache()` and cannot be handed an argument today. The
# voice server and the text adapter set this around the ToolBox construction,
# so the ToolBox gets its own organisation's cache without knowing this module
# exists. When tools.py can pass `self.ctx.org_id` itself, this becomes an
# unused default and can go.
_CURRENT_ORG: ContextVar[str] = ContextVar("current_org_id", default=DEFAULT_ORG_ID)


def current_org_id() -> str:
    """The organisation this task is serving; the default when nobody set one."""
    return _CURRENT_ORG.get()


def use_org(org_id: str | None) -> Token[str]:
    """Bind the current task to an organisation. Returns the reset token."""
    return _CURRENT_ORG.set(normalize_org_id(org_id))


def reset_org(token: Token[str]) -> None:
    """Undo a `use_org`. Safe to call from the same task that set it."""
    _CURRENT_ORG.reset(token)
