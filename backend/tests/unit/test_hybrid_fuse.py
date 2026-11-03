"""Unit tests for hybrid score fusion (no database)."""

from __future__ import annotations

import pytest

from app.retrieval.hybrid import fuse_scores


def test_fusion_prefers_strong_vector_when_weighted() -> None:
    fused = fuse_scores(
        [0.9, 0.1],
        [0.1, 0.9],
        vector_weight=0.8,
        text_weight=0.2,
    )
    assert fused[0] > fused[1]


def test_fusion_prefers_strong_text_when_weighted() -> None:
    fused = fuse_scores(
        [0.9, 0.1],
        [0.1, 0.9],
        vector_weight=0.2,
        text_weight=0.8,
    )
    assert fused[1] > fused[0]


def test_equal_positive_channel_normalises_to_one() -> None:
    fused = fuse_scores([0.5, 0.5], [0.0, 0.0], vector_weight=1.0, text_weight=0.0)
    assert fused == [1.0, 1.0]


def test_length_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        fuse_scores([1.0], [1.0, 2.0], vector_weight=0.5, text_weight=0.5)


def test_zero_weights_raise() -> None:
    with pytest.raises(ValueError):
        fuse_scores([1.0], [1.0], vector_weight=0.0, text_weight=0.0)
