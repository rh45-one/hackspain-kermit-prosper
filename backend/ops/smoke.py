"""Post-deploy smoke test: the three surfaces the demo depends on.

Usage: uv run --with websockets python ops/smoke.py <host>
       (host is a bare hostname, e.g. prosper-clinicreflow.fly.dev)

Exits non-zero if health, the ops console or the voice WebSocket handshake is
not reachable within the retry budget, so CI can fail the deploy.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request

HEALTH_ATTEMPTS = 30
HEALTH_INTERVAL_S = 5.0


def _schemes(host: str) -> tuple[str, str]:
    """Plain http/ws for a local container, TLS for a deployed host."""
    local = host.startswith(("localhost", "127.0.0.1", "0.0.0.0"))
    return ("http", "ws") if local else ("https", "wss")


def _get(url: str, timeout: float = 10.0, token: str = "") -> tuple[int, str]:
    request = urllib.request.Request(url)
    if token:
        request.add_header("X-Ops-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as refused:
        # A refusal is an answer here: the ops door returning 401 or 403 to a
        # request with no token is the behaviour being checked, not an error.
        return refused.code, refused.read().decode("utf-8", "replace")


def wait_healthy(host: str) -> None:
    http, _ = _schemes(host)
    last = ""
    for attempt in range(1, HEALTH_ATTEMPTS + 1):
        try:
            status, body = _get(f"{http}://{host}/healthz")
            if status == 200 and json.loads(body).get("status") == "ok":
                print(f"healthz ok after {attempt} attempt(s)")
                return
            last = f"{status} {body[:120]}"
        except (OSError, TimeoutError, json.JSONDecodeError) as exc:
            last = repr(exc)
        print(f"  attempt {attempt}/{HEALTH_ATTEMPTS}: {last}")
        time.sleep(HEALTH_INTERVAL_S)
    raise SystemExit(f"healthz never went green: {last}")


def check_ops(host: str) -> None:
    """The ops surface answers, and answers only to whoever holds the token.

    These views serve whole call transcripts, so a deployed host refuses
    everything until OPS_TOKEN is set. That makes an unauthenticated 401 or
    403 here the CORRECT answer, not a failure — and a 200 without a token
    means the door is open to the internet, which is the one outcome this
    smoke must never let through.
    """
    http, _ = _schemes(host)
    token = os.environ.get("OPS_TOKEN", "")

    status, _ = _get(f"{http}://{host}/ops")
    if not token:
        if status in (401, 403):
            print(f"ops closed to strangers ({status}) - set OPS_TOKEN to read it")
            return
        raise SystemExit(f"/ops answered {status} with no token: the door is open")
    if status not in (401, 403):
        raise SystemExit(f"/ops answered {status} without a token; it must refuse")

    status, body = _get(f"{http}://{host}/ops", token=token)
    if status != 200:
        raise SystemExit(f"/ops returned {status} with the token")
    status, body = _get(f"{http}://{host}/ops/api/calls", token=token)
    if status != 200:
        raise SystemExit(f"/ops/api/calls returned {status} with the token")
    print(f"ops ok, and shut to strangers ({len(json.loads(body))} call(s) on disk)")


async def check_ws(host: str) -> None:
    import websockets

    _, ws_scheme = _schemes(host)

    # Handshake only. Opening the socket starts a real pipeline worker, so we
    # close immediately; the server flushes it as an empty call.
    async with websockets.connect(f"{ws_scheme}://{host}/ws", open_timeout=15):
        print("ws handshake ok")


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else ""
    if not host:
        raise SystemExit("usage: smoke.py <host>")
    wait_healthy(host)
    check_ops(host)
    asyncio.run(check_ws(host))
    http, ws_scheme = _schemes(host)
    print(f"smoke passed: {ws_scheme}://{host}/ws  {http}://{host}/ops")


if __name__ == "__main__":
    main()
