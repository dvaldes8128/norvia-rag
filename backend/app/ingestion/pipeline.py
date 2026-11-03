"""Ingestion pipeline: extract → chunk → embed → idempotent upsert (F2.1–F2.5, D3)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select, update
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

ReplaceMode = str | None  # None | "replace" | "as_new"


@dataclass(frozen=True)
class IngestionResult:
    document_id: UUID
    content_hash: str
    page_count: int
    chunk_count: int
    reused: bool
    version: int
    replaced: bool = False


@dataclass(frozen=True)
class FilenameConflict:
    document_id: UUID
    filename: str
    version: int
    content_hash: str


def content_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_live_by_hash(session: Session, *, tenant_id: str, content_hash: str) -> Document | None:
    return session.scalar(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.content_hash == content_hash,
            Document.deleted_at.is_(None),
        )
    )


def find_live_by_filename(
    session: Session,
    *,
    tenant_id: str,
    filename: str,
) -> Document | None:
    """Most recently created live document with this filename (D3 conflict target)."""
    return session.scalar(
        select(Document)
        .where(
            Document.tenant_id == tenant_id,
            Document.filename == filename,
            Document.deleted_at.is_(None),
        )
        .order_by(Document.created_at.desc())
        .limit(1)
    )


def detect_filename_conflict(
    session: Session,
    *,
    tenant_id: str,
    filename: str,
    content_hash: str,
) -> FilenameConflict | None:
    """Same live filename + different bytes → operator must confirm (D3)."""
    if find_live_by_hash(session, tenant_id=tenant_id, content_hash=content_hash) is not None:
        return None
    existing = find_live_by_filename(session, tenant_id=tenant_id, filename=filename)
    if existing is None or existing.content_hash == content_hash:
        return None
    return FilenameConflict(
        document_id=existing.id,
        filename=existing.filename,
        version=existing.version,
        content_hash=existing.content_hash,
    )


def soft_delete_live_chunks(
    session: Session, *, document_id: UUID, when: datetime | None = None
) -> int:
    stamp = when or datetime.now(UTC)
    result = session.execute(
        update(Chunk)
        .where(Chunk.document_id == document_id, Chunk.deleted_at.is_(None))
        .values(deleted_at=stamp)
    )
    return int(result.rowcount or 0)


def soft_delete_document(session: Session, *, document_id: UUID) -> Document | None:
    """Soft-delete a live document and its chunks; None if missing or already deleted."""
    document = session.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        return None
    stamp = datetime.now(UTC)
    document.deleted_at = stamp
    soft_delete_live_chunks(session, document_id=document_id, when=stamp)
    session.flush()
    return document


def _active_chunk_count(session: Session, document_id: UUID) -> int:
    count = session.scalar(
        select(func.count())
        .select_from(Chunk)
        .where(Chunk.document_id == document_id, Chunk.deleted_at.is_(None))
    )
    return int(count or 0)


def ingest_file(
    session: Session,
    *,
    tenant_id: str,
    file_path: str | Path,
    filename: str,
    embeddings: EmbeddingsProvider | None = None,
    replace_mode: ReplaceMode = None,
    replace_document_id: UUID | None = None,
) -> IngestionResult:
    """Run the full ingestion pipeline inside an open tenant-scoped session.

    Idempotency (F2.5) + versioning (D3):
    * Live ``(tenant_id, content_hash)`` — same bytes → reuse, no re-embed.
    * Same live filename + different bytes — require ``replace_mode``:
      ``replace`` bumps ``version``, soft-deletes prior chunks, re-indexes;
      ``as_new`` creates a separate document leaving the previous live.
    * Partial failures soft-delete leftover live chunks for that document before insert.
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

    existing = find_live_by_hash(session, tenant_id=tenant_id, content_hash=content_hash)
    replaced = False

    if existing is not None:
        existing_count = _active_chunk_count(session, existing.id)
        if existing_count > 0:
            logger.info(
                "ingestion.idempotent_hit",
                tenant_id=tenant_id,
                document_id=str(existing.id),
                chunk_count=existing_count,
            )
            if existing.filename != filename:
                existing.filename = filename
            return IngestionResult(
                document_id=existing.id,
                content_hash=content_hash,
                page_count=existing.page_count,
                chunk_count=existing_count,
                reused=True,
                version=existing.version,
                replaced=False,
            )
        document = existing
        document.page_count = page_count
        document.filename = filename
    else:
        name_hit = find_live_by_filename(session, tenant_id=tenant_id, filename=filename)
        if name_hit is not None and name_hit.content_hash != content_hash:
            mode = (replace_mode or "").strip().lower() or None
            if mode == "replace":
                target_id = replace_document_id or name_hit.id
                document = session.get(Document, target_id)
                if (
                    document is None
                    or document.deleted_at is not None
                    or document.tenant_id != tenant_id
                    or document.filename != filename
                ):
                    raise PermanentIngestionError(
                        "replace_document_id does not match a live document with this filename"
                    )
                soft_delete_live_chunks(session, document_id=document.id)
                document.content_hash = content_hash
                document.page_count = page_count
                document.version = int(document.version) + 1
                replaced = True
                logger.info(
                    "ingestion.version_replace",
                    tenant_id=tenant_id,
                    document_id=str(document.id),
                    version=document.version,
                )
            elif mode == "as_new":
                document = Document(
                    tenant_id=tenant_id,
                    filename=filename,
                    content_hash=content_hash,
                    page_count=page_count,
                )
                session.add(document)
                session.flush()
            else:
                raise PermanentIngestionError(
                    "Filename conflict: pass confirm=replace or confirm=as_new"
                )
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

    # Soft-delete any leftover live chunks (retry-safe; D3 keeps history).
    soft_delete_live_chunks(session, document_id=document.id)
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
        version=document.version,
        replaced=replaced,
    )
    return IngestionResult(
        document_id=document.id,
        content_hash=content_hash,
        page_count=page_count,
        chunk_count=len(chunks),
        reused=False,
        version=document.version,
        replaced=replaced,
    )
