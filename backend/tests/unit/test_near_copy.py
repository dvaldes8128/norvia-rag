"""Unit tests for near-copy fuzzy retrieval gating."""

from __future__ import annotations

from app.retrieval.near_copy import is_near_copy, near_copy_ratio


def test_near_copy_accepts_typos_and_extra_adjectives() -> None:
    base = "Flood damage is covered up to fifty thousand EUR under section A"
    with_typo = "Flood damage is covered up to fify thousand EUR under section A"
    with_adj = (
        "Flood damage is importantly covered up to fifty thousand EUR under section A"
    )
    assert near_copy_ratio(base, with_typo) >= 95
    assert near_copy_ratio(base, with_adj) >= 95
    assert is_near_copy(base, with_typo, min_ratio=95)
    assert is_near_copy(base, with_adj, min_ratio=95)


def test_near_copy_rejects_unrelated_prose() -> None:
    policy = "Flood damage is covered up to fifty thousand EUR under section A"
    parking = "Office parking permits renew every January for employees only"
    assert near_copy_ratio(policy, parking) < 50
    assert not is_near_copy(policy, parking, min_ratio=95)


def test_near_copy_min_ratio_zero_disables_gate() -> None:
    assert is_near_copy("alpha", "zzzz unrelated", min_ratio=0)


def test_open_question_vs_policy_prose_is_below_strict_gate() -> None:
    question = "What is the flood coverage limit under the home policy section A?"
    chunk = (
        "Flood damage is covered up to fifty thousand EUR under section A when water "
        "originates from overflowing rivers, storm surge, or sudden surface runoff."
    )
    # Documents the product trade-off: strict 95 empties open-QA retrieval.
    assert near_copy_ratio(question, chunk) < 95
