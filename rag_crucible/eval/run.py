"""Run the suites a spec selects and assemble the EvalRunResult.

Used by the CLI directly and by the Phase 3 worker per job. Two failure
modes, chosen by the caller:

- ``fail_fast=True`` (CLI): the first suite error propagates — interactive
  use wants the traceback.
- ``fail_fast=False`` (worker): a failing suite is recorded as
  ``status="failed"`` with its error and the other suites' results are kept —
  partial results are never thrown away (DESIGN.md §7).

Suites run concurrently (independent by design); items within a suite run
through a bounded semaphore (``suites.concurrency``). Providers are warmed
before any timed work so lazy model loads don't pollute latency stats. Seed
discipline: each suite derives its own child seed (spec.seed + fixed offset),
so adding a suite never perturbs another suite's sampling.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any

from rag_crucible.config import RunSpec
from rag_crucible.eval.faithfulness import run_faithfulness_suite
from rag_crucible.eval.judge import build_judge
from rag_crucible.eval.privacy import run_privacy_suite
from rag_crucible.eval.retrieval import run_retrieval_suite
from rag_crucible.eval.security import run_security_suite
from rag_crucible.eval.types import EvalRunResult, SuiteResult
from rag_crucible.index import VectorIndex
from rag_crucible.ingest import IngestReport
from rag_crucible.obs.aggregate import TimingCollector
from rag_crucible.pipeline import build_pipeline
from rag_crucible.qa import QAItem, load_qa

_SUITE_SEED_OFFSETS = {"retrieval": 1, "faithfulness": 2, "security": 3, "privacy": 4}

_SuiteCoro = Coroutine[Any, Any, SuiteResult]


async def run_eval(
    spec: RunSpec,
    index: VectorIndex,
    *,
    fail_fast: bool = True,
    run_id: str | None = None,
    ingestion: IngestReport | None = None,
) -> EvalRunResult:
    if spec.suites is None:
        raise ValueError(f"spec {spec.name!r} configures no evaluation suites")
    # QA-backed suites use the file when supplied. Retrieval requires it at
    # config validation; answer-side suites report an actionable runtime error
    # until A3 adds the questions-only command-line front door.
    needs_qa = bool(spec.suites.retrieval or spec.suites.faithfulness or spec.suites.security)
    qa_items: list[QAItem] = []
    if needs_qa and spec.corpus.qa is not None:
        qa_items = load_qa(spec.corpus.qa)
    elif needs_qa:
        raise ValueError("selected suites need questions; provide corpus.qa")
    pipeline = build_pipeline(spec, index)
    collector = TimingCollector()
    concurrency = spec.suites.concurrency
    started_at = _now()

    # Every suite except retrieval generates answers, so warm the generator
    # unless retrieval is the only suite selected.
    needs_generator = bool(spec.suites.faithfulness or spec.suites.security or spec.suites.privacy)
    await pipeline.warmup(generator=needs_generator)

    guarded: list[_SuiteCoro] = []
    if spec.suites.retrieval is not None:
        guarded.append(
            _guard(
                "retrieval",
                run_retrieval_suite(
                    pipeline, qa_items, spec.suites.retrieval, collector, concurrency=concurrency
                ),
                fail_fast=fail_fast,
            )
        )
    if spec.suites.faithfulness is not None:
        judge = build_judge(spec.suites.faithfulness.judge)
        guarded.append(
            _guard(
                "faithfulness",
                run_faithfulness_suite(
                    pipeline,
                    qa_items,
                    spec.suites.faithfulness,
                    judge,
                    spec.seed + _SUITE_SEED_OFFSETS["faithfulness"],
                    collector,
                    concurrency=concurrency,
                ),
                fail_fast=fail_fast,
            )
        )
    if spec.suites.security is not None:
        guarded.append(
            _guard(
                "security",
                run_security_suite(
                    pipeline,
                    spec,
                    qa_items,
                    spec.suites.security,
                    spec.seed + _SUITE_SEED_OFFSETS["security"],
                    collector,
                    concurrency=concurrency,
                ),
                fail_fast=fail_fast,
            )
        )
    if spec.suites.privacy is not None:
        guarded.append(
            _guard(
                "privacy",
                run_privacy_suite(
                    pipeline,
                    spec,
                    spec.suites.privacy,
                    spec.seed + _SUITE_SEED_OFFSETS["privacy"],
                    collector,
                    concurrency=concurrency,
                ),
                fail_fast=fail_fast,
            )
        )
    suite_results = await asyncio.gather(*guarded)

    return EvalRunResult(
        run_id=run_id,
        name=spec.name,
        spec_hash=spec.spec_hash(),
        spec_identity_json=spec.canonical_json(),
        seed=spec.seed,
        started_at=started_at,
        finished_at=_now(),
        suites=tuple(suite_results),
        stage_stats=tuple(collector.stats()),
        ingestion=ingestion,
        spec=spec,
    )


async def _guard(suite: str, coro: _SuiteCoro, *, fail_fast: bool) -> SuiteResult:
    try:
        return await coro
    except Exception as exc:
        if fail_fast:
            raise
        return SuiteResult(
            suite=suite,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
            metrics=(),
            records=(),
        )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
