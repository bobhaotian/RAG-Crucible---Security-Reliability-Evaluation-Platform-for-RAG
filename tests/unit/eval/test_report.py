"""The report shows a metric that was not measured as its state and reason,
never as a number, a zero, or a bar."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, get_args

import matplotlib
import pytest
from matplotlib.colors import to_hex

from rag_crucible.eval import MetricState
from rag_crucible.eval.report import (
    _bars,
    describe_suite,
    format_value,
    render_summary,
    write_report,
)
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
    # the reason is markdown-escaped; the label is not
    assert "- leakage_rate@indirect — not_estimable: why leakage\\_rate@indirect" in summary


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
    assert describe_suite(_suite("faithfulness", metric)) == (
        "groundedness=— (error: judge failed twice) · 1 not measured (see summary.md)"
    )


def test_reasons_are_plain_text_in_markdown(tmp_path: Path) -> None:
    metric = Metric(
        suite="faithfulness",
        name="groundedness",
        value=None,
        state="error",
        reason="judge said **no** <b>x</b> [see](http://e.x) `code` & co_op ~~gone~~ \\ end",
    )
    summary = render_summary(_result(tmp_path, _suite("faithfulness", metric)))

    assert (
        "- groundedness — error: judge said \\*\\*no\\*\\* \\<b\\>x\\</b\\> "
        "\\[see\\](http://e.x) \\`code\\` \\& co\\_op \\~\\~gone\\~\\~ \\\\ end"
    ) in summary


def _ranked(
    variant: str, *values: float | None, state: MetricState = "unsupported"
) -> list[Metric]:
    names = ("recall@1", "recall@5", "ndcg@10", "mrr", "recall@10")
    return [
        Metric(suite="retrieval", name=n, variant=variant, value=v)
        if v is not None
        else Metric(
            suite="retrieval", name=n, variant=variant, value=None, state=state, reason="no labels"
        )
        for n, v in zip(names, values, strict=False)
    ]


def test_cli_line_shows_rerank_on_when_it_was_measured() -> None:
    suite = _suite("retrieval", *_ranked("rerank=off", 0.1, 0.2), *_ranked("rerank=on", 0.3, 0.4))
    assert describe_suite(suite) == "recall@1=0.300 · recall@5=0.400"


def test_cli_line_falls_back_to_rerank_off() -> None:
    no_reranker = _ranked("rerank=on", None, None, state="inapplicable")
    inapplicable = _suite("retrieval", *_ranked("rerank=off", 0.1, 0.2), *no_reranker)
    assert describe_suite(inapplicable) == (
        "recall@1=0.100 · recall@5=0.200 · 2 inapplicable (see summary.md)"
    )
    # a reranker-off run emits rerank=off only, which main printed as a blank line
    off_only = _suite("retrieval", *_ranked("rerank=off", 0.1, 0.2))
    assert describe_suite(off_only) == "recall@1=0.100 · recall@5=0.200"


def test_cli_line_gives_each_reason_once_and_counts_the_rest() -> None:
    unlabelled = _suite(
        "retrieval",
        *_ranked("rerank=off", None, None, None, None, None),
        *_ranked("rerank=on", None, None, None, None, None),
    )
    line = describe_suite(unlabelled)
    assert line == (
        "recall@1=— (unsupported: no labels) · recall@5=— (unsupported) · "
        "ndcg@10=— (unsupported) · mrr=— (unsupported) · 10 not measured (see summary.md)"
    )
    assert line.count("no labels") == 1


def test_cli_line_counts_inapplicable_apart_from_not_measured() -> None:
    suite = _suite(
        "retrieval",
        *_ranked("rerank=off", 0.1, None, None),
        *_ranked("rerank=on", None, None, None, state="inapplicable"),
    )
    assert describe_suite(suite).endswith(" · 2 not measured · 3 inapplicable (see summary.md)")


def test_cli_line_counts_arms_it_does_not_show() -> None:
    """The headline is the `none` arm; a defense arm that all errored still shows up."""
    suite = _suite(
        "security",
        Metric(
            suite="security", name="knowledge_corruption_rate", variant="defense=none", value=0.5
        ),
        _missing("security", "knowledge_corruption_rate", "defense=prompt_isolation", "error"),
        _missing("security", "injection_compliance_rate", "defense=prompt_isolation", "error"),
    )
    assert describe_suite(suite) == (
        "knowledge_corruption_rate=0.500 · 2 not measured (see summary.md)"
    )


def test_a_retrieval_metric_outside_the_rerank_variants_is_shown_as_measured(
    tmp_path: Path,
) -> None:
    result = _result(
        tmp_path, _suite("retrieval", Metric(suite="retrieval", name="mrr", value=0.25))
    )

    summary = render_summary(result)

    assert "- mrr: 0.2500" in summary
    assert "| mrr |" not in summary


def test_bars_draw_only_measured_values_and_label_the_rest() -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    _bars(
        ax,
        [0.0, 1.0, 2.0],
        [Metric(suite="s", name="a", value=0.0), _missing("s", "b", state="error"), None],
        width=0.4,
        color="C0",
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


def test_a_suite_with_nothing_measured_gets_a_placeholder_plot(
    tmp_path: Path, figures: dict[str, Any]
) -> None:
    result = _result(
        tmp_path,
        _suite(
            "retrieval",
            _missing("retrieval", "mrr", "rerank=off"),
            _missing("retrieval", "mrr", "rerank=on"),
        ),
        _suite(
            "security",
            _missing("security", "knowledge_corruption_rate", "defense=none"),
            _missing("security", "knowledge_corruption_rate", "defense=injection_filter", "error"),
        ),
        _suite("privacy", _missing("privacy", "leakage_rate", "defense=none")),
    )

    written = write_report(result, tmp_path / "out")

    assert sorted(p.name for p in written) == [
        "privacy.png",
        "results.json",
        "retrieval.png",
        "security.png",
        "summary.md",
    ]
    expected = {
        "Retrieval quality": "nothing measured: unsupported (2)",
        "Attack success by defense": "nothing measured: unsupported (1) · error (1)",
        "Canary leakage by condition": "nothing measured: unsupported (1)",
    }
    for title, line in expected.items():
        ax = figures[f"{title} — {result.name}"].axes[0]
        assert ax.texts[0].get_text() == line
        assert not ax.patches and not ax.axison  # no bars, no axes: nothing to read as a value
    summary = (tmp_path / "out" / "summary.md").read_text(encoding="utf-8")
    table = [line for line in summary.splitlines() if line.startswith("| ")]
    assert not any(NUMBER.search(line) for line in table)


def test_the_retrieval_plot_is_judged_on_the_metrics_it_would_draw(
    tmp_path: Path, figures: dict[str, Any]
) -> None:
    """A measured metric outside rerank on/off is not in the plot, so it does not make one."""
    result = _result(
        tmp_path,
        _suite(
            "retrieval",
            Metric(suite="retrieval", name="mrr", value=0.25),
            _missing("retrieval", "recall@1", "rerank=off"),
            _missing("retrieval", "recall@1", "rerank=on"),
        ),
    )

    write_report(result, tmp_path / "out")

    ax = figures[f"Retrieval quality — {result.name}"].axes[0]
    assert ax.texts[0].get_text() == "nothing measured: unsupported (2)"


@pytest.fixture
def figures(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """The figures write_report draws, by title, kept open for inspection."""
    import matplotlib.pyplot as plt

    kept: dict[str, Any] = {}
    close = plt.close
    monkeypatch.setattr(plt, "close", lambda fig: kept.setdefault(fig.axes[0].get_title(), fig))
    yield kept
    for fig in kept.values():
        close(fig)


def _bars_of(fig: Any) -> list[tuple[float, float]]:
    ax = fig.axes[0]
    return sorted(
        (round(p.get_x() + p.get_width() / 2, 6), round(p.get_height(), 6)) for p in ax.patches
    )


def test_a_missing_rerank_on_side_is_not_drawn_with_the_off_value(
    tmp_path: Path, figures: dict[str, Any]
) -> None:
    result = _result(
        tmp_path,
        _suite(
            "retrieval",
            Metric(suite="retrieval", name="mrr", variant="rerank=off", value=0.5),
            _missing("retrieval", "mrr", "rerank=on", "error"),
            Metric(suite="retrieval", name="recall@1", variant="rerank=off", value=0.25),
            Metric(suite="retrieval", name="recall@1", variant="rerank=on", value=0.75),
        ),
    )

    write_report(result, tmp_path / "out")

    fig = figures[f"Retrieval quality — {result.name}"]
    assert _bars_of(fig) == [(-0.2, 0.5), (0.8, 0.25), (1.2, 0.75)]
    assert [(t.get_position()[0], t.get_text()) for t in fig.axes[0].texts] == [(0.2, "error")]


def test_a_series_with_no_bar_keeps_its_own_legend_colour(
    tmp_path: Path, figures: dict[str, Any]
) -> None:
    result = _result(
        tmp_path,
        _suite(
            "retrieval",
            Metric(suite="retrieval", name="mrr", variant="rerank=off", value=0.5),
            _missing("retrieval", "mrr", "rerank=on"),
        ),
    )

    write_report(result, tmp_path / "out")

    legend = figures[f"Retrieval quality — {result.name}"].axes[0].get_legend()
    colours = {
        t.get_text(): to_hex(h.get_facecolor())
        for t, h in zip(legend.get_texts(), legend.legend_handles, strict=True)
    }
    assert colours == {"rerank off": to_hex("C0"), "rerank on": to_hex("C1")}


def test_state_labels_stay_inside_the_axes(tmp_path: Path, figures: dict[str, Any]) -> None:
    # The last slot holds only a not-measured metric, beyond every bar.
    result = _result(
        tmp_path,
        _suite(
            "security",
            Metric(suite="security", name="a_rate", variant="defense=none", value=0.5),
            Metric(suite="security", name="b_rate", variant="defense=none", value=0.5),
            _missing("security", "b_rate", "defense=injection_filter", "error"),
        ),
    )

    write_report(result, tmp_path / "out")

    fig = figures[f"Attack success by defense — {result.name}"]
    fig.canvas.draw()
    lo, hi = fig.axes[0].get_xlim()
    (text,) = fig.axes[0].texts
    assert lo <= text.get_position()[0] - 0.2 and text.get_position()[0] + 0.2 <= hi


def test_a_suite_that_ran_replaces_its_old_chart_and_an_absent_suite_is_left_alone(
    tmp_path: Path,
) -> None:
    out = tmp_path / "out"
    earlier = _result(
        tmp_path,
        _suite(
            "retrieval",
            Metric(suite="retrieval", name="mrr", variant="rerank=off", value=0.5),
            Metric(suite="retrieval", name="mrr", variant="rerank=on", value=0.6),
        ),
        _suite(
            "security",
            Metric(suite="security", name="a_rate", variant="defense=none", value=0.5),
        ),
    )
    write_report(earlier, out)
    old_retrieval = (out / "retrieval.png").read_bytes()
    old_security = (out / "security.png").read_bytes()

    # nothing measured for retrieval, and no security suite at all this time
    later = _result(
        tmp_path,
        _suite(
            "retrieval",
            _missing("retrieval", "mrr", "rerank=off"),
            _missing("retrieval", "mrr", "rerank=on"),
        ),
    )
    write_report(later, out)

    assert (out / "retrieval.png").read_bytes() != old_retrieval  # now the placeholder
    assert (out / "security.png").read_bytes() == old_security  # not this run's to touch


def test_the_report_deletes_nothing_in_a_users_folder(tmp_path: Path) -> None:
    """A run with no suites leaves every file alone, whatever its name or case."""
    out = tmp_path / "out"
    out.mkdir()
    mine = ["latency.png", "retrieval.png", "security.PNG", "Privacy.png", "notes.png"]
    for name in mine:
        (out / name).write_bytes(name.encode())

    write_report(_result(tmp_path), out)

    for name in mine:
        assert (out / name).read_bytes() == name.encode()

    # A folder that shares a plot's name, for a suite this run did not include.
    # (Separate directory: on a case-insensitive filesystem it would be Privacy.png.)
    other = tmp_path / "other"
    (other / "security.png").mkdir(parents=True)
    write_report(_result(tmp_path), other)
    assert (other / "security.png").is_dir()


def test_an_absent_rerank_on_side_is_not_drawn_with_the_off_value(
    tmp_path: Path, figures: dict[str, Any]
) -> None:
    result = _result(
        tmp_path,
        _suite(
            "retrieval",
            Metric(suite="retrieval", name="mrr", variant="rerank=off", value=0.5),
            # no rerank=on metric for mrr at all
            Metric(suite="retrieval", name="recall@1", variant="rerank=off", value=0.25),
            Metric(suite="retrieval", name="recall@1", variant="rerank=on", value=0.75),
        ),
    )

    write_report(result, tmp_path / "out")

    fig = figures[f"Retrieval quality — {result.name}"]
    assert _bars_of(fig) == [(-0.2, 0.5), (0.8, 0.25), (1.2, 0.75)]
    assert list(fig.axes[0].texts) == []


def _legend(fig: Any) -> dict[str, str]:
    legend = fig.axes[0].get_legend()
    return {
        t.get_text(): to_hex(h.get_facecolor())
        for t, h in zip(legend.get_texts(), legend.legend_handles, strict=True)
    }


def _bar_colours(fig: Any) -> set[str]:
    return {to_hex(p.get_facecolor()) for p in fig.axes[0].patches}


def test_security_series_keep_their_own_colours(tmp_path: Path, figures: dict[str, Any]) -> None:
    result = _result(
        tmp_path,
        _suite(
            "security",
            Metric(suite="security", name="a_rate", variant="defense=none", value=0.5),
            _missing("security", "a_rate", "defense=injection_filter", "error"),
            Metric(suite="security", name="a_rate", variant="defense=prompt_isolation", value=0.25),
        ),
    )

    write_report(result, tmp_path / "out")

    fig = figures[f"Attack success by defense — {result.name}"]
    assert _legend(fig) == {
        "none": to_hex("C0"),
        "injection_filter": to_hex("C1"),
        "prompt_isolation": to_hex("C2"),
    }
    assert _bar_colours(fig) == {to_hex("C0"), to_hex("C2")}


def test_privacy_series_keep_their_own_colours(tmp_path: Path, figures: dict[str, Any]) -> None:
    result = _result(
        tmp_path,
        _suite(
            "privacy",
            Metric(
                suite="privacy", name="retrieval_exposure_rate", variant="defense=none", value=1.0
            ),
            _missing("privacy", "leakage_rate", "defense=none", "not_estimable"),
        ),
    )

    write_report(result, tmp_path / "out")

    fig = figures[f"Canary leakage by condition — {result.name}"]
    assert _legend(fig) == {
        "retrieval exposure": to_hex("C0"),
        "generation leakage": to_hex("C1"),
    }
    assert _bar_colours(fig) == {to_hex("C0")}
