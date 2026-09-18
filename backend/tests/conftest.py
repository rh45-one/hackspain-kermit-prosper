"""Shared fixtures for clinic and brain tests. Offline only: no network."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "clinic"


def load_fixture(name: str) -> dict[str, Any]:
    with (FIXTURES_DIR / f"{name}.json").open(encoding="utf-8") as f:
        return json.load(f)
