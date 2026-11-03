"""Near-copy fuzzy matching for retrieval gating.

``token_set_ratio`` treats two strings as near-copies when they share almost the
same token multiset — tolerant of typos, extra adjectives, and word-order
changes, but not of true paraphrases/synonyms.
"""

from __future__ import annotations

from rapidfuzz import fuzz


def near_copy_ratio(left: str, right: str) -> float:
    """Return 0–100 ``token_set_ratio`` after light whitespace normalisation."""
    a = " ".join(left.split())
    b = " ".join(right.split())
    if not a or not b:
        return 0.0
    return float(fuzz.token_set_ratio(a, b))


def is_near_copy(left: str, right: str, *, min_ratio: float) -> bool:
    """True when fuzzy near-copy score is at least ``min_ratio`` (0–100)."""
    if min_ratio <= 0:
        return True
    return near_copy_ratio(left, right) >= min_ratio
