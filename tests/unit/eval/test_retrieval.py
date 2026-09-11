from __future__ import annotations

import pytest

from crucible.config import RetrievalSuiteConfig
from crucible.eval.retrieval import _aggregate, run_retrieval_suite
from crucible.obs.aggregate import TimingCollector
from crucible.qa import QAItem


def test_aggregate_calculates_each_cutoff_and_mrr() -> None:
    config = RetrievalSuiteConfig(k_values=(1, 2))
    metrics = {m.name: m.value for m in _aggregate([1, 2, None], config, variant="rerank=off")}

    assert metrics["recall@1"] == pytest.approx(1 / 3, abs=0.0001)
    assert metrics["recall@2"] == pytest.approx(2 / 3, abs=0.0001)
    assert metrics["ndcg@1"] == pytest.approx(1 / 3, abs=0.0001)
    assert metrics["mrr"] == 0.5


async def test_unlabelled_retrieval_is_typed_as_unsupported_not_zero() -> None:
    result = await run_retrieval_suite(
        object(),  # type: ignore[arg-type]
        [QAItem(qid="q1", question="What happened?")],
        RetrievalSuiteConfig(),
        TimingCollector(),
    )

    assert result.status == "skipped"
    assert result.metrics == ()
    assert result.records == ()
    assert result.error == "unsupported: retrieval labels missing for q1"
