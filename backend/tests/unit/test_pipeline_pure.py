"""Unit tests for pipeline helpers that do not need PostgreSQL."""

from __future__ import annotations

from pathlib import Path

from app.ingestion.chunking import chunk_pages
from app.ingestion.pdf import extract_pages
from app.ingestion.pipeline import content_sha256
from app.providers.fake import FakeEmbeddings

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample_policy.pdf"


def test_content_hash_is_stable() -> None:
    assert content_sha256(FIXTURE) == content_sha256(FIXTURE)
    assert len(content_sha256(FIXTURE)) == 64


def test_fixture_pipeline_pieces_compose() -> None:
    """Extract → chunk → embed without DB; shapes must line up."""
    pages = extract_pages(FIXTURE)
    chunks = chunk_pages(pages, size_tokens=20, overlap_tokens=4)
    assert chunks
    vectors = FakeEmbeddings(dim=64).embed([c.content for c in chunks])
    assert len(vectors) == len(chunks)
    assert all(len(v) == 64 for v in vectors)
