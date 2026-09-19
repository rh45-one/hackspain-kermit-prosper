#!/bin/sh
# Green before every commit, and the exit code has to survive. Twice today a
# verification command ended in a pipe, the chain read the pipe's status
# instead of pytest's, and a red suite was pushed.
set -e
cd "$(dirname "$0")"
uv run pytest -q
uv run ruff check src tests
