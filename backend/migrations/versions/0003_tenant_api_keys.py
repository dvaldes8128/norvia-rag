"""DB-backed tenant API keys for admin-created tenants

Revision ID: 0003_tenant_api_keys
Revises: 0002_d3_soft_delete
Create Date: 2026-11-03
"""

from __future__ import annotations

from alembic import op

revision = "0003_tenant_api_keys"
down_revision = "0002_d3_soft_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant_api_keys (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id  VARCHAR(64) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            key_hash   VARCHAR(64) NOT NULL,
            key_prefix VARCHAR(16) NOT NULL,
            label      VARCHAR(128) NOT NULL DEFAULT 'default',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            revoked_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_tenant_api_keys_hash_live "
        "ON tenant_api_keys (key_hash) WHERE revoked_at IS NULL"
    )
    op.execute("CREATE INDEX ix_tenant_api_keys_tenant_id ON tenant_api_keys (tenant_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_api_keys")
