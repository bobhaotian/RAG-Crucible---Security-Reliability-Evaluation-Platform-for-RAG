"""Data contracts for evaluation results.

Every headline number is backed by per-item records — a metric is never
reported without the evidence to audit it. ``variant`` is how one run carries
its own comparisons (``rerank=on`` / ``rerank=off`` now; defense conditions in
Phase 4); the result store and dashboard key on it.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from crucible.config import RunSpec
from crucible.obs.aggregate import StageStats
from crucible.types import StrictModel


class Metric(StrictModel):
    suite: str
    name: str  # e.g. "recall@10", "hallucination_rate"
    variant: str = ""  # e.g. "rerank=on"; "" when the metric has one condition
    value: float


class RetrievalRecord(StrictModel):
    kind: Literal["retrieval"] = "retrieval"
    qid: str
    question: str
    first_hit_rank_initial: int | None  # 1-based; None = gold never retrieved
    first_hit_rank_reranked: int | None  # None when rerank lift is off
    retrieved_initial: tuple[str, ...]  # chunk ids in rank order
    retrieved_reranked: tuple[str, ...]


class ClaimJudgment(StrictModel):
    claim: str
    supported: bool
    parse_ok: bool  # judge output parsed cleanly (False = heuristic fallback)
    cached: bool


class CitationJudgment(StrictModel):
    chunk_id: str
    supports_claim: bool


class FaithfulnessRecord(StrictModel):
    kind: Literal["faithfulness"] = "faithfulness"
    qid: str
    question: str
    answer: str
    claims: tuple[ClaimJudgment, ...]
    citations_parsed: bool  # did the generator emit usable [n] markers?
    citations: tuple[CitationJudgment, ...]  # judged parsed citations only
    answer_match: bool  # gold answer string appears in the answer


EvalRecord = Annotated[RetrievalRecord | FaithfulnessRecord, Field(discriminator="kind")]


class SuiteResult(StrictModel):
    suite: str
    status: Literal["succeeded", "failed"] = "succeeded"
    error: str | None = None
    metrics: tuple[Metric, ...]
    records: tuple[EvalRecord, ...]


class EvalRunResult(StrictModel):
    """Everything one evaluation run produced. Persisted as results.json in
    Phase 2; the Phase 3 result store decomposes the same model into tables."""

    name: str
    spec_hash: str
    seed: int
    started_at: str  # ISO-8601 UTC
    finished_at: str
    suites: tuple[SuiteResult, ...]
    stage_stats: tuple[StageStats, ...]
    spec: RunSpec  # the full spec, so the run is reproducible from this file

    def metric(self, suite: str, name: str, variant: str = "") -> float | None:
        for suite_result in self.suites:
            if suite_result.suite != suite:
                continue
            for metric in suite_result.metrics:
                if metric.name == name and metric.variant == variant:
                    return metric.value
        return None
