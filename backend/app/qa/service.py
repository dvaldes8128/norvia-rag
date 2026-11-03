"""Question-answering orchestration (R4): retrieve → prompt → LLM → validate citations."""

from __future__ import annotations

import re
import time
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.config import settings
from app.core.telemetry import get_tracer
from app.providers.base import LLMProvider
from app.providers.factory import get_llm_provider
from app.qa.prompt import build_prompt, excerpt_for_citation
from app.retrieval.hybrid import RetrievedChunk, retrieve

_DONT_KNOW_RE = re.compile(r"i don'?t know", re.IGNORECASE)
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "with",
    }
)
_DONT_KNOW_ANSWER = "I don't know based on the provided documents."
_tracer = get_tracer(__name__)


class Citation(BaseModel):
    document_id: UUID
    filename: str
    page_number: int = Field(ge=1)
    chunk_id: UUID
    excerpt: str

    @field_validator("excerpt")
    @classmethod
    def excerpt_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("excerpt must be non-empty")
        return v


class AnswerPayload(BaseModel):
    answer: str
    citations: list[Citation]
    confidence: float = Field(ge=0.0, le=1.0)


def is_dont_know(text: str) -> bool:
    return bool(_DONT_KNOW_RE.search(text))


def _content_words(text: str) -> set[str]:
    return {
        m.group(0).casefold()
        for m in _WORD_RE.finditer(text)
        if m.group(0).casefold() not in _STOPWORDS
    }


def lexical_overlap(answer: str, chunk_content: str) -> tuple[int, float]:
    """Return (overlap_token_count, overlap / |answer_words|) for grounding checks."""
    answer_words = _content_words(answer)
    if not answer_words:
        return 0, 0.0
    overlap = answer_words & _content_words(chunk_content)
    return len(overlap), len(overlap) / len(answer_words)


def chunk_supports_answer(
    answer: str,
    chunk: RetrievedChunk,
    *,
    min_tokens: int | None = None,
    min_ratio: float | None = None,
) -> bool:
    min_tokens = settings.citation_min_overlap_tokens if min_tokens is None else min_tokens
    min_ratio = settings.citation_min_overlap_ratio if min_ratio is None else min_ratio
    count, ratio = lexical_overlap(answer, chunk.content)
    return count >= min_tokens or ratio >= min_ratio


def select_citation_chunks(
    chunks: list[RetrievedChunk],
    answer: str,
    *,
    citation_top_n: int = 3,
    lexical_grounding: bool = False,
) -> list[RetrievedChunk]:
    """Pick up to ``citation_top_n`` citation sources.

    * **A** (``lexical_grounding=False``): top-N by retrieval score.
    * **B** (``lexical_grounding=True``): overlap **groups** (pass/fail the
      threshold) over the full retrieval set; it does not rank. Among the
      grounded group, take top-N by retrieval score only. Empty group →
      caller should emit don't-know.
    """
    if not chunks:
        return []
    n = max(1, citation_top_n)
    if not lexical_grounding:
        return sorted(chunks, key=lambda c: c.score, reverse=True)[:n]

    grounded = [chunk for chunk in chunks if chunk_supports_answer(answer, chunk)]
    grounded.sort(key=lambda chunk: chunk.score, reverse=True)
    return grounded[:n]


def confidence_for(chunks: list[RetrievedChunk], answer: str) -> float:
    if not chunks or is_dont_know(answer):
        return 0.0
    # Top fused score among *cited* chunks (already in [0, 1] after channel norms).
    top = max(c.score for c in chunks)
    if len(chunks) == 1:
        return round(min(1.0, top * 0.9), 3)
    return round(min(1.0, top), 3)


def citations_from_chunks(chunks: list[RetrievedChunk]) -> list[Citation]:
    """Build verifiable citations strictly from selected fragments (F4.3, F4.6)."""
    return [
        Citation(
            document_id=c.document_id,
            filename=c.filename,
            page_number=c.page_number,
            chunk_id=c.chunk_id,
            excerpt=excerpt_for_citation(c.content),
        )
        for c in chunks
    ]


def validate_citations(
    citations: list[Citation],
    retrieved: list[RetrievedChunk],
) -> list[Citation]:
    """Drop any citation whose chunk_id was not in the retrieval set (F4.6)."""
    allowed = {c.chunk_id for c in retrieved}
    return [c for c in citations if c.chunk_id in allowed]


def payload_from_answer(
    answer_text: str,
    chunks: list[RetrievedChunk],
    *,
    citation_top_n: int = 3,
    lexical_grounding: bool = False,
) -> AnswerPayload:
    """Assemble a validated answer payload from free-text + retrieved chunks."""
    text = answer_text.strip()
    if not chunks or is_dont_know(text):
        return AnswerPayload(
            answer=_DONT_KNOW_ANSWER,
            citations=[],
            confidence=0.0,
        )

    selected = select_citation_chunks(
        chunks,
        text,
        citation_top_n=citation_top_n,
        lexical_grounding=lexical_grounding,
    )
    if lexical_grounding and not selected:
        return AnswerPayload(
            answer=_DONT_KNOW_ANSWER,
            citations=[],
            confidence=0.0,
        )

    citations = validate_citations(citations_from_chunks(selected), chunks)
    payload = AnswerPayload(
        answer=text,
        citations=citations,
        confidence=confidence_for(selected, text),
    )
    return AnswerPayload.model_validate(payload.model_dump())


def answer_question(
    session: Session,
    *,
    question: str,
    llm: LLMProvider | None = None,
    top_k: int | None = None,
    tenant_id: str | None = None,
    citation_top_n: int = 3,
    lexical_grounding: bool = False,
    near_copy_min_ratio: float | None = None,
) -> AnswerPayload:
    with _tracer.start_as_current_span("qa.retrieve") as span:
        if tenant_id is not None:
            span.set_attribute("tenant_id", tenant_id)
        span.set_attribute("question.len", len(question))
        span.set_attribute("citation.top_n", citation_top_n)
        span.set_attribute("citation.lexical_grounding", lexical_grounding)
        if near_copy_min_ratio is not None:
            span.set_attribute("retrieval.near_copy_min_ratio", near_copy_min_ratio)
        started = time.perf_counter()
        chunks = retrieve(
            session,
            question=question,
            top_k=top_k,
            near_copy_min_ratio=near_copy_min_ratio,
        )
        span.set_attribute("retrieval.latency_ms", round((time.perf_counter() - started) * 1000, 2))
        span.set_attribute("retrieval.chunk_count", len(chunks))

    prompt = build_prompt(question, chunks)
    provider = llm or get_llm_provider()

    with _tracer.start_as_current_span("qa.llm.generate") as span:
        if tenant_id is not None:
            span.set_attribute("tenant_id", tenant_id)
        started = time.perf_counter()
        result = provider.generate(prompt)
        span.set_attribute("llm.latency_ms", round((time.perf_counter() - started) * 1000, 2))
        span.set_attribute("llm.model", result.model)
        span.set_attribute("llm.prompt_tokens", result.prompt_tokens)
        span.set_attribute("llm.completion_tokens", result.completion_tokens)

    return payload_from_answer(
        result.text,
        chunks,
        citation_top_n=citation_top_n,
        lexical_grounding=lexical_grounding,
    )
