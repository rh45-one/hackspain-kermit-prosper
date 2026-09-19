"""Wait for a candidate the runner started itself to actually listen.

The run loop used to fire the first cases straight after `subprocess.Popen`, so
a freshly started agent raced its own startup and those calls were attributed to
the model even though nothing was answering yet. A candidate that never comes up
is reported as `invalid_evaluation`: never scored, never silently skipped.

Nothing here decides a verdict. It decides whether a case may be scored at all.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from evaluator.models import CandidateConfig

DEFAULT_HEALTH_PATH = "/healthz"
POLL_S = 0.25


@dataclass
class Readiness:
    """Whether a started candidate answered, and how long it took."""

    ready: bool
    url: str | None
    waited_s: float
    detail: str

    def describe(self) -> str:
        target = self.url or "sin URL de sondeo"
        if self.ready:
            return f"listo en {self.waited_s:.1f}s ({target}, {self.detail})"
        return f"NO responde tras {self.waited_s:.1f}s ({target}, {self.detail})"

    def as_manifest(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "url": self.url,
            "waited_s": self.waited_s,
            "detail": self.detail,
        }


def ready_url_for(candidate: CandidateConfig) -> str | None:
    """`ws://host:port/ws` → `http://host:port/healthz`, unless given explicitly."""
    if candidate.ready_url:
        return candidate.ready_url
    if not candidate.ws_url:
        return None
    parts = urlsplit(candidate.ws_url)
    scheme = {"ws": "http", "wss": "https"}.get(parts.scheme)
    if scheme is None:
        return None
    host = parts.hostname or "127.0.0.1"
    # An implicit port stays implicit: https://host/healthz, not https://host:443/healthz.
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit((scheme, netloc, DEFAULT_HEALTH_PATH, "", ""))


async def wait_for_ready(
    url: str,
    timeout_s: float,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    poll_s: float = POLL_S,
) -> Readiness:
    """Poll `url` until it answers with anything below 500, or time out.

    A 404 is a live agent without a health route, not a dead one. A refused
    connection or a 5xx is not ready.
    """
    started = time.monotonic()
    detail = "sin respuesta"
    async with httpx.AsyncClient(timeout=2.0, transport=transport) as client:
        while True:
            try:
                response = await client.get(url)
                if response.status_code < 500:
                    return Readiness(
                        True, url, round(time.monotonic() - started, 2), f"HTTP {response.status_code}"
                    )
                detail = f"HTTP {response.status_code}"
            except httpx.HTTPError as exc:
                detail = type(exc).__name__
            waited = time.monotonic() - started
            if waited >= timeout_s:
                return Readiness(False, url, round(waited, 2), detail)
            await asyncio.sleep(poll_s)


def wait_for_candidate(candidate: CandidateConfig) -> Readiness:
    """Blocking wrapper for the run loop."""
    url = ready_url_for(candidate)
    if url is None:
        return Readiness(False, None, 0.0, "sin ws_url ni ready_url para sondear")
    return asyncio.run(wait_for_ready(url, candidate.ready_timeout_s))
