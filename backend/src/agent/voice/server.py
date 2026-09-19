"""Entry point: FastAPI app serving the voice WebSocket and health checks.

Run: uv run python -m agent.voice.server   (listens on VOICE_WS_PORT)
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
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


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws")
async def voice_ws(websocket: WebSocket) -> None:
    """One phone call. Everything inside is per-connection."""
    await websocket.accept()
    ctx = CallContext(data_dir=app_settings.data_dir)
    logger.info("socket open (provisional id {})", ctx.call_id)

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
        ctx.mark_pipeline_error()
        logger.exception("pipeline error on call {}: {}", ctx.call_id, exc)
    finally:
        ctx.mark_stopped()
        ctx.audit("wire_audio_metrics", ctx.wire_audio)
        # Exactly one submission flush per call: the CallContext guard makes
        # repeat invocations (here and on early returns) no-ops.
        await flush_call(ctx, app_settings)
        logger.info("socket done: call {} (stopped={})", ctx.call_id, ctx.stopped)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=app_settings.voice_ws_host, port=app_settings.voice_ws_port, log_level="info")


if __name__ == "__main__":
    main()
