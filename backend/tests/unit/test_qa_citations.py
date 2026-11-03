"""Unit tests for citation validation and don't-know behaviour (Q1.1 / F4)."""

from __future__ import annotations

from uuid import uuid4

from app.qa.prompt import build_prompt
from app.qa.service import (
    Citation,
    citations_from_chunks,
    is_dont_know,
    payload_from_answer,
    validate_citations,
)
from app.retrieval.hybrid import RetrievedChunk


def _chunk(**overrides) -> RetrievedChunk:
    base = dict(
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename="policy.pdf",
        page_number=3,
        chunk_index=0,
        content="Flood damage is covered up to 50000 EUR under clause 4.2.",
        vector_score=0.8,
        text_score=0.6,
        score=0.75,
    )
    base.update(overrides)
    return RetrievedChunk(**base)


def test_citations_built_from_retrieved_chunks() -> None:
    c = _chunk()
    citations = citations_from_chunks([c])
    assert len(citations) == 1
    assert citations[0].chunk_id == c.chunk_id
    assert citations[0].page_number == 3
    assert "flood" in citations[0].excerpt.lower()


def test_validate_citations_drops_unknown_chunk_ids() -> None:
    kept = _chunk()
    foreign = Citation(
        document_id=uuid4(),
        filename="other.pdf",
        page_number=1,
        chunk_id=uuid4(),
        excerpt="not retrieved",
    )
    out = validate_citations(
        [citations_from_chunks([kept])[0], foreign],
        [kept],
    )
    assert len(out) == 1
    assert out[0].chunk_id == kept.chunk_id


def test_dont_know_yields_empty_citations_and_zero_confidence() -> None:
    payload = payload_from_answer("I don't know based on the provided documents.", [_chunk()])
    assert is_dont_know(payload.answer)
    assert payload.citations == []
    assert payload.confidence == 0.0


def test_empty_retrieval_is_dont_know() -> None:
    payload = payload_from_answer("Anything", [])
    assert payload.confidence == 0.0
    assert payload.citations == []


def test_prompt_isolates_document_context() -> None:
    prompt = build_prompt("What is covered?", [_chunk()])
    assert "<<<DOCUMENT_CONTEXT>>>" in prompt
    assert "<<<END_DOCUMENT_CONTEXT>>>" in prompt
    assert "untrusted" in prompt.lower()
    assert "Question: What is covered?" in prompt
