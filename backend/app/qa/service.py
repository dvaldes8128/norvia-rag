"""Question-answering orchestration (R4): retrieve → prompt → LLM → validate citations."""

from __future__ import annotations

import re
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.providers.base import LLMProvider
from app.providers.factory import get_llm_provider
from app.qa.prompt import build_prompt, excerpt_for_citation
from app.retrieval.hybrid import RetrievedChunk, retrieve

_DONT_KNOW_RE = re.compile(r"i don'?t know", re.IGNORECASE)


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


def confidence_for(chunks: list[RetrievedChunk], answer: str) -> float:
    if not chunks or is_dont_know(answer):
        return 0.0
    # Top fused score is already in [0, 1] after normalisation within the candidate set.
    top = max(c.score for c in chunks)
    # Slightly discount when only one weak fragment backs the answer.
    if len(chunks) == 1:
        return round(min(1.0, top * 0.9), 3)
    return round(min(1.0, top), 3)


def citations_from_chunks(chunks: list[RetrievedChunk]) -> list[Citation]:
    """Build verifiable citations strictly from retrieved fragments (F4.3, F4.6)."""
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


def payload_from_answer(answer_text: str, chunks: list[RetrievedChunk]) -> AnswerPayload:
    """Assemble a validated answer payload from free-text + retrieved chunks."""
    text = answer_text.strip()
    if not chunks or is_dont_know(text):
        return AnswerPayload(
            answer="I don't know based on the provided documents.",
            citations=[],
            confidence=0.0,
        )
    citations = validate_citations(citations_from_chunks(chunks), chunks)
    payload = AnswerPayload(
        answer=text,
        citations=citations,
        confidence=confidence_for(chunks, text),
    )
    return AnswerPayload.model_validate(payload.model_dump())


def answer_question(
    session: Session,
    *,
    question: str,
    llm: LLMProvider | None = None,
    top_k: int | None = None,
) -> AnswerPayload:
    chunks = retrieve(session, question=question, top_k=top_k)
    prompt = build_prompt(question, chunks)
    provider = llm or get_llm_provider()
    result = provider.generate(prompt)
    return payload_from_answer(result.text, chunks)
