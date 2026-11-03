"""Root pytest config: markers and localhost DB URL defaults for integration."""

from __future__ import annotations

import os

import pytest

# Prefer localhost when tests run on the host (CI Compose publishes 5432).
# Compose service DNS (`db`) remains the default inside containers.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://norvia_app:norvia_app@localhost:5432/norvia",
)
os.environ.setdefault(
    "ADMIN_DATABASE_URL",
    "postgresql+psycopg://norvia:norvia@localhost:5432/norvia",
)
os.environ.setdefault("APP_DB_PASSWORD", "norvia_app")
os.environ.setdefault("LLM_PROVIDER", "fake")
os.environ.setdefault("EMBEDDINGS_PROVIDER", "fake")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: requires Compose Postgres + pgvector (Q1.2)",
    )
