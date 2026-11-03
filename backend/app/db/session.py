"""Session helpers that bind the current tenant for Row-Level Security.

Tenant-scoped queries MUST go through :func:`tenant_session`, which opens a
transaction and sets ``app.current_tenant`` with ``SET LOCAL`` so every RLS policy
filters to that tenant. If the GUC is unset, policies use
``current_setting('app.current_tenant', true)`` which returns NULL -> no rows
(fail-closed).

Administrative work that must see all tenants (e.g. creating tenants) uses
:func:`admin_session`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.base import SessionLocal


@contextmanager
def tenant_session(tenant_id: str) -> Iterator[Session]:
    """Yield a Session scoped to ``tenant_id`` via RLS. Commits on success."""
    db = SessionLocal()
    try:
        # SET LOCAL is transaction-scoped; parameters can't be bound in SET,
        # so we use set_config() which is injection-safe.
        db.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": tenant_id},
        )
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def admin_session() -> Iterator[Session]:
    """Yield a Session without a tenant bound. Only for cross-tenant admin ops."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
