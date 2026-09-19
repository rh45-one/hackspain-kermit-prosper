# Backend Makefile. All targets assume cwd = backend/ (run via `make -C backend …`
# from the repository root). A relative DATA_DIR in .env resolves to backend/data.
.PHONY: sync run serve tunnel public ops test lint check-ws docker-build docker-run deploy deploy-secrets

sync:
	uv sync

run:
	@echo "Voice server starting at http://127.0.0.1:$$(grep -E '^VOICE_WS_PORT=' .env | cut -d= -f2) (Ctrl-C to stop)"
	uv run python -m agent.voice.server

tunnel:  ## use a free random URL, or ops/ngrok-domain.txt for an optional static domain
	@port=$$(grep -E '^VOICE_WS_PORT=' .env | cut -d= -f2); if ! curl --fail --silent --max-time 2 "http://127.0.0.1:$$port/healthz" >/dev/null; then echo "Voice server is not running on port $$port. Start it first with: make run" >&2; exit 1; fi; domain=$$(cat ops/ngrok-domain.txt 2>/dev/null || true); if [ -n "$$domain" ]; then ngrok http --url="$$domain" "$$port"; else ngrok http "$$port"; fi

public:  ## start the voice server if needed, then open an ngrok tunnel (Ctrl-C stops owned processes)
	@set -eu; port=$$(grep -E '^VOICE_WS_PORT=' .env | cut -d= -f2); owns_server=0; server_pid=""; if curl --fail --silent --max-time 2 "http://127.0.0.1:$$port/healthz" >/dev/null; then echo "Using existing voice server on port $$port"; else echo "Starting voice server on port $$port"; uv run python -m agent.voice.server & server_pid=$$!; owns_server=1; fi; cleanup() { if [ "$$owns_server" = 1 ]; then kill "$$server_pid" 2>/dev/null || true; fi; }; trap cleanup EXIT INT TERM; attempt=0; until curl --fail --silent --max-time 2 "http://127.0.0.1:$$port/healthz" >/dev/null; do attempt=$$((attempt + 1)); if [ "$$attempt" -eq 20 ] || ! kill -0 "$$server_pid" 2>/dev/null; then echo "Voice server did not become healthy on port $$port" >&2; exit 1; fi; sleep 1; done; domain=$$(cat ops/ngrok-domain.txt 2>/dev/null || true); if [ -n "$$domain" ]; then ngrok http --url="$$domain" "$$port"; else ngrok http "$$port"; fi

ops:
	uv run uvicorn agent.ops.console:app --port $$(grep OPS_HTTP_PORT .env | cut -d= -f2)

test:
	uv run pytest -q

lint:
	uv run ruff check src tests

check-ws:  ## smoke test the tunnel endpoint (path must match dashboard Settings)
	wscat -c "$$(grep -E '^PUBLIC_WS_URL' .env | cut -d= -f2)" -x '{"event":"connected"}'

serve:  ## single-port production shape (voice /ws + ops /ops), same as the container
	uv run python -m agent.serve

docker-build:
	docker build --platform linux/amd64 -t prosper-agent:local .

docker-run:  ## run the built image locally against backend/.env
	docker run --rm -p 8080:8080 --env-file .env -e DATA_DIR=/data -e PORT=8080 prosper-agent:local

deploy:  ## fly.io, region mad, one always-on machine
	fly deploy

deploy-secrets:  ## push every non-comment key of .env to fly as a secret
	grep -E '^[A-Z_]+=.' .env | grep -v '^PUBLIC_WS_URL' | xargs fly secrets set
