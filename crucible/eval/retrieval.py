"""Retrieval-quality suite: recall@k, nDCG@k, MRR — with rerank lift.

Each query is retrieved once; when ``rerank_lift`` is on, the same candidate
list is also reordered by the reranker (full list, not top_n) and every metric
is emitted under two variants, ``rerank=off`` and ``rerank=on``. The lift is
the per-metric delta; the report layer renders it explicitly.
"""

from __future__ import annotations

from crucible.config import RetrievalSuiteConfig
from crucible.eval.concurrent import bounded_gather
from crucible.eval.metrics import (
    first_relevant_rank,
    mean,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)
from crucible.eval.types import Metric, RetrievalRecord, SuiteResult
from crucible.obs import StageTimer
from crucible.obs.aggregate import TimingCollector
from crucible.pipeline import RagPipeline
from crucible.qa import QAItem, is_relevant

SUITE = "retrieval"


async def run_retrieval_suite(
    pipeline: RagPipeline,
    qa_items: list[QAItem],
    config: RetrievalSuiteConfig,
    collector: TimingCollector,
    *,
    concurrency: int = 4,
) -> SuiteResult:
    rerank = config.rerank_lift and pipeline.has_reranker

    async def evaluate_item(item: QAItem) -> RetrievalRecord:
        timer = StageTimer()
        candidates = await pipeline.retrieve(item.question, timer=timer)
        rank_initial = first_relevant_rank([is_relevant(c.chunk, item) for c in candidates])

        rank_reranked: int | None = None
        reranked_ids: tuple[str, ...] = ()
        if rerank:
            reranked = await pipeline.rerank(item.question, candidates, timer=timer)
            rank_reranked = first_relevant_rank([is_relevant(c.chunk, item) for c in reranked])
            reranked_ids = tuple(c.chunk.chunk_id for c in reranked)
        collector.add_all(timer.as_dict())

        return RetrievalRecord(
            qid=item.qid,
            question=item.question,
            first_hit_rank_initial=rank_initial,
            first_hit_rank_reranked=rank_reranked,
            retrieved_initial=tuple(c.chunk.chunk_id for c in candidates),
            retrieved_reranked=reranked_ids,
        )

    records = await bounded_gather([evaluate_item(item) for item in qa_items], concurrency)

    metrics = _aggregate([r.first_hit_rank_initial for r in records], config, variant="rerank=off")
    if rerank:
        metrics += _aggregate(
            [r.first_hit_rank_reranked for r in records], config, variant="rerank=on"
        )
    return SuiteResult(suite=SUITE, metrics=tuple(metrics), records=tuple(records))


def _aggregate(
    ranks: list[int | None], config: RetrievalSuiteConfig, *, variant: str
) -> list[Metric]:
    metrics = []
    for k in config.k_values:
        metrics.append(
            Metric(
                suite=SUITE,
                name=f"recall@{k}",
                variant=variant,
                value=round(mean([recall_at_k(r, k) for r in ranks]), 4),
            )
        )
        metrics.append(
            Metric(
                suite=SUITE,
                name=f"ndcg@{k}",
                variant=variant,
                value=round(mean([ndcg_at_k(r, k) for r in ranks]), 4),
            )
        )
    metrics.append(
        Metric(
            suite=SUITE,
            name="mrr",
            variant=variant,
            value=round(mean([reciprocal_rank(r) for r in ranks]), 4),
        )
    )
    return metrics
