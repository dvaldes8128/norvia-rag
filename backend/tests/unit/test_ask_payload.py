"""Unit tests for QA payload assembly with the fake LLM (no database)."""

from __future__ import annotations

from uuid import uuid4

from app.providers.fake import FakeLLM
from app.qa.prompt import build_prompt
from app.qa.service import payload_from_answer
from app.retrieval.hybrid import RetrievedChunk


def test_fake_llm_plus_payload_grounds_answer() -> None:
    chunk = RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename="policy.pdf",
        page_number=1,
        chunk_index=0,
        content="Flood damage is covered up to 50000 EUR. Theft requires a police report.",
        vector_score=0.9,
        text_score=0.7,
        score=0.85,
    )
    prompt = build_prompt("What is the flood damage limit?", [chunk])
    text = FakeLLM().generate(prompt).text
    payload = payload_from_answer(text, [chunk])
    assert "flood" in payload.answer.lower()
    assert len(payload.citations) == 1
    assert payload.citations[0].chunk_id == chunk.chunk_id
    assert payload.confidence > 0
