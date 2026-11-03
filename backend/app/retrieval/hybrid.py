"""Hybrid retrieval: pgvector cosine + PostgreSQL full-text, fused by weight (F3).

Runs inside a tenant-scoped session so RLS enforces isolation (F3.1). Score fusion
is a weighted sum of normalised vector similarity and ``ts_rank`` (D1).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Select, func, literal_column, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.telemetry import get_tracer
from app.db.models import Chunk, Document
from app.providers.base import EmbeddingsProvider
from app.providers.factory import get_embeddings_provider
from app.retrieval.near_copy import is_near_copy

# Generated column lives in Postgres only (see migration 0001_initial).
_CONTENT_TSV = literal_column("chunks.content_tsv")
_tracer = get_tracer(__name__)


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    filename: str
    page_number: int
    chunk_index: int
    content: str
    vector_score: float
    text_score: float
    score: float


def fuse_scores(
    vector_scores: list[float],
    text_scores: list[float],
    *,
    vector_weight: float,
    text_weight: float,
) -> list[float]:
    """Weighted fusion after min-max normalising each channel independently.

    Pure function so unit tests can assert ranking behaviour without Postgres.
    Empty channels contribute 0. If all values in a channel are equal and > 0,
    every entry gets 1.0 for that channel (avoids zeroing a useful signal).
    """
    if len(vector_scores) != len(text_scores):
        raise ValueError("vector_scores and text_scores must have the same length")

    def _norm(vals: list[float]) -> list[float]:
        if not vals:
            return []
        lo, hi = min(vals), max(vals)
        if hi - lo < 1e-12:
            return [1.0 if v > 0 else 0.0 for v in vals]
        return [(v - lo) / (hi - lo) for v in vals]

    nv = _norm(vector_scores)
    nt = _norm(text_scores)
    total_w = vector_weight + text_weight
    if total_w <= 0:
        raise ValueError("weights must sum to a positive value")
    vw, tw = vector_weight / total_w, text_weight / total_w
    return [vw * v + tw * t for v, t in zip(nv, nt, strict=True)]


def _candidate_select(question: str, query_vec: list[float]) -> Select:
    tsq = func.plainto_tsquery("english", question)
    return (
        select(
            Chunk.id,
            Chunk.document_id,
            Chunk.page_number,
            Chunk.chunk_index,
            Chunk.content,
            (1 - Chunk.embedding.cosine_distance(query_vec)).label("vector_score"),
            func.coalesce(func.ts_rank(_CONTENT_TSV, tsq), 0.0).label("text_score"),
            Document.filename,
        )
        .join(Document, Document.id == Chunk.document_id)
        # D3: soft-deleted docs/chunks must not dilute scores or back citations.
        .where(Chunk.deleted_at.is_(None), Document.deleted_at.is_(None))
    )


def retrieve(
    session: Session,
    *,
    question: str,
    top_k: int | None = None,
    embeddings: EmbeddingsProvider | None = None,
    vector_weight: float | None = None,
    text_weight: float | None = None,
    candidate_pool: int | None = None,
    near_copy_min_ratio: float | None = None,
) -> list[RetrievedChunk]:
    """Return top-k chunks for ``question`` under the current tenant session.

    After hybrid fusion, candidates must pass a near-copy fuzzy gate against the
    question (``token_set_ratio >= near_copy_min_ratio``). Ratio ``0`` disables
    the gate (default — open NL QA). Raise toward 95 for near-quote demos;
    typical questions vs policy prose often score only ~70.
    """
    k = top_k if top_k is not None else settings.retrieval_top_k
    vw = settings.hybrid_vector_weight if vector_weight is None else vector_weight
    tw = settings.hybrid_text_weight if text_weight is None else text_weight
    pool = candidate_pool if candidate_pool is not None else max(k * 4, 20)
    min_ratio = (
        settings.retrieval_near_copy_min_ratio
        if near_copy_min_ratio is None
        else near_copy_min_ratio
    )

    provider = embeddings or get_embeddings_provider()
    with _tracer.start_as_current_span("retrieval.embed_query") as span:
        span.set_attribute("embeddings.input_count", 1)
        query_vec = provider.embed([question])[0]
        span.set_attribute("embeddings.dim", len(query_vec))
    tsq = func.plainto_tsquery("english", question)
    base = _candidate_select(question, query_vec)

    vector_rows = session.execute(
        base.order_by(Chunk.embedding.cosine_distance(query_vec)).limit(pool)
    ).all()
    text_rows = session.execute(
        base.where(_CONTENT_TSV.op("@@")(tsq))
        .order_by(func.ts_rank(_CONTENT_TSV, tsq).desc())
        .limit(pool)
    ).all()

    by_id: dict[UUID, object] = {}
    for row in vector_rows:
        by_id[row.id] = row
    for row in text_rows:
        by_id[row.id] = row

    if not by_id:
        return []

    rows = list(by_id.values())
    vector_scores = [float(r.vector_score or 0.0) for r in rows]  # type: ignore[attr-defined]
    text_scores = [float(r.text_score or 0.0) for r in rows]  # type: ignore[attr-defined]
    fused = fuse_scores(vector_scores, text_scores, vector_weight=vw, text_weight=tw)

    ranked = sorted(
        zip(rows, fused, vector_scores, text_scores, strict=True),
        key=lambda item: item[1],
        reverse=True,
    )

    results: list[RetrievedChunk] = []
    for row, score, v, t in ranked:
        content = row.content  # type: ignore[attr-defined]
        if not is_near_copy(question, content, min_ratio=min_ratio):
            continue
        results.append(
            RetrievedChunk(
                chunk_id=row.id,  # type: ignore[attr-defined]
                document_id=row.document_id,  # type: ignore[attr-defined]
                filename=row.filename,  # type: ignore[attr-defined]
                page_number=row.page_number,  # type: ignore[attr-defined]
                chunk_index=row.chunk_index,  # type: ignore[attr-defined]
                content=content,
                vector_score=v,
                text_score=t,
                score=score,
            )
        )
        if len(results) >= k:
            break
    return results
