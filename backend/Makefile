# Backend Makefile. All targets assume cwd = backend/ (run via `make -C backend …`
# from the repository root). A relative DATA_DIR in .env resolves to backend/data.
.PHONY: sync run tunnel ops test lint check-ws

sync:
	uv sync

run:
	uv run python -m agent.voice.server

tunnel:  ## requires: ngrok account + static domain claimed (EU region)
	ngrok http --url=$$(cat ops/ngrok-domain.txt 2>/dev/null || echo FAIL-claim-domain-first) --region=eu $$(grep VOICE_WS_PORT .env | cut -d= -f2)

ops:
	uv run uvicorn agent.ops.console:app --port $$(grep OPS_HTTP_PORT .env | cut -d= -f2)

test:
	uv run pytest -q

lint:
	uv run ruff check src tests

check-ws:  ## smoke test the tunnel endpoint (path must match dashboard Settings)
	wscat -c "$$(grep -E '^PUBLIC_WS_URL' .env | cut -d= -f2)" -x '{"event":"connected"}'
