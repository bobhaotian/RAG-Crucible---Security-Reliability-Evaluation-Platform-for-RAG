from __future__ import annotations

import pytest

from rag_crucible.config import RetrievalSuiteConfig
from rag_crucible.eval.retrieval import _aggregate, run_retrieval_suite
from rag_crucible.obs.aggregate import TimingCollector
from rag_crucible.qa import QAItem


def test_aggregate_calculates_each_cutoff_and_mrr() -> None:
    config = RetrievalSuiteConfig(k_values=(1, 2))
    aggregated = _aggregate([1, 2, None], config, variant="rerank=off", excluded=0)
    metrics = {m.name: m.value for m in aggregated}
    assert {(m.n, m.n_excluded) for m in aggregated} == {(3, 0)}

    assert metrics["recall@1"] == pytest.approx(1 / 3, abs=0.0001)
    assert metrics["recall@2"] == pytest.approx(2 / 3, abs=0.0001)
    assert metrics["ndcg@1"] == pytest.approx(1 / 3, abs=0.0001)
    assert metrics["mrr"] == 0.5


class _NoRetrieval:
    """A pipeline the suite must not query: nothing it could score is labelled."""

    has_reranker = True


async def test_unlabelled_retrieval_is_typed_as_unsupported_not_zero() -> None:
    result = await run_retrieval_suite(
        _NoRetrieval(),  # type: ignore[arg-type]
        [QAItem(qid="q1", question="What happened?"), QAItem(qid="q2", question="And?")],
        RetrievalSuiteConfig(k_values=(1, 5)),
        TimingCollector(),
    )

    # Skipped, with every metric it would have produced present and saying why,
    # and no non-error smuggled into SuiteResult.error.
    assert result.status == "skipped"
    assert result.error is None
    assert result.records == ()
    names = ["recall@1", "ndcg@1", "recall@5", "ndcg@5", "mrr"]
    assert [(m.name, m.variant) for m in result.metrics] == [
        (name, variant) for variant in ("rerank=off", "rerank=on") for name in names
    ]
    for metric in result.metrics:
        assert metric.value is None and metric.state == "unsupported"
        assert (metric.n, metric.n_excluded) == (0, 2)
        assert (
            metric.reason is not None and "no question carries a retrieval label" in metric.reason
        )
