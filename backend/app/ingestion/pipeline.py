"""Ingestion pipeline: extract → chunk → embed → idempotent upsert (F2.1–F2.5)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.logging import get_logger
from app.core.telemetry import get_tracer
from app.db.models import Chunk, Document
from app.ingestion.chunking import chunk_pages
from app.ingestion.errors import PermanentIngestionError, TransientIngestionError
from app.ingestion.pdf import extract_pages
from app.providers.base import EmbeddingsProvider, ProviderError
from app.providers.factory import get_embeddings_provider

logger = get_logger(__name__)
_tracer = get_tracer(__name__)


@dataclass(frozen=True)
class IngestionResult:
    document_id: UUID
    content_hash: str
    page_count: int
    chunk_count: int
    reused: bool


def content_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ingest_file(
    session: Session,
    *,
    tenant_id: str,
    file_path: str | Path,
    filename: str,
    embeddings: EmbeddingsProvider | None = None,
) -> IngestionResult:
    """Run the full ingestion pipeline inside an open tenant-scoped session.

    Idempotency (F2.5):
    * ``UNIQUE(tenant_id, content_hash)`` — same bytes → same document.
    * If that document already has chunks, return it without re-embedding.
    * If the document exists but has zero chunks (partial prior failure), re-index.
    """
    path = Path(file_path)
    if not path.is_file():
        raise PermanentIngestionError(f"Upload file not found: {path}")

    content_hash = content_sha256(path)
    pages = extract_pages(path)
    page_count = len(pages)

    chunks = chunk_pages(
        pages,
        size_tokens=settings.chunk_size_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
    )
    if not chunks:
        raise PermanentIngestionError("No chunks produced from PDF text")

    existing = session.scalar(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.content_hash == content_hash,
        )
    )

    if existing is not None:
        existing_count = session.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.document_id == existing.id)
        )
        if existing_count and existing_count > 0:
            logger.info(
                "ingestion.idempotent_hit",
                tenant_id=tenant_id,
                document_id=str(existing.id),
                chunk_count=existing_count,
            )
            # Refresh filename if the same bytes were uploaded under another name.
            if existing.filename != filename:
                existing.filename = filename
            return IngestionResult(
                document_id=existing.id,
                content_hash=content_hash,
                page_count=existing.page_count,
                chunk_count=int(existing_count),
                reused=True,
            )
        document = existing
        document.page_count = page_count
        document.filename = filename
    else:
        document = Document(
            tenant_id=tenant_id,
            filename=filename,
            content_hash=content_hash,
            page_count=page_count,
        )
        session.add(document)
        session.flush()

    provider = embeddings or get_embeddings_provider()
    try:
        with _tracer.start_as_current_span("ingestion.embed_chunks") as span:
            span.set_attribute("tenant_id", tenant_id)
            span.set_attribute("embeddings.input_count", len(chunks))
            vectors = provider.embed([c.content for c in chunks])
    except ProviderError as exc:
        raise TransientIngestionError(f"Embeddings provider failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise TransientIngestionError(f"Embeddings provider failed: {exc}") from exc

    if len(vectors) != len(chunks):
        raise TransientIngestionError(
            f"Embeddings count mismatch: got {len(vectors)}, expected {len(chunks)}"
        )

    # Replace any partial chunk set for this document (retry-safe).
    session.execute(delete(Chunk).where(Chunk.document_id == document.id))
    session.flush()

    for text_chunk, vector in zip(chunks, vectors, strict=True):
        session.add(
            Chunk(
                tenant_id=tenant_id,
                document_id=document.id,
                page_number=text_chunk.page_number,
                chunk_index=text_chunk.chunk_index,
                content=text_chunk.content,
                token_count=text_chunk.token_count,
                embedding=vector,
            )
        )
    session.flush()

    logger.info(
        "ingestion.completed",
        tenant_id=tenant_id,
        document_id=str(document.id),
        page_count=page_count,
        chunk_count=len(chunks),
    )
    return IngestionResult(
        document_id=document.id,
        content_hash=content_hash,
        page_count=page_count,
        chunk_count=len(chunks),
        reused=False,
    )
