"""Entry point: FastAPI app serving voice WebSockets and the call simulator.

Run: uv run python -m agent.voice.server   (listens on VOICE_WS_PORT)
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport
from pipecat.workers.runner import WorkerRunner

from agent.accounts.store import ensure_database
from agent.config import Settings, settings
from agent.logging import setup_logging
from agent.ops import turns as text_turns
from agent.orgs import reset_org, use_org
from agent.voice.context import CallContext
from agent.voice.flush import flush_call
from agent.voice.pipeline import build_worker, transport_params

app_settings: Settings = settings()
setup_logging(app_settings.log_level)

# How long a socket will wait for a cold catalogue before answering the call
# without one. Only ever paid by the first call of an organisation the
# lifespan did not warm; the clinic this process is configured for is warm
# before the first socket opens, so a scored call never waits here.
CATALOGUE_WARM_TIMEOUT_SECONDS = 5.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Users, organisations and their credentials. Migrations run here, on
    # every boot, so a deploy can never serve a schema it has not applied.
    # `ensure_database` never raises: a console feature is not allowed to be
    # the reason a scored call does not connect.
    ensure_database(app_settings)
    # Warm the immutable clinic catalogue once, only with credentials: the
    # warm call is the app's single outbound request at boot, and an offline
    # host must never be pushed against the Prosper API.
    if app_settings.prosper_api_key:
        try:
            from agent.brain import deps

            org_id = app_settings.org_id
            client = deps.try_clinic_client(app_settings, org_id)
            cache = deps.try_catalogue_cache(org_id)
            if client and cache:
                await deps.warm_shared_catalogue(client, org_id)
                providers = len(getattr(cache, "providers_by_id", {}) or {})
                logger.info("clinic catalogue warmed for {}: {} providers", org_id, providers)
            else:
                logger.warning("clinic/scheduling layers not ready - running degraded")
        except Exception as exc:  # noqa: BLE001
            logger.error("catalogue warm failed: {}", exc)
    else:
        logger.warning("PROSPER_API_KEY not set - skipping catalogue warm (offline mode)")
    yield


app = FastAPI(title="Prosper voice agent", lifespan=lifespan)
call_client_dir = Path(__file__).resolve().parents[3] / "serverwebsock"
app.mount("/call", StaticFiles(directory=call_client_dir, html=True), name="call")

# Local test surface, off unless TURNS_ADAPTER is set: the text adapter the
# evaluator bench drives (POST /turns). The process answering scored calls
# must not serve test routes, so this is a no-op there. agent.serve imports
# this same app, so it needs no wiring of its own.
text_turns.mount_if_enabled(app, app_settings)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws")
async def voice_ws(websocket: WebSocket) -> None:
    """One scored Prosper call. Everything inside is per-connection."""
    await _run_voice_socket(websocket, submit_actions=True)


@app.websocket("/ws/demo")
async def demo_voice_ws(websocket: WebSocket) -> None:
    """One browser demo call using the production pipeline without submissions."""
    await _run_voice_socket(websocket, submit_actions=False)


async def _warm_catalogue_for(org_id: str) -> None:
    """Warm an organisation's catalogue on its first call. Never raises.

    The lifespan warms the organisation this process is configured for, so on
    a scored call this sees a warmed cache and returns without any I/O. A
    second organisation has nobody to warm it at boot — its first caller does,
    once, under a timeout, because a clinic that will not answer must cost a
    call a few seconds of degraded lookups and never the call itself.
    """
    from agent.brain import deps

    try:
        await asyncio.wait_for(
            deps.ensure_catalogue_warm(app_settings, org_id),
            CATALOGUE_WARM_TIMEOUT_SECONDS,
        )
    except (TimeoutError, asyncio.CancelledError):
        logger.warning("catalogue for {} not warm in time; call runs on ids", org_id)
    except Exception as exc:  # noqa: BLE001 - never fail a call over a lookup table
        logger.error("catalogue warm for {} failed: {}", org_id, exc)


async def _run_voice_socket(websocket: WebSocket, *, submit_actions: bool) -> None:
    await websocket.accept()
    # One organisation per socket, bound to this task before anything is
    # built: the ToolBox reads it from here to pick its catalogue cache.
    org_id = app_settings.org_id
    org_token = use_org(org_id)
    ctx = CallContext(
        org_id=org_id,
        data_dir=app_settings.data_dir,
        submit_actions=submit_actions,
    )
    logger.info(
        "{} socket open for {} (provisional id {})",
        "scored" if submit_actions else "demo",
        org_id,
        ctx.call_id,
    )

    try:
        await _warm_catalogue_for(org_id)
        transport_params_ = transport_params(ctx, app_settings)
        transport = FastAPIWebsocketTransport(websocket, params=transport_params_)
        worker = build_worker(transport, ctx, app_settings)
        runner = WorkerRunner(
            handle_sigint=False,  # per-socket runners must never own signals
            handle_sigterm=False,
        )
        await runner.add_workers(worker)
        # Returns when the pipeline ends: harness disconnect, idle timeout,
        # session timeout or cancel. The harness `stop` event is captured by
        # the serializer into ctx; the socket close ends the pipeline here.
        await runner.run()
    except WebSocketDisconnect:
        logger.info("socket closed by harness: call {}", ctx.call_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("pipeline error on call {}: {}", ctx.call_id, exc)
    finally:
        ctx.mark_stopped()
        # Exactly one flush per call. Demo contexts take the audited no-submit
        # branch; scored calls retain the normal Prosper submission contract.
        await flush_call(ctx, app_settings)
        reset_org(org_token)
        logger.info("socket done: call {} (stopped={})", ctx.call_id, ctx.stopped)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=app_settings.voice_ws_host, port=app_settings.voice_ws_port, log_level="info")


if __name__ == "__main__":
    main()
