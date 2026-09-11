"""Rank metrics under the single-gold formulation.

The seeded corpus has exactly one gold passage per question (and BEIR SciFact
qrels are predominantly single-document), so v1 metrics use first-relevant-rank
semantics:

- recall@k = 1 if the first relevant result ranks within k, else 0
  (averaged over queries this is the standard "hit rate@k" / KILT-style
  answer-in-context@k);
- nDCG@k   = 1/log2(rank+1) if rank <= k, else 0 — the binary single-relevant
  reduction of nDCG;
- MRR      = 1/rank, 0 on miss.

Graded multi-relevance nDCG is future work and is called out in the README.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def first_relevant_rank(flags: Sequence[bool]) -> int | None:
    """1-based rank of the first relevant result, or None if absent."""
    for position, flag in enumerate(flags, start=1):
        if flag:
            return position
    return None


def recall_at_k(rank: int | None, k: int) -> float:
    return 1.0 if rank is not None and rank <= k else 0.0


def ndcg_at_k(rank: int | None, k: int) -> float:
    if rank is None or rank > k:
        return 0.0
    return 1.0 / math.log2(rank + 1)


def reciprocal_rank(rank: int | None) -> float:
    return 0.0 if rank is None else 1.0 / rank


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0
