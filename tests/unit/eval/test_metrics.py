"""Golden values for the single-gold rank metrics."""

from __future__ import annotations

import math

from crucible.eval.metrics import (
    first_relevant_rank,
    mean,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_first_relevant_rank() -> None:
    assert first_relevant_rank([False, False, True, True]) == 3
    assert first_relevant_rank([True]) == 1
    assert first_relevant_rank([False, False]) is None
    assert first_relevant_rank([]) is None


def test_recall_at_k() -> None:
    assert recall_at_k(3, 5) == 1.0
    assert recall_at_k(3, 3) == 1.0
    assert recall_at_k(3, 2) == 0.0
    assert recall_at_k(None, 100) == 0.0


def test_ndcg_at_k_log_discount() -> None:
    assert ndcg_at_k(1, 10) == 1.0
    assert math.isclose(ndcg_at_k(2, 10), 1 / math.log2(3))
    assert math.isclose(ndcg_at_k(4, 10), 1 / math.log2(5))
    assert ndcg_at_k(11, 10) == 0.0
    assert ndcg_at_k(None, 10) == 0.0


def test_reciprocal_rank() -> None:
    assert reciprocal_rank(1) == 1.0
    assert reciprocal_rank(4) == 0.25
    assert reciprocal_rank(None) == 0.0


def test_mean_handles_empty() -> None:
    assert mean([]) == 0.0
    assert mean([0.0, 1.0]) == 0.5
