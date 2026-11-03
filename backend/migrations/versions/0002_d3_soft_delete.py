"""D3: soft-delete columns + live-only unique indexes for versioning

Revision ID: 0002_d3_soft_delete
Revises: 0001_initial
Create Date: 2026-11-03
"""
from __future__ import annotations

from alembic import op

revision = "0002_d3_soft_delete"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE documents ADD COLUMN deleted_at TIMESTAMPTZ")
    op.execute("ALTER TABLE chunks ADD COLUMN deleted_at TIMESTAMPTZ")

    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS uq_document_tenant_hash")
    op.execute("ALTER TABLE chunks DROP CONSTRAINT IF EXISTS uq_chunk_doc_index")

    op.execute(
        """
        CREATE UNIQUE INDEX uq_document_tenant_hash_live
            ON documents (tenant_id, content_hash)
            WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_chunk_doc_index_live
            ON chunks (document_id, chunk_index)
            WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX ix_documents_tenant_filename_live
            ON documents (tenant_id, filename)
            WHERE deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_tenant_filename_live")
    op.execute("DROP INDEX IF EXISTS uq_chunk_doc_index_live")
    op.execute("DROP INDEX IF EXISTS uq_document_tenant_hash_live")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS deleted_at")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS deleted_at")
    op.execute(
        """
        ALTER TABLE documents
            ADD CONSTRAINT uq_document_tenant_hash UNIQUE (tenant_id, content_hash)
        """
    )
    op.execute(
        """
        ALTER TABLE chunks
            ADD CONSTRAINT uq_chunk_doc_index UNIQUE (document_id, chunk_index)
        """
    )
