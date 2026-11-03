"""Retrieval metrics for the synthetic corpus eval (R7)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuestionResult:
    question_id: str
    question: str
    expected_doc_ids: list[str]
    retrieved_doc_ids: list[str]
    hit: bool
    marker_hit: bool
    rank: int | None


def recall_at_k(hits: list[bool]) -> float:
    if not hits:
        return 0.0
    return sum(1 for h in hits if h) / len(hits)


def mean_reciprocal_rank(ranks: list[int | None]) -> float:
    if not ranks:
        return 0.0
    total = 0.0
    for rank in ranks:
        if rank is None or rank <= 0:
            continue
        total += 1.0 / rank
    return total / len(ranks)
