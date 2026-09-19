.PHONY: setup check lint test frontend-check smoke clinic agent frontend

setup:
	uv sync --project backend --frozen
	uv sync --project evaluator --frozen
	npm --prefix frontend ci --no-audit --no-fund

check: lint test frontend-check

lint:
	uv run --project backend ruff check backend/src backend/tests integration
	uv run --project evaluator ruff check evaluator/src evaluator/tests
	npm --prefix frontend run lint

test:
	uv run --project backend pytest -q
	uv run --project evaluator pytest -c evaluator/pyproject.toml evaluator/tests -q
	PYTHONPATH=evaluator/src uv run --project backend pytest integration -q

frontend-check:
	npm --prefix frontend run typecheck
	npm --prefix frontend run build

smoke:
	uv run --project evaluator python -m evaluator.cli run --config evaluator/experiments/smoke.yaml

clinic:
	uv run --project evaluator python -m evaluator.cli clinic --dataset evaluator/data/clinic_dataset.json --port 8090

agent:
	PROSPER_API_BASE_URL=http://127.0.0.1:8090 PROSPER_API_KEY=pk-local-eval PORT=7860 uv run --project backend python -m agent.serve

frontend:
	npm --prefix frontend run dev
