"""Single-port production entry point.

Local development keeps two processes (``agent.voice.server`` on 7860 and the
ops console on 7861). A deployed host gives us one hostname and one port, and
the ops console must read the same ``DATA_DIR`` the voice pipeline writes, so
both have to live in one process on one machine.

Run: python -m agent.serve   (listens on $PORT, default 8080)

    wss://<host>/ws     voice WebSocket announced to the harness
    https://<host>/ops  jury console
    https://<host>/healthz
"""
from __future__ import annotations

import os

from agent.ops.console import app as ops_app
from agent.voice.server import app, app_settings

# The ops routes are all under /ops and never collide with /ws or /healthz.
app.include_router(ops_app.router)


def main() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", app_settings.voice_ws_port))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level=app_settings.log_level.lower())


if __name__ == "__main__":
    main()
