"""Unit tests for eval metrics (no database)."""

from __future__ import annotations

from eval.metrics import mean_reciprocal_rank, recall_at_k


def test_recall_at_k() -> None:
    assert recall_at_k([True, True, False, True]) == 0.75
    assert recall_at_k([]) == 0.0


def test_mrr() -> None:
    assert mean_reciprocal_rank([1, 2, None]) == (1.0 + 0.5 + 0.0) / 3
    assert mean_reciprocal_rank([]) == 0.0
