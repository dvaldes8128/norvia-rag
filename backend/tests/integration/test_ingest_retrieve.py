"""Q1.2 — ingest into real pgvector and hybrid-retrieve (Compose Postgres)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.auth import ensure_tenant
from app.db.models import Chunk, Document
from app.db.session import tenant_session
from app.ingestion.pipeline import ingest_file
from app.providers.fake import FakeEmbeddings
from app.retrieval.hybrid import retrieve
from corpus.build_pdfs import build_all

pytestmark = pytest.mark.integration


def test_ingest_is_idempotent_and_retrievable(pg_engine) -> None:
    assert pg_engine is not None
    tenant_id = "acme-ingest"
    ensure_tenant(tenant_id, name="Acme")
    built = dict(build_all())
    pdf = built["home_flood_policy"]
    embeddings = FakeEmbeddings()

    with tenant_session(tenant_id) as session:
        first = ingest_file(
            session,
            tenant_id=tenant_id,
            file_path=pdf,
            filename="home_flood_policy.pdf",
            embeddings=embeddings,
        )
        assert first.reused is False
        assert first.chunk_count > 0

        second = ingest_file(
            session,
            tenant_id=tenant_id,
            file_path=pdf,
            filename="home_flood_policy.pdf",
            embeddings=embeddings,
        )
        assert second.reused is True
        assert second.document_id == first.document_id

        chunk_count = session.scalar(select(func.count()).select_from(Chunk))
        assert chunk_count == first.chunk_count

        hits = retrieve(
            session,
            question="What is the flood coverage limit under section A?",
            top_k=3,
            embeddings=embeddings,
        )
        assert hits, "expected at least one retrieved chunk"
        assert any("flood" in h.content.lower() for h in hits)
        assert any("fifty thousand" in h.content.lower() for h in hits)
        assert all(h.document_id == first.document_id for h in hits)


def test_hybrid_retrieval_prefers_matching_document(pg_engine) -> None:
    assert pg_engine is not None
    tenant_id = "acme-hybrid"
    ensure_tenant(tenant_id, name="Acme Hybrid")
    built = dict(build_all())
    embeddings = FakeEmbeddings()

    with tenant_session(tenant_id) as session:
        for doc_id, pdf_path in built.items():
            ingest_file(
                session,
                tenant_id=tenant_id,
                file_path=pdf_path,
                filename=f"{doc_id}.pdf",
                embeddings=embeddings,
            )

        docs = {str(d.id): d.filename for d in session.scalars(select(Document)).all()}
        assert len(docs) == len(built)

        hits = retrieve(
            session,
            question="What waiting period applies to elective orthopaedic surgery?",
            top_k=3,
            embeddings=embeddings,
        )
        assert hits
        top_name = hits[0].filename
        assert "health_waiting" in top_name
