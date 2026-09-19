"""Shared fixtures for clinic and brain tests. Offline only: no network."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "clinic"


def load_fixture(name: str) -> dict[str, Any]:
    with (FIXTURES_DIR / f"{name}.json").open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(autouse=True)
def _accounts_database_is_never_the_real_one(tmp_path, monkeypatch):
    """No test reads the platform database this machine happens to hold.

    `directory` resolves routes through `store()`, which without an explicit
    config reads `DATA_DIR/platform.db`. So the moment somebody seeded the
    local clinic with a real team, seven tests asserting the declared defaults
    went red — tests that had nothing to do with the change and were only ever
    passing because the developer's laptop was empty.

    A test that depends on ambient state is not a test. Each one gets its own
    empty file; the ones that want rows put them there themselves.
    """
    from agent.accounts import directory as accounts_directory
    from agent.accounts import store as accounts_store

    empty = tmp_path / "accounts" / "platform.db"
    empty.parent.mkdir(parents=True, exist_ok=True)
    real = accounts_store.store

    def scoped(config=None):
        return real(config) if config is not None else accounts_store._store_at(str(empty))

    # `directory` binds the name at import, so patching the store module alone
    # would leave it reading the real file.
    monkeypatch.setattr(accounts_store, "store", scoped)
    monkeypatch.setattr(accounts_directory, "store", scoped)
    if hasattr(accounts_directory, "_rows") and hasattr(accounts_directory._rows, "cache_clear"):
        accounts_directory._rows.cache_clear()
    return str(empty)


@pytest.fixture
def accounts_db(_accounts_database_is_never_the_real_one) -> str:
    """The empty, migrated platform database this test owns.

    Depends on the autouse fixture above rather than building a second file:
    a test that writes rows and a `store()` that reads somewhere else is the
    confusing failure this exists to prevent.
    """
    from agent.accounts import db

    path = _accounts_database_is_never_the_real_one
    db.migrate(path)
    return path
