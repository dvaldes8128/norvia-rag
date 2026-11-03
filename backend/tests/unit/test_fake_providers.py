"""Unit tests for the deterministic fake providers (no DB, no network)."""

from __future__ import annotations

import math

from app.providers.fake import FakeEmbeddings, FakeLLM


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_embeddings_are_deterministic() -> None:
    emb = FakeEmbeddings(dim=256)
    v1 = emb.embed(["policy coverage for flood damage"])[0]
    v2 = emb.embed(["policy coverage for flood damage"])[0]
    assert v1 == v2


def test_embeddings_dimension_and_norm() -> None:
    emb = FakeEmbeddings(dim=128)
    v = emb.embed(["hello world"])[0]
    assert len(v) == 128
    assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-9)


def test_embeddings_empty_text_is_stable_unit_vector() -> None:
    emb = FakeEmbeddings(dim=64)
    v = emb.embed([""])[0]
    assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-9)


def test_lexical_overlap_drives_similarity() -> None:
    emb = FakeEmbeddings(dim=512)
    base = emb.embed(["flood damage coverage limits for property"])[0]
    similar = emb.embed(["coverage limits for flood damage"])[0]
    unrelated = emb.embed(["quarterly internal circular about parking"])[0]
    assert _cosine(base, similar) > _cosine(base, unrelated)


def test_fake_llm_grounds_answer_in_context() -> None:
    llm = FakeLLM()
    prompt = (
        "Context: Flood damage is covered up to 50000 EUR. "
        "Theft requires a police report.\n"
        "Question: What is the flood damage limit?"
    )
    result = llm.generate(prompt)
    assert "flood damage is covered" in result.text.lower()
    assert result.model == "fake-deterministic-1"


def test_fake_llm_says_unknown_without_context() -> None:
    llm = FakeLLM()
    result = llm.generate("Context: \nQuestion: What is the flood limit?")
    assert "i don't know" in result.text.lower()


def test_fake_llm_stream_matches_generate() -> None:
    llm = FakeLLM()
    prompt = "Context: Alpha beta gamma.\nQuestion: alpha"
    streamed = "".join(llm.stream(prompt)).strip()
    assert streamed == llm.generate(prompt).text
