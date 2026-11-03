"""initial schema: tenants, documents, ingestion_jobs, chunks + pgvector + RLS

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-02
"""
from __future__ import annotations

from alembic import op

from app.config import settings

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

DIM = settings.embeddings_dim
APP_ROLE = "norvia_app"
APP_PASSWORD = settings.app_db_password

TENANT_TABLES = ("documents", "ingestion_jobs", "chunks")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Restricted application role: NOSUPERUSER + NOBYPASSRLS so RLS is enforced.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}'
                    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            END IF;
        END
        $$
        """
    )

    op.execute(
        """
        CREATE TABLE tenants (
            id         VARCHAR(64) PRIMARY KEY,
            name       VARCHAR(255) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE documents (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    VARCHAR(64) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            filename     VARCHAR(512) NOT NULL,
            content_hash VARCHAR(64) NOT NULL,
            page_count   INTEGER NOT NULL DEFAULT 0,
            version      INTEGER NOT NULL DEFAULT 1,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_document_tenant_hash UNIQUE (tenant_id, content_hash)
        )
        """
    )
    op.execute("CREATE INDEX ix_documents_tenant_id ON documents (tenant_id)")

    op.execute(
        """
        CREATE TABLE ingestion_jobs (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   VARCHAR(64) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
            status      VARCHAR(16) NOT NULL DEFAULT 'pending',
            error       TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_job_status
                CHECK (status IN ('pending','processing','completed','failed'))
        )
        """
    )
    op.execute("CREATE INDEX ix_jobs_tenant_id ON ingestion_jobs (tenant_id)")
    op.execute("CREATE INDEX ix_jobs_status ON ingestion_jobs (status)")

    op.execute(
        f"""
        CREATE TABLE chunks (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   VARCHAR(64) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            content     TEXT NOT NULL,
            token_count INTEGER NOT NULL DEFAULT 0,
            embedding   vector({DIM}) NOT NULL,
            content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
            CONSTRAINT uq_chunk_doc_index UNIQUE (document_id, chunk_index)
        )
        """
    )
    op.execute("CREATE INDEX ix_chunks_tenant_id ON chunks (tenant_id)")
    op.execute("CREATE INDEX ix_chunks_document_id ON chunks (document_id)")
    op.execute(
        "CREATE INDEX ix_chunks_content_tsv ON chunks USING gin (content_tsv)"
    )
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    # Row-Level Security: fail-closed tenant isolation (D2).
    for tbl in TENANT_TABLES:
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {tbl}
                USING (tenant_id = current_setting('app.current_tenant', true))
                WITH CHECK (tenant_id = current_setting('app.current_tenant', true))
            """
        )

    # Grant the app role data-only access (no DDL, so it can't disable RLS).
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )


def downgrade() -> None:
    for tbl in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tbl}")
    op.execute("DROP TABLE IF EXISTS chunks")
    op.execute("DROP TABLE IF EXISTS ingestion_jobs")
    op.execute("DROP TABLE IF EXISTS documents")
    op.execute("DROP TABLE IF EXISTS tenants")
