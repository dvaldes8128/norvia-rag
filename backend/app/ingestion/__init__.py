"""Document ingestion: PDF extract, chunking, embeddings, idempotent upsert."""

from app.ingestion.chunking import TextChunk, chunk_pages, count_tokens
from app.ingestion.errors import (
    IngestionError,
    PermanentIngestionError,
    TransientIngestionError,
)
from app.ingestion.pdf import PageText, extract_pages

__all__ = [
    "IngestionError",
    "IngestionResult",
    "PageText",
    "PermanentIngestionError",
    "TextChunk",
    "TransientIngestionError",
    "chunk_pages",
    "content_sha256",
    "count_tokens",
    "extract_pages",
    "ingest_file",
]


def __getattr__(name: str):
    # Lazy exports that pull in SQLAlchemy / providers.
    if name in {"IngestionResult", "content_sha256", "ingest_file"}:
        from app.ingestion import pipeline as _pipeline

        return getattr(_pipeline, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
