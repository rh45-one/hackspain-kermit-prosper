"""Entry point: FastAPI app serving voice WebSockets and the call simulator.

Run: uv run python -m agent.voice.server   (listens on VOICE_WS_PORT)
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport
from pipecat.workers.runner import WorkerRunner

from agent.config import Settings, settings
from agent.logging import setup_logging
from agent.voice.context import CallContext
from agent.voice.flush import flush_call
from agent.voice.pipeline import build_worker, transport_params

app_settings: Settings = settings()
setup_logging(app_settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the immutable clinic catalogue once, only with credentials: the
    # warm call is the app's single outbound request at boot, and an offline
    # host must never be pushed against the Prosper API.
    if app_settings.prosper_api_key:
        try:
            from agent.brain import deps

            client = deps.try_clinic_client(app_settings)
            cache = deps.try_catalogue_cache()
            if client and cache:
                await cache.warm(client)
                providers = len(getattr(cache, "providers_by_id", {}) or {})
                logger.info("clinic catalogue warmed: {} providers", providers)
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


async def _run_voice_socket(websocket: WebSocket, *, submit_actions: bool) -> None:
    await websocket.accept()
    ctx = CallContext(data_dir=app_settings.data_dir, submit_actions=submit_actions)
    logger.info(
        "{} socket open (provisional id {})",
        "scored" if submit_actions else "demo",
        ctx.call_id,
    )

    try:
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
        logger.info("socket done: call {} (stopped={})", ctx.call_id, ctx.stopped)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=app_settings.voice_ws_host, port=app_settings.voice_ws_port, log_level="info")


if __name__ == "__main__":
    main()
