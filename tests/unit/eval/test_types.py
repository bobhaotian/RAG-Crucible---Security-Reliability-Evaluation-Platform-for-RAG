from __future__ import annotations

from crucible.eval.types import EvalRunResult, Metric, SuiteResult

from ...conftest import make_fake_spec


def test_metric_selects_variant_and_handles_missing(tmp_path) -> None:
    spec = make_fake_spec(tmp_path)
    result = EvalRunResult(
        name=spec.name,
        spec_hash=spec.spec_hash(),
        seed=spec.seed,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
        suites=(
            SuiteResult(
                suite="retrieval",
                metrics=(
                    Metric(suite="retrieval", name="mrr", variant="rerank=off", value=0.25),
                    Metric(suite="retrieval", name="mrr", variant="rerank=on", value=0.75),
                ),
                records=(),
            ),
        ),
        stage_stats=(),
        spec=spec,
    )

    assert result.metric("retrieval", "mrr", "rerank=on") == 0.75
    assert result.metric("retrieval", "missing") is None
    assert result.metric("privacy", "mrr") is None
