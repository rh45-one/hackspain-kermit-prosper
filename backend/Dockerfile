# Prosper voice agent — single container, single port.
# Serves wss://<host>/ws (harness) and https://<host>/ops (jury console).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependency layer: cached across code changes (the venv is ~400 MB, rebuilding
# it on every deploy would cost minutes we do not have during the hackathon).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Runtime call logs live on the mounted volume, never in the image layer.
ENV DATA_DIR=/data \
    PORT=8080
RUN mkdir -p /data/calls /data/reflow

EXPOSE 8080
CMD ["python", "-m", "agent.serve"]
