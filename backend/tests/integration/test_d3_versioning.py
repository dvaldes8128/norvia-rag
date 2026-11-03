"""D3 — filename versioning, soft-delete, retrieval filters inactive rows."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.auth import ensure_tenant
from app.db.models import Chunk, Document
from app.db.session import tenant_session
from app.ingestion.errors import PermanentIngestionError
from app.ingestion.pipeline import ingest_file, soft_delete_document
from app.providers.fake import FakeEmbeddings
from app.retrieval.hybrid import retrieve
from corpus.build_pdfs import build_all

pytestmark = pytest.mark.integration


def test_filename_replace_soft_deletes_old_chunks(pg_engine, tmp_path: Path) -> None:
    assert pg_engine is not None
    tenant_id = "acme-d3-replace"
    ensure_tenant(tenant_id, name="Acme D3")
    built = dict(build_all())
    embeddings = FakeEmbeddings()
    first_pdf = built["home_flood_policy"]
    second_pdf = built["auto_theft_policy"]
    filename = "policy.pdf"

    with tenant_session(tenant_id) as session:
        first = ingest_file(
            session,
            tenant_id=tenant_id,
            file_path=first_pdf,
            filename=filename,
            embeddings=embeddings,
        )
        assert first.version == 1
        assert first.replaced is False
        live_before = session.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.document_id == first.document_id, Chunk.deleted_at.is_(None))
        )
        assert live_before == first.chunk_count

        with pytest.raises(PermanentIngestionError, match="Filename conflict"):
            ingest_file(
                session,
                tenant_id=tenant_id,
                file_path=second_pdf,
                filename=filename,
                embeddings=embeddings,
            )

        second = ingest_file(
            session,
            tenant_id=tenant_id,
            file_path=second_pdf,
            filename=filename,
            embeddings=embeddings,
            replace_mode="replace",
            replace_document_id=first.document_id,
        )
        assert second.document_id == first.document_id
        assert second.replaced is True
        assert second.version == 2

        doc = session.get(Document, first.document_id)
        assert doc is not None
        assert doc.version == 2
        assert doc.deleted_at is None

        soft_count = session.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.document_id == first.document_id, Chunk.deleted_at.is_not(None))
        )
        live_after = session.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.document_id == first.document_id, Chunk.deleted_at.is_(None))
        )
        assert soft_count == live_before
        assert live_after == second.chunk_count

        hits = retrieve(
            session,
            question="What is the flood coverage limit under section A?",
            top_k=5,
            embeddings=embeddings,
        )
        # Old flood chunks are soft-deleted; theft policy should dominate.
        assert all(h.document_id == first.document_id for h in hits) if hits else True
        floodish = [
            h
            for h in hits
            if "flood" in h.content.lower() and "fifty thousand" in h.content.lower()
        ]
        assert floodish == []


def test_as_new_keeps_both_live(pg_engine) -> None:
    assert pg_engine is not None
    tenant_id = "acme-d3-as-new"
    ensure_tenant(tenant_id, name="Acme D3 as_new")
    built = dict(build_all())
    embeddings = FakeEmbeddings()
    filename = "shared_name.pdf"

    with tenant_session(tenant_id) as session:
        first = ingest_file(
            session,
            tenant_id=tenant_id,
            file_path=built["home_flood_policy"],
            filename=filename,
            embeddings=embeddings,
        )
        second = ingest_file(
            session,
            tenant_id=tenant_id,
            file_path=built["auto_theft_policy"],
            filename=filename,
            embeddings=embeddings,
            replace_mode="as_new",
        )
        assert second.document_id != first.document_id
        assert second.version == 1
        live_docs = session.scalars(
            select(Document).where(Document.deleted_at.is_(None))
        ).all()
        assert len(live_docs) == 2
        assert {d.filename for d in live_docs} == {filename}


def test_soft_delete_hides_from_retrieval(pg_engine) -> None:
    assert pg_engine is not None
    tenant_id = "acme-d3-delete"
    ensure_tenant(tenant_id, name="Acme D3 delete")
    built = dict(build_all())
    embeddings = FakeEmbeddings()

    with tenant_session(tenant_id) as session:
        result = ingest_file(
            session,
            tenant_id=tenant_id,
            file_path=built["home_flood_policy"],
            filename="home_flood_policy.pdf",
            embeddings=embeddings,
        )
        hits_before = retrieve(
            session,
            question="What is the flood coverage limit under section A?",
            top_k=3,
            embeddings=embeddings,
        )
        assert hits_before

        deleted = soft_delete_document(session, document_id=result.document_id)
        assert deleted is not None
        assert deleted.deleted_at is not None

        hits_after = retrieve(
            session,
            question="What is the flood coverage limit under section A?",
            top_k=3,
            embeddings=embeddings,
        )
        assert hits_after == []
