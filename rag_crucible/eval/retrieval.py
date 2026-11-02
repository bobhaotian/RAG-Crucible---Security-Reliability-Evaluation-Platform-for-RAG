"""Retrieval-quality suite: recall@k, nDCG@k, MRR — with rerank lift.

Each query is retrieved once; when ``rerank_lift`` is on, the same candidate
list is also reordered by the reranker (full list, not top_n) and every metric
is emitted under two variants, ``rerank=off`` and ``rerank=on``. The lift is
the per-metric delta; the report layer renders it explicitly.

Only questions with a retrieval label (``gold_fact`` or ``gold_docs``) can be
scored. A partially labelled set is scored over its labelled questions: every
metric records how many were left out (``n_excluded``), and an
``excluded_item`` record names each one. With none labelled, the suite is
skipped, and each metric it would have produced is emitted as ``unsupported``
with the reason, rather than left out. When ``rerank_lift`` is on but the
pipeline was built without a reranker, the rerank-on variant is emitted as
``inapplicable``. (A reranker configured with ``enabled: false`` is still built
and still measured here: ``enabled`` governs serving, not the lift.)
"""

from __future__ import annotations

from rag_crucible.config import RetrievalSuiteConfig
from rag_crucible.eval.concurrent import bounded_gather
from rag_crucible.eval.measure import not_measured, rate
from rag_crucible.eval.metrics import (
    first_relevant_rank,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)
from rag_crucible.eval.types import (
    ExcludedItemRecord,
    Metric,
    NotMeasuredState,
    RetrievalRecord,
    SuiteResult,
)
from rag_crucible.obs import StageTimer
from rag_crucible.obs.aggregate import TimingCollector
from rag_crucible.pipeline import RagPipeline
from rag_crucible.qa import QAItem, is_relevant

SUITE = "retrieval"


async def run_retrieval_suite(
    pipeline: RagPipeline,
    qa_items: list[QAItem],
    config: RetrievalSuiteConfig,
    collector: TimingCollector,
    *,
    concurrency: int = 4,
) -> SuiteResult:
    labelled = [item for item in qa_items if item.scores_retrieval]
    excluded = len(qa_items) - len(labelled)
    unlabelled = [
        ExcludedItemRecord(unit="question", item_id=item.qid, reason="no retrieval label")
        for item in qa_items
        if not item.scores_retrieval
    ]
    rerank = config.rerank_lift and pipeline.has_reranker
    # Asked for, but there is no rerank-on ranking to score: say so per metric.
    no_reranker = config.rerank_lift and not pipeline.has_reranker
    if not labelled:
        reason = (
            f"no question carries a retrieval label (gold_fact or gold_docs); "
            f"{len(qa_items)} question(s) loaded"
        )
        variants = ["rerank=off", "rerank=on"] if rerank else ["rerank=off"]
        unsupported = [
            not_measured(
                SUITE,
                name,
                state="unsupported",
                reason=reason,
                variant=v,
                n=0,
                excluded=excluded,
            )
            for v in variants
            for name in _names(config)
        ]
        return SuiteResult(
            suite=SUITE,
            status="skipped",
            metrics=tuple(unsupported + (_no_rerank_on(config) if no_reranker else [])),
            records=tuple(unlabelled),
        )

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

    records = await bounded_gather([evaluate_item(item) for item in labelled], concurrency)

    metrics = _aggregate(
        [r.first_hit_rank_initial for r in records],
        config,
        variant="rerank=off",
        excluded=excluded,
    )
    if rerank:
        metrics += _aggregate(
            [r.first_hit_rank_reranked for r in records],
            config,
            variant="rerank=on",
            excluded=excluded,
        )
    elif no_reranker:
        metrics += _no_rerank_on(config)
    return SuiteResult(suite=SUITE, metrics=tuple(metrics), records=(*records, *unlabelled))


def _no_rerank_on(config: RetrievalSuiteConfig) -> list[Metric]:
    return [
        not_measured(
            SUITE,
            name,
            state="inapplicable",
            reason="rerank_lift is on, but the pipeline was built without a reranker",
            variant="rerank=on",
        )
        for name in _names(config)
    ]


def _names(config: RetrievalSuiteConfig) -> list[str]:
    """Every metric this suite emits per variant, in emission order."""
    return [name for k in config.k_values for name in (f"recall@{k}", f"ndcg@{k}")] + ["mrr"]


# Unreachable while every scored question is labelled, which the caller ensures.
_EMPTY: tuple[NotMeasuredState, str] = ("not_estimable", "no labelled question was scored")


def _aggregate(
    ranks: list[int | None], config: RetrievalSuiteConfig, *, variant: str, excluded: int
) -> list[Metric]:
    def scored(name: str, values: list[float]) -> Metric:
        return rate(SUITE, name, values, variant=variant, excluded=excluded, empty=_EMPTY)

    metrics = []
    for k in config.k_values:
        metrics.append(scored(f"recall@{k}", [recall_at_k(r, k) for r in ranks]))
        metrics.append(scored(f"ndcg@{k}", [ndcg_at_k(r, k) for r in ranks]))
    metrics.append(scored("mrr", [reciprocal_rank(r) for r in ranks]))
    return metrics
