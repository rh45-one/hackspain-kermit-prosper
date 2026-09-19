"""The ops console serves whole transcripts, so it must fail closed off-host.

A caller dictates their national id and telephone number aloud during a
registration and those words sit verbatim in the call JSONL. These routes had
no check of any kind while `Dockerfile` runs `agent.serve` — which mounts them
— and `fly.toml` publishes port 8080 to the internet.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from agent.ops import console
from agent.ops.console import require_ops_access


@pytest.fixture
def ops_token(monkeypatch):
    """Set the configured token. `settings()` is lru_cached, so patch the call."""

    def _set(value: str) -> None:
        monkeypatch.setattr(console, "settings", lambda: type("S", (), {"ops_token": value})())

    return _set


class FakeRequest:
    def __init__(self, host: str = "", headers: dict | None = None, query: dict | None = None):
        self.client = type("C", (), {"host": host})() if host else None
        self.headers = headers or {}
        self.query_params = query or {}


def test_loopback_is_served_when_no_token_is_set(ops_token):
    """A laptop keeps working untouched."""
    ops_token("")
    for host in ("127.0.0.1", "::1"):
        require_ops_access(FakeRequest(host))  # must not raise


def test_the_open_internet_is_refused_when_no_token_is_set(ops_token):
    """Unset plus public is the one combination that must never quietly work."""
    ops_token("")
    with pytest.raises(HTTPException) as caught:
        require_ops_access(FakeRequest("203.0.113.7"))
    assert caught.value.status_code == 403


def test_a_client_with_no_address_is_refused(ops_token):
    ops_token("")
    with pytest.raises(HTTPException):
        require_ops_access(FakeRequest(""))


def test_the_token_opens_it_from_anywhere(ops_token):
    ops_token("s3cret")
    require_ops_access(FakeRequest("203.0.113.7", headers={"x-ops-token": "s3cret"}))
    require_ops_access(FakeRequest("203.0.113.7", query={"token": "s3cret"}))


def test_a_wrong_token_is_refused_even_on_loopback(ops_token):
    """Once a secret exists it is the only way in, from anywhere."""
    ops_token("s3cret")
    for req in (FakeRequest("127.0.0.1"), FakeRequest("127.0.0.1", headers={"x-ops-token": "no"})):
        with pytest.raises(HTTPException) as caught:
            require_ops_access(req)
        assert caught.value.status_code == 401


def test_a_forwarded_request_is_never_loopback(ops_token):
    """uvicorn rewrites client.host from X-Forwarded-For for trusted peers.

    Today the default trusts only loopback, so this is not exploitable. But
    FORWARDED_ALLOW_IPS=* is the first thing anyone sets in a container to see
    a real client address, and from that moment `X-Forwarded-For: 127.0.0.1`
    sent from the open internet would read as local and open the console with
    no token. If something is proxying for you, you are not local.
    """
    ops_token("")
    for header in ("x-forwarded-for", "forwarded", "x-real-ip"):
        with pytest.raises(HTTPException) as caught:
            require_ops_access(FakeRequest("127.0.0.1", headers={header: "203.0.113.7"}))
        assert caught.value.status_code == 403


def test_a_token_still_works_from_behind_a_proxy(ops_token):
    """The secret is the check; a proxy in front is then irrelevant."""
    ops_token("s3cret")
    require_ops_access(
        FakeRequest("10.0.0.1", headers={"x-ops-token": "s3cret", "x-forwarded-for": "203.0.113.7"})
    )
