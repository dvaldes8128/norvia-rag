"""Q1.3 — a tenant must not retrieve another tenant's data (RLS)."""

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


def test_rls_hides_other_tenant_chunks(pg_engine) -> None:
    assert pg_engine is not None
    built = dict(build_all())
    flood_pdf = built["home_flood_policy"]
    theft_pdf = built["auto_theft_policy"]

    ensure_tenant("tenant-a", name="Tenant A")
    ensure_tenant("tenant-b", name="Tenant B")

    with tenant_session("tenant-a") as session:
        ingest_file(
            session,
            tenant_id="tenant-a",
            file_path=flood_pdf,
            filename="home_flood_policy.pdf",
            embeddings=FakeEmbeddings(),
        )

    with tenant_session("tenant-b") as session:
        ingest_file(
            session,
            tenant_id="tenant-b",
            file_path=theft_pdf,
            filename="auto_theft_policy.pdf",
            embeddings=FakeEmbeddings(),
        )

    with tenant_session("tenant-a") as session:
        count = session.scalar(select(func.count()).select_from(Chunk))
        assert count and count > 0
        docs = list(session.scalars(select(Document)).all())
        assert len(docs) == 1
        assert docs[0].filename == "home_flood_policy.pdf"

        # Even when asking about theft (tenant-b content), retrieval stays inside A.
        hits = retrieve(
            session,
            question="What excess applies to vehicle theft indemnification?",
            top_k=5,
            embeddings=FakeEmbeddings(),
        )
        assert all("theft" not in h.filename.lower() for h in hits)
        assert all(h.filename == "home_flood_policy.pdf" for h in hits) if hits else True

    with tenant_session("tenant-b") as session:
        docs = list(session.scalars(select(Document)).all())
        assert len(docs) == 1
        assert docs[0].filename == "auto_theft_policy.pdf"
        flood_hits = retrieve(
            session,
            question="What is the flood coverage limit under section A?",
            top_k=5,
            embeddings=FakeEmbeddings(),
        )
        assert all("flood" not in h.filename.lower() for h in flood_hits)


def test_unset_tenant_guc_is_fail_closed(pg_engine) -> None:
    """Without set_config, FORCE RLS yields zero rows for the app role."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from tests.integration.db import database_urls

    assert pg_engine is not None
    ensure_tenant("solo", name="Solo")
    built = dict(build_all())
    with tenant_session("solo") as session:
        ingest_file(
            session,
            tenant_id="solo",
            file_path=built["claims_procedure_notice"],
            filename="claims_procedure_notice.pdf",
            embeddings=FakeEmbeddings(),
        )

    app_url, _ = database_urls()
    engine = create_engine(app_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, future=True)
    db = Session()
    try:
        # No set_config → policies compare tenant_id to NULL → no rows.
        n = db.execute(text("SELECT count(*) FROM chunks")).scalar_one()
        assert n == 0
        n_docs = db.execute(text("SELECT count(*) FROM documents")).scalar_one()
        assert n_docs == 0
    finally:
        db.close()
        engine.dispose()
