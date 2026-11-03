"""R7 — recall@k over the synthetic corpus must stay above the quality bar."""

from __future__ import annotations

import pytest

from eval.metrics import recall_at_k
from eval.run import _evaluate, _prepare_corpus

pytestmark = pytest.mark.integration


def test_corpus_recall_at_5(pg_engine) -> None:
    assert pg_engine is not None
    tenant_id = "eval-integration"
    _prepare_corpus(tenant_id)
    results = _evaluate(tenant_id, k=5)
    recall = recall_at_k([r.hit for r in results])
    marker_recall = recall_at_k([r.marker_hit for r in results])
    assert recall >= 0.8, f"recall@5={recall:.3f} below 0.8; results={results!r}"
    assert marker_recall >= 0.7, f"marker_recall@5={marker_recall:.3f} below 0.7"
