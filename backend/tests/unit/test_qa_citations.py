"""Unit tests for citation validation and don't-know behaviour (Q1.1 / F4)."""

from __future__ import annotations

from uuid import uuid4

from app.qa.prompt import build_prompt
from app.qa.service import (
    Citation,
    citations_from_chunks,
    is_dont_know,
    payload_from_answer,
    select_citation_chunks,
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


def test_strategy_a_cites_top_n_by_score() -> None:
    low = _chunk(content="Parking circular about office hours.", score=0.2)
    high = _chunk(
        content="Flood damage is covered up to fifty thousand EUR.",
        score=0.95,
    )
    mid = _chunk(content="Theft requires a police report within 48 hours.", score=0.5)
    selected = select_citation_chunks(
        [low, high, mid],
        "Flood damage is covered up to fifty thousand EUR.",
        citation_top_n=2,
        lexical_grounding=False,
    )
    assert [c.chunk_id for c in selected] == [high.chunk_id, mid.chunk_id]

    payload = payload_from_answer(
        "Flood damage is covered up to fifty thousand EUR.",
        [low, high, mid],
        citation_top_n=2,
        lexical_grounding=False,
    )
    assert len(payload.citations) == 2
    assert payload.citations[0].chunk_id == high.chunk_id


def test_strategy_b_grounds_full_pool_then_top_n() -> None:
    # High retrieval score but no lexical overlap with the flood answer.
    parking = _chunk(
        content="Office parking permits renew every January.",
        score=0.99,
    )
    flood_low = _chunk(
        content="Flood damage is covered up to fifty thousand EUR under section A.",
        score=0.4,
    )
    flood_mid = _chunk(
        content="Section A flood limit is fifty thousand EUR for sudden surface runoff.",
        score=0.55,
    )
    answer = "Flood damage is covered up to fifty thousand EUR under section A."
    selected = select_citation_chunks(
        [parking, flood_low, flood_mid],
        answer,
        citation_top_n=2,
        lexical_grounding=True,
    )
    # Must not stop at parking (top score) and return <N; pull grounded from full set.
    assert len(selected) == 2
    assert parking.chunk_id not in {c.chunk_id for c in selected}
    assert {c.chunk_id for c in selected} == {flood_low.chunk_id, flood_mid.chunk_id}

    invented = payload_from_answer(
        "Extraterrestrial coverage is unlimited.",
        [parking, flood_low, flood_mid],
        citation_top_n=2,
        lexical_grounding=True,
    )
    assert invented.citations == []
    assert invented.confidence == 0.0
    assert is_dont_know(invented.answer)
