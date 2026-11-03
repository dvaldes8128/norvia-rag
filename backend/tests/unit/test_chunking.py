"""Unit tests for token-based chunking with overlap (Q1.1)."""

from __future__ import annotations

import pytest

from app.ingestion.chunking import chunk_pages, count_tokens
from app.ingestion.pdf import PageText


def _page(n: int, text: str) -> PageText:
    return PageText(page_number=n, text=text)


def test_count_tokens_alphanumeric() -> None:
    # Tokenizer keeps [a-z0-9]+ so "50,000" → "50" + "000"
    assert count_tokens("Flood damage: 50,000 EUR!") == 5
    assert count_tokens("Hello world") == 2
    assert count_tokens("") == 0


def test_chunk_respects_size_and_overlap() -> None:
    # 20 tokens on one page
    words = " ".join(f"w{i}" for i in range(20))
    chunks = chunk_pages([_page(1, words)], size_tokens=8, overlap_tokens=2)
    assert len(chunks) >= 3
    assert all(c.token_count <= 8 for c in chunks)
    # Consecutive windows share the overlap tokens
    first_tokens = chunks[0].content.split()
    second_tokens = chunks[1].content.split()
    assert first_tokens[-2:] == second_tokens[:2]


def test_chunk_page_number_is_first_token_page() -> None:
    pages = [
        _page(1, " ".join(f"a{i}" for i in range(5))),
        _page(2, " ".join(f"b{i}" for i in range(5))),
    ]
    chunks = chunk_pages(pages, size_tokens=6, overlap_tokens=1)
    assert chunks[0].page_number == 1
    # Second window starts near the end of page 1 / start of page 2
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
    chunks = chunk_pages([_page(3, "alpha beta gamma")], size_tokens=100, overlap_tokens=10)
    assert len(chunks) == 1
    assert chunks[0].page_number == 3
    assert chunks[0].content == "alpha beta gamma"
    assert chunks[0].token_count == 3
