"""Fixtures for integration tests against Compose Postgres (decision #8)."""

from __future__ import annotations

import os

import pytest
from sqlalchemy.engine import Engine

from tests.integration.db import (
    admin_engine,
    database_urls,
    run_migrations,
    wait_for_postgres,
    wipe_all_data,
)


def _require_or_skip(exc: Exception) -> None:
    if os.environ.get("NORVIA_REQUIRE_DB") == "1":
        raise RuntimeError(f"Postgres required but unavailable: {exc}") from exc
    pytest.skip(f"Postgres not available ({exc}); start with: docker compose up -d db")


@pytest.fixture(scope="session")
def pg_engine() -> Engine:
    _, admin_url = database_urls()
    try:
        wait_for_postgres(admin_url)
        run_migrations()
    except Exception as exc:  # noqa: BLE001
        _require_or_skip(exc)
        raise  # pragma: no cover
    engine = admin_engine()
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_db(pg_engine: Engine) -> None:
    wipe_all_data(pg_engine)
    yield
    wipe_all_data(pg_engine)
