"""Unit tests for tiktoken chunking with original-text offsets (Q1.1)."""

from __future__ import annotations

import pytest

from app.ingestion.chunking import chunk_pages, count_tokens
from app.ingestion.pdf import PageText


def _page(n: int, text: str) -> PageText:
    return PageText(page_number=n, text=text)


def test_count_tokens_cl100k() -> None:
    assert count_tokens("Hello world") == 2
    assert count_tokens("alpha beta gamma") == 3
    assert count_tokens("") == 0
    assert count_tokens("Flood damage: 50,000 EUR!") == 10


def test_chunk_preserves_accents_and_punctuation() -> None:
    text = "La póliza cubre daños: 50.000 EUR."
    chunks = chunk_pages([_page(1, text)], size_tokens=100, overlap_tokens=10)
    assert len(chunks) == 1
    assert chunks[0].content == text
    assert "póliza" in chunks[0].content
    assert chunks[0].token_count == count_tokens(text)


def test_chunk_respects_size_and_overlap() -> None:
    text = " ".join(f"word{i}" for i in range(40))
    size, overlap = 16, 4
    chunks = chunk_pages([_page(1, text)], size_tokens=size, overlap_tokens=overlap)
    assert len(chunks) >= 3
    assert all(c.token_count <= size for c in chunks)
    assert all(c.content in text for c in chunks)
    # Consecutive windows overlap in the original string (shared character span).
    for left, right in zip(chunks, chunks[1:], strict=False):
        assert left.content[-8:] in right.content or right.content[:12] in left.content


def test_chunk_page_number_is_first_token_page() -> None:
    pages = [
        _page(1, " ".join(f"a{i}" for i in range(5))),
        _page(2, " ".join(f"b{i}" for i in range(5))),
    ]
    chunks = chunk_pages(pages, size_tokens=6, overlap_tokens=1)
    assert chunks[0].page_number == 1
    assert chunks[0].chunk_index == 0
    assert all(c.chunk_index == i for i, c in enumerate(chunks))


def test_chunk_empty_pages_yield_empty() -> None:
    assert chunk_pages([_page(1, "   ")], size_tokens=10, overlap_tokens=2) == []


def test_chunk_rejects_invalid_sizes() -> None:
    pages = [_page(1, "one two three")]
    with pytest.raises(ValueError):
        chunk_pages(pages, size_tokens=0, overlap_tokens=0)
    with pytest.raises(ValueError):
        chunk_pages(pages, size_tokens=5, overlap_tokens=5)
    with pytest.raises(ValueError):
        chunk_pages(pages, size_tokens=5, overlap_tokens=-1)


def test_single_short_page_one_chunk() -> None:
    text = "alpha beta gamma"
    chunks = chunk_pages([_page(3, text)], size_tokens=100, overlap_tokens=10)
    assert len(chunks) == 1
    assert chunks[0].page_number == 3
    assert chunks[0].content == text
    assert chunks[0].token_count == count_tokens(text)


def test_chunk_collapses_pdf_soft_wraps() -> None:
    pages = [_page(1, "Flood damage up to fifty\nthousand EUR under section A.")]
    chunks = chunk_pages(pages, size_tokens=100, overlap_tokens=10)
    assert len(chunks) == 1
    assert "fifty thousand" in chunks[0].content
    assert "\n" not in chunks[0].content


def test_chunk_content_keeps_accents_across_pages() -> None:
    pages = [
        _page(1, "Póliza A: cobertura de agua."),
        _page(2, "Póliza B: exclusiones de guerra."),
    ]
    chunks = chunk_pages(pages, size_tokens=8, overlap_tokens=2)
    assert chunks
    joined = " ".join(c.content for c in chunks)
    assert "Póliza" in joined
    assert "agua" in joined or "guerra" in joined
