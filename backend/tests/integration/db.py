"""DB helpers for integration tests: wait, migrate, admin engine."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def database_urls() -> tuple[str, str]:
    app_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://norvia_app:norvia_app@localhost:5432/norvia",
    )
    admin_url = os.environ.get(
        "ADMIN_DATABASE_URL",
        "postgresql+psycopg://norvia:norvia@localhost:5432/norvia",
    )
    return app_url, admin_url


def wait_for_postgres(admin_url: str, *, timeout_s: float = 60.0) -> None:
    engine = create_engine(admin_url, pool_pre_ping=True)
    deadline = time.time() + timeout_s
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            engine.dispose()
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(1.0)
    engine.dispose()
    raise RuntimeError(f"Postgres not reachable at {admin_url}: {last_error}")


def run_migrations() -> None:
    """Apply Alembic migrations as the admin role."""
    env = os.environ.copy()
    # Ensure alembic picks up localhost URLs when running outside Compose DNS.
    app_url, admin_url = database_urls()
    env.setdefault("DATABASE_URL", app_url)
    env.setdefault("ADMIN_DATABASE_URL", admin_url)
    env.setdefault("APP_DB_PASSWORD", os.environ.get("APP_DB_PASSWORD", "norvia_app"))
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


def admin_engine() -> Engine:
    _, admin_url = database_urls()
    return create_engine(admin_url, pool_pre_ping=True, future=True)


@contextmanager
def admin_db_session(engine: Engine | None = None) -> Iterator[Session]:
    """Session as the DB owner role (bypasses app-role restrictions).

    Note: FORCE RLS still applies to the table owner. Prefer tenant_session for
    tenant-owned rows; use this for the ``tenants`` table and DDL-adjacent ops.
    """
    owns = engine is None
    eng = engine or admin_engine()
    factory = sessionmaker(bind=eng, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        if owns:
            eng.dispose()


def wipe_all_data(engine: Engine) -> None:
    """Delete all app data. Uses the admin role; TRUNCATE ... CASCADE."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE chunks, ingestion_jobs, documents, tenant_api_keys, tenants "
                "RESTART IDENTITY CASCADE"
            )
        )
