"""Token-based chunking with overlap (F2.2 / D1).

Uses the same lowercase alphanumeric tokenizer as the fake embeddings provider so
chunk boundaries and lexical similarity stay consistent in the offline path.
Token counts are approximate (not tiktoken); sizes are tuned via recall@k.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.ingestion.pdf import PageText

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


@dataclass(frozen=True)
class TextChunk:
    content: str
    page_number: int  # 1-indexed page where the chunk starts
    chunk_index: int
    token_count: int


def count_tokens(text: str) -> int:
    """Approximate token count (alphanumeric word pieces)."""
    return len(_TOKEN_RE.findall(text))


def chunk_pages(
    pages: list[PageText],
    *,
    size_tokens: int,
    overlap_tokens: int,
) -> list[TextChunk]:
    """Split pages into overlapping chunks.

    Tokens are streamed across page boundaries so a chunk may span pages; the
    stored ``page_number`` is the page of the chunk's first token (citation-friendly).
    """
    if size_tokens <= 0:
        raise ValueError("size_tokens must be positive")
    if overlap_tokens < 0:
        raise ValueError("overlap_tokens must be non-negative")
    if overlap_tokens >= size_tokens:
        raise ValueError("overlap_tokens must be smaller than size_tokens")

    # Flatten to (token, page_number) so windows keep page attribution.
    stream: list[tuple[str, int]] = []
    for page in pages:
        for token in _TOKEN_RE.findall(page.text):
            stream.append((token, page.page_number))

    if not stream:
        return []

    step = size_tokens - overlap_tokens
    chunks: list[TextChunk] = []
    start = 0
    index = 0
    while start < len(stream):
        end = min(start + size_tokens, len(stream))
        window = stream[start:end]
        content = " ".join(tok for tok, _ in window)
        chunks.append(
            TextChunk(
                content=content,
                page_number=window[0][1],
                chunk_index=index,
                token_count=len(window),
            )
        )
        index += 1
        if end >= len(stream):
            break
        start += step

    return chunks
