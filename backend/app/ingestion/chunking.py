"""Token-based chunking with overlap (F2.2 / D1).

Window size uses ``tiktoken`` ``cl100k_base`` (same family as common chat models).
Stored chunk text is a **slice of the original page text** (character offsets), so
citations keep punctuation, casing and non-ASCII letters (e.g. Spanish ``póliza``).

Fake embeddings keep a separate Unicode word tokenizer for lexical offline similarity;
they consume the sliced text, not a reconstructed token join.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import tiktoken

from app.ingestion.pdf import PageText

_ENCODING_NAME = "cl100k_base"
_PAGE_SEP = "\n"


@dataclass(frozen=True)
class TextChunk:
    content: str
    page_number: int  # 1-indexed page where the chunk starts
    chunk_index: int
    token_count: int


@lru_cache(maxsize=1)
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding(_ENCODING_NAME)


def count_tokens(text: str) -> int:
    """Return ``cl100k_base`` token count for ``text``."""
    if not text:
        return 0
    return len(_encoding().encode(text))


def _byte_to_char_index(text: str) -> list[int]:
    """Map each UTF-8 byte offset to a character index; last entry is ``len(text)``."""
    mapping: list[int] = []
    for i, ch in enumerate(text):
        mapping.extend([i] * len(ch.encode("utf-8")))
    mapping.append(len(text))
    return mapping


def _token_char_spans(text: str) -> list[tuple[int, int]]:
    """Exclusive ``[start, end)`` character spans for each token in ``text``."""
    enc = _encoding()
    token_ids = enc.encode(text)
    if not token_ids:
        return []
    b2c = _byte_to_char_index(text)
    spans: list[tuple[int, int]] = []
    byte_pos = 0
    for tok in token_ids:
        raw = enc.decode_single_token_bytes(tok)
        start_b = byte_pos
        end_b = byte_pos + len(raw)
        spans.append((b2c[start_b], b2c[end_b]))
        byte_pos = end_b
    return spans


def _join_pages(pages: list[PageText]) -> tuple[str, list[tuple[int, int, int]]]:
    """Concatenate pages with a newline; return text and ``(start, end, page)`` spans."""
    parts: list[str] = []
    spans: list[tuple[int, int, int]] = []
    pos = 0
    for page in pages:
        text = page.text or ""
        if not text.strip():
            continue
        if parts:
            parts.append(_PAGE_SEP)
            pos += len(_PAGE_SEP)
        start = pos
        parts.append(text)
        pos += len(text)
        spans.append((start, pos, page.page_number))
    return "".join(parts), spans


def _page_at(char_offset: int, page_spans: list[tuple[int, int, int]]) -> int:
    for start, end, page_number in page_spans:
        if start <= char_offset < end:
            return page_number
    # Offset on a separator or at EOF → nearest preceding page.
    for start, _end, page_number in reversed(page_spans):
        if char_offset >= start:
            return page_number
    return page_spans[0][2]


def chunk_pages(
    pages: list[PageText],
    *,
    size_tokens: int,
    overlap_tokens: int,
) -> list[TextChunk]:
    """Split pages into overlapping chunks sized by ``cl100k_base`` tokens.

    Chunks may span page boundaries; ``page_number`` is the page of the first
    character of the sliced window. ``content`` is ``full_text[start:end]``.
    """
    if size_tokens <= 0:
        raise ValueError("size_tokens must be positive")
    if overlap_tokens < 0:
        raise ValueError("overlap_tokens must be non-negative")
    if overlap_tokens >= size_tokens:
        raise ValueError("overlap_tokens must be smaller than size_tokens")

    full_text, page_spans = _join_pages(pages)
    if not full_text.strip():
        return []

    token_spans = _token_char_spans(full_text)
    if not token_spans:
        return []

    step = size_tokens - overlap_tokens
    chunks: list[TextChunk] = []
    start = 0
    index = 0
    n = len(token_spans)
    while start < n:
        end = min(start + size_tokens, n)
        char_start = token_spans[start][0]
        char_end = token_spans[end - 1][1]
        # Keep punctuation/casing/accents from the PDF slice; collapse soft wraps
        # from extraction so markers like "fifty thousand" stay searchable.
        content = " ".join(full_text[char_start:char_end].split())
        chunks.append(
            TextChunk(
                content=content,
                page_number=_page_at(char_start, page_spans),
                chunk_index=index,
                token_count=end - start,
            )
        )
        index += 1
        if end >= n:
            break
        start += step

    return chunks
