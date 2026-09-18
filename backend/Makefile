# Backend Makefile. All targets assume cwd = backend/ (run via `make -C backend …`
# from the repository root). A relative DATA_DIR in .env resolves to backend/data.
.PHONY: sync run serve tunnel ops test lint check-ws docker-build docker-run deploy deploy-secrets

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
