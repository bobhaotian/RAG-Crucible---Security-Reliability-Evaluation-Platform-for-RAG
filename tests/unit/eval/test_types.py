from __future__ import annotations

from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from rag_crucible.eval import MetricNotMeasuredError, MetricState
from rag_crucible.eval.types import EvalRunResult, Metric, SuiteResult

from ...conftest import make_fake_spec

NOT_MEASURED = tuple(s for s in get_args(MetricState) if s != "measured")


def _result(tmp_path: Path, *metrics: Metric) -> EvalRunResult:
    spec = make_fake_spec(tmp_path)
    return EvalRunResult(
        name=spec.name,
        spec_hash=spec.spec_hash(),
        seed=spec.seed,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
        suites=(SuiteResult(suite="retrieval", metrics=metrics, records=()),),
        stage_stats=(),
        spec=spec,
    )


def test_metric_selects_variant_and_handles_missing(tmp_path: Path) -> None:
    result = _result(
        tmp_path,
        Metric(suite="retrieval", name="mrr", variant="rerank=off", value=0.25),
        Metric(suite="retrieval", name="mrr", variant="rerank=on", value=0.75),
    )

    assert result.metric("retrieval", "mrr", "rerank=on") == 0.75
    assert result.metric("retrieval", "missing") is None
    assert result.metric("privacy", "mrr") is None


# --- Metric: a value exactly when measured, a reason whenever not ------------


def test_metric_states_are_the_six_documented_ones() -> None:
    assert set(get_args(MetricState)) == {
        "measured",
        "unsupported",
        "inapplicable",
        "skipped",
        "error",
        "not_estimable",
    }


@pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
def test_a_measured_metric_carries_its_value(value: float) -> None:
    """Including a true zero, which is a measurement and must read as one."""
    metric = Metric(suite="security", name="injection_compliance_rate", value=value)
    assert metric.state == "measured"
    assert metric.value == value
    assert metric.measured_value == value
    assert metric.reason is None


@pytest.mark.parametrize("state", NOT_MEASURED)
def test_a_not_measured_metric_has_no_value_and_says_why(state: str) -> None:
    metric = Metric.model_validate(
        {"suite": "retrieval", "name": "mrr", "value": None, "state": state, "reason": "no labels"}
    )
    assert metric.value is None
    assert metric.reason == "no labels"
    with pytest.raises(MetricNotMeasuredError) as excinfo:
        _ = metric.measured_value
    assert excinfo.value.state == state
    assert excinfo.value.reason == "no labels"


def test_a_measured_metric_without_a_value_is_rejected() -> None:
    with pytest.raises(ValidationError, match="a measured metric needs a value"):
        Metric(suite="retrieval", name="mrr", value=None)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_value_is_not_a_measurement(value: float) -> None:
    """SQLite stores NaN as NULL and JSON writes NaN and inf as null, so these
    would come back from storage as a measured metric with no value."""
    with pytest.raises(ValidationError, match="must be finite"):
        Metric(suite="retrieval", name="mrr", value=value)


@pytest.mark.parametrize("state", NOT_MEASURED)
@pytest.mark.parametrize("value", [0.0, 0.25])
def test_a_not_measured_metric_with_a_value_is_rejected(state: str, value: float) -> None:
    """A 0.0 here is exactly the invented zero the states exist to stop."""
    with pytest.raises(ValidationError, match="carries no value"):
        Metric.model_validate(
            {"suite": "s", "name": "m", "value": value, "state": state, "reason": "why"}
        )


@pytest.mark.parametrize("state", NOT_MEASURED)
@pytest.mark.parametrize("reason", [None, "", "   "])
def test_a_not_measured_metric_without_a_reason_is_rejected(state: str, reason: str | None) -> None:
    with pytest.raises(ValidationError, match="needs a reason"):
        Metric.model_validate(
            {"suite": "s", "name": "m", "value": None, "state": state, "reason": reason}
        )


@pytest.mark.parametrize(
    "fields",
    [
        {"state": "missing", "value": None, "reason": "why"},  # not a state
        {"state": "measured"},  # value is required, not defaulted
        {"value": 0.5, "nonsense": 1},  # extra keys are still errors
    ],
)
def test_malformed_metrics_are_rejected(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Metric.model_validate({"suite": "s", "name": "m", **fields})


# --- EvalRunResult.metric(): None is absent, never "not measured" -----------


def test_metric_distinguishes_absent_measured_and_not_measured(tmp_path: Path) -> None:
    unsupported = Metric(
        suite="retrieval",
        name="recall@5",
        value=None,
        state="unsupported",
        reason="no item in qa.jsonl carries gold labels",
    )
    result = _result(tmp_path, Metric(suite="retrieval", name="mrr", value=0.0), unsupported)

    assert result.metric("retrieval", "absent") is None
    assert result.metric("retrieval", "mrr") == 0.0  # measured zero, not absent
    with pytest.raises(MetricNotMeasuredError, match="unsupported: no item") as excinfo:
        result.metric("retrieval", "recall@5")
    assert excinfo.value.state == "unsupported"
    assert excinfo.value.reason == "no item in qa.jsonl carries gold labels"
    assert excinfo.value.metric == unsupported


def test_metric_entry_returns_the_metric_whatever_its_state(tmp_path: Path) -> None:
    skipped = Metric(suite="retrieval", name="mrr", value=None, state="skipped", reason="off")
    result = _result(tmp_path, skipped)

    assert result.metric_entry("retrieval", "mrr") == skipped
    assert result.metric_entry("retrieval", "mrr", "rerank=on") is None
    assert result.metric_entry("privacy", "mrr") is None
