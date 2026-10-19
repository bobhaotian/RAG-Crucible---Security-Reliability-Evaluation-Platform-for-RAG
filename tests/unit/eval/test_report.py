"""The report shows a metric that was not measured as its state and reason,
never as a number, a zero, or a bar."""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

import matplotlib
import pytest

from rag_crucible.eval import MetricState
from rag_crucible.eval.report import _bars, describe, format_value, render_summary, write_report
from rag_crucible.eval.types import EvalRunResult, Metric, SuiteResult

from ...conftest import make_fake_spec

matplotlib.use("Agg")

NOT_MEASURED = tuple(s for s in get_args(MetricState) if s != "measured")
NUMBER = re.compile(r"\d\.\d")


def _missing(
    suite: str, name: str, variant: str = "", state: MetricState = "unsupported"
) -> Metric:
    return Metric(
        suite=suite,
        name=name,
        variant=variant,
        value=None,
        state=state,
        reason=f"why {name} {variant}".strip(),
    )


def _result(tmp_path: Path, *suites: SuiteResult) -> EvalRunResult:
    spec = make_fake_spec(tmp_path)
    return EvalRunResult(
        name=spec.name,
        spec_hash=spec.spec_hash(),
        seed=spec.seed,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
        suites=suites,
        stage_stats=(),
        spec=spec,
    )


def _suite(name: str, *metrics: Metric) -> SuiteResult:
    return SuiteResult(suite=name, metrics=metrics, records=())


def _row(summary: str, first_cell: str) -> str:
    rows = [line for line in summary.splitlines() if line.startswith(f"| {first_cell} |")]
    assert len(rows) == 1, (first_cell, rows)
    return rows[0]


def test_format_value_separates_measured_zero_unmeasured_and_absent() -> None:
    assert format_value(Metric(suite="s", name="m", value=0.0)) == "0.0000"
    assert format_value(_missing("s", "m", state="not_estimable")) == "— (not_estimable)"
    assert format_value(None) == "—"


@pytest.mark.parametrize("state", NOT_MEASURED)
def test_every_unmeasured_state_renders_with_its_reason_and_no_number(
    tmp_path: Path, state: MetricState
) -> None:
    result = _result(
        tmp_path,
        _suite(
            "faithfulness",
            Metric(suite="faithfulness", name="answer_accuracy", value=0.5),
            _missing("faithfulness", "groundedness", state=state),
        ),
    )

    summary = render_summary(result)

    row = _row(summary, "groundedness")
    assert row == f"| groundedness | — ({state}) |"
    assert f"- groundedness — {state}: why groundedness" in summary
    assert _row(summary, "answer_accuracy") == "| answer_accuracy | 0.5000 |"


def test_a_lift_needs_both_sides_measured(tmp_path: Path) -> None:
    result = _result(
        tmp_path,
        _suite(
            "retrieval",
            Metric(suite="retrieval", name="mrr", variant="rerank=off", value=0.25),
            Metric(suite="retrieval", name="mrr", variant="rerank=on", value=0.75),
            Metric(suite="retrieval", name="recall@5", variant="rerank=off", value=0.5),
            _missing("retrieval", "recall@5", "rerank=on", state="error"),
            _missing("retrieval", "ndcg@10", "rerank=off"),
            _missing("retrieval", "ndcg@10", "rerank=on"),
        ),
    )

    summary = render_summary(result)

    assert _row(summary, "mrr") == "| mrr | 0.2500 | 0.7500 | +0.5000 |"
    assert _row(summary, "recall@5") == "| recall@5 | 0.5000 | — (error) | — |"
    assert _row(summary, "ndcg@10") == "| ndcg@10 | — (unsupported) | — (unsupported) | — |"
    assert "- recall@5 [rerank=on] — error: why recall@5 rerank=on" in summary
    # one line per distinct state and reason
    assert "- ndcg@10 [rerank=off] — unsupported: why ndcg@10 rerank=off" in summary


def test_identical_reasons_are_listed_once(tmp_path: Path) -> None:
    def same(name: str) -> Metric:
        return Metric(
            suite="retrieval",
            name=name,
            variant="rerank=on",
            value=None,
            state="inapplicable",
            reason="no reranker configured",
        )

    result = _result(
        tmp_path,
        _suite(
            "retrieval",
            Metric(suite="retrieval", name="mrr", variant="rerank=off", value=0.25),
            same("mrr"),
            Metric(suite="retrieval", name="recall@1", variant="rerank=off", value=0.0),
            same("recall@1"),
        ),
    )

    summary = render_summary(result)

    assert (
        "- mrr [rerank=on], recall@1 [rerank=on] — inapplicable: no reranker configured" in summary
    )
    assert summary.count("no reranker configured") == 1


def test_security_cells_never_default_to_zero(tmp_path: Path) -> None:
    result = _result(
        tmp_path,
        _suite(
            "security",
            _missing("security", "poison_retrieval_rate"),
            Metric(suite="security", name="injection_retrieval_rate", value=1.0),
            Metric(
                suite="security",
                name="knowledge_corruption_rate",
                variant="defense=none",
                value=0.0,
            ),
            _missing(
                "security", "knowledge_corruption_rate", "defense=injection_filter", "skipped"
            ),
            # emitted under `none` only: absent under injection_filter, not zero
            Metric(
                suite="security",
                name="injection_compliance_rate",
                variant="defense=none",
                value=0.5,
            ),
        ),
    )

    summary = render_summary(result)

    assert "- poison_retrieval_rate: — (unsupported)" in summary
    assert "- injection_retrieval_rate: 1.0000" in summary
    assert _row(summary, "knowledge_corruption_rate") == (
        "| knowledge_corruption_rate | 0.0000 | — (skipped) |"
    )
    assert (
        _row(summary, "injection_compliance_rate") == "| injection_compliance_rate | 0.5000 | — |"
    )
    assert "knowledge_corruption_rate [defense=injection_filter] — skipped" in summary


def test_privacy_table_and_probe_line(tmp_path: Path) -> None:
    result = _result(
        tmp_path,
        _suite(
            "privacy",
            Metric(suite="privacy", name="leakage_rate", variant="defense=none", value=0.25),
            _missing("privacy", "retrieval_exposure_rate", "defense=none", "error"),
            Metric(suite="privacy", name="leakage_rate", variant="defense=pii_filter", value=0.0),
            Metric(suite="privacy", name="leakage_rate@direct", value=0.5),
            _missing("privacy", "leakage_rate@indirect", state="not_estimable"),
        ),
    )

    summary = render_summary(result)

    assert _row(summary, "none") == "| none | — (error) | 0.2500 |"
    assert _row(summary, "pii_filter") == "| pii_filter | — | 0.0000 |"
    assert "direct 0.50 · indirect — (not_estimable)" in summary
    assert "- leakage_rate@indirect — not_estimable: why leakage_rate@indirect" in summary


def test_reasons_are_kept_on_one_line(tmp_path: Path) -> None:
    metric = Metric(
        suite="faithfulness",
        name="groundedness",
        value=None,
        state="error",
        reason="judge\nfailed  twice",
    )
    summary = render_summary(_result(tmp_path, _suite("faithfulness", metric)))

    assert "- groundedness — error: judge failed twice" in summary
    assert describe(metric) == "groundedness=— (error: judge failed twice)"


def test_describe_for_the_cli() -> None:
    assert describe(Metric(suite="s", name="mrr", value=0.25)) == "mrr=0.250"
    assert describe(_missing("s", "mrr", state="skipped")) == "mrr=— (skipped: why mrr)"


def test_bars_draw_only_measured_values_and_label_the_rest() -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    _bars(
        ax,
        [0.0, 1.0, 2.0],
        [Metric(suite="s", name="a", value=0.0), _missing("s", "b", state="error"), None],
        width=0.4,
    )
    heights = [patch.get_height() for patch in ax.patches]
    texts = [(text.get_position()[0], text.get_text()) for text in ax.texts]
    plt.close(fig)

    assert heights == [0.0]  # the measured zero is still a (zero-height) bar
    assert texts == [(1.0, "error")]  # the unmeasured one is named, not drawn


def test_write_report_with_unmeasured_metrics_writes_every_artifact(tmp_path: Path) -> None:
    result = _result(
        tmp_path,
        _suite(
            "retrieval",
            Metric(suite="retrieval", name="mrr", variant="rerank=off", value=0.25),
            _missing("retrieval", "mrr", "rerank=on"),
        ),
        _suite(
            "security",
            _missing("security", "knowledge_corruption_rate", "defense=none"),
            Metric(
                suite="security",
                name="knowledge_corruption_rate",
                variant="defense=prompt_isolation",
                value=0.1,
            ),
        ),
        _suite(
            "privacy",
            _missing("privacy", "leakage_rate", "defense=none"),
            Metric(
                suite="privacy", name="retrieval_exposure_rate", variant="defense=none", value=1.0
            ),
        ),
    )

    written = write_report(result, tmp_path / "out")

    assert sorted(p.name for p in written) == [
        "privacy.png",
        "results.json",
        "retrieval.png",
        "security.png",
        "summary.md",
    ]


def test_a_plot_with_nothing_measured_is_not_written(tmp_path: Path) -> None:
    result = _result(
        tmp_path,
        _suite(
            "retrieval",
            _missing("retrieval", "mrr", "rerank=off"),
            _missing("retrieval", "mrr", "rerank=on"),
        ),
        _suite("privacy", _missing("privacy", "leakage_rate", "defense=none")),
    )

    written = write_report(result, tmp_path / "out")

    assert sorted(p.name for p in written) == ["results.json", "summary.md"]
    summary = (tmp_path / "out" / "summary.md").read_text(encoding="utf-8")
    table = [line for line in summary.splitlines() if line.startswith("| ")]
    assert not any(NUMBER.search(line) for line in table)
