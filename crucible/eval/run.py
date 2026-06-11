"""Run the suites a spec selects and assemble the EvalRunResult.

Phase 2 entrypoint (CLI calls this; the Phase 3 runner reuses it per job).
Suites run sequentially here — the local providers are CPU-bound, so
concurrency buys nothing until hosted providers arrive with the runner.

Seed discipline: each suite derives its own child seed (spec.seed + fixed
offset), so adding a suite never perturbs another suite's sampling.
"""

from __future__ import annotations

from datetime import UTC, datetime

from crucible.config import RunSpec
from crucible.eval.faithfulness import run_faithfulness_suite
from crucible.eval.judge import build_judge
from crucible.eval.qa import load_qa
from crucible.eval.retrieval import run_retrieval_suite
from crucible.eval.types import EvalRunResult, SuiteResult
from crucible.index import VectorIndex
from crucible.obs.aggregate import TimingCollector
from crucible.pipeline import build_pipeline

_SUITE_SEED_OFFSETS = {"retrieval": 1, "faithfulness": 2}


async def run_eval(spec: RunSpec, index: VectorIndex) -> EvalRunResult:
    if spec.suites is None:
        raise ValueError(f"spec {spec.name!r} configures no evaluation suites")
    assert spec.corpus.qa is not None  # enforced by RunSpec validation
    qa_items = load_qa(spec.corpus.qa)
    pipeline = build_pipeline(spec, index)
    collector = TimingCollector()
    started_at = _now()

    suite_results: list[SuiteResult] = []
    if spec.suites.retrieval is not None:
        suite_results.append(
            await run_retrieval_suite(pipeline, qa_items, spec.suites.retrieval, collector)
        )
    if spec.suites.faithfulness is not None:
        judge = build_judge(spec.suites.faithfulness.judge)
        suite_results.append(
            await run_faithfulness_suite(
                pipeline,
                qa_items,
                spec.suites.faithfulness,
                judge,
                spec.seed + _SUITE_SEED_OFFSETS["faithfulness"],
                collector,
            )
        )

    return EvalRunResult(
        name=spec.name,
        spec_hash=spec.spec_hash(),
        seed=spec.seed,
        started_at=started_at,
        finished_at=_now(),
        suites=tuple(suite_results),
        stage_stats=tuple(collector.stats()),
        spec=spec,
    )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
