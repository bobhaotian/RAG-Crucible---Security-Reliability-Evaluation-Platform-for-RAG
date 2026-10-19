"""Render an EvalRunResult to disk: results.json, summary.md, and plots.

The summary tables are the same ones the README quotes; the rerank-lift
column (on - off) is computed here so the headline report is explicit about
what the reranking stage buys.

A metric that was not measured is shown as what it is. Its table cell holds
its state, and each section lists the reasons under a "Not measured" heading.
It is never printed as a number or drawn as a bar of height zero, and a figure
derived from two metrics (the rerank lift) is given only when both were
measured. A metric the run did not emit at all is an em dash.

Plots are drawn from measured values only. When a suite ran but nothing in
its plot was measured, the plot is still written under its usual name, as a
placeholder that says so and counts the states. It replaces whatever chart an
earlier run left there, so the folder never holds a chart of numbers its
summary says were not measured. A plot for a suite this run did not include is
left untouched, as it always was: the report deletes nothing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from rag_crucible.eval.types import EvalRunResult, Metric, SuiteResult

# A metric the run did not emit. Distinct from one it emitted without a value,
# which carries its state, and from a measured zero, which is a number.
ABSENT = "—"


def format_value(metric: Metric | None, digits: int = 4) -> str:
    """A metric as a table cell: its value, ``— (<state>)`` when it was not
    measured, or an em dash when the run did not emit it."""
    if metric is None:
        return ABSENT
    if metric.value is None:
        return f"{ABSENT} ({metric.state})"
    return f"{metric.value:.{digits}f}"


def describe_suite(suite: SuiteResult, limit: int = 4) -> str:
    """The ``rag-crucible eval`` line for one suite: up to ``limit`` headline
    metrics, each distinct reason given once, then counts of every metric in
    the suite that was not measured, shown or not. ``inapplicable`` metrics are
    counted on their own: they do not apply to this configuration, which is not
    a gap in the measurement.

    Retrieval headlines are the rerank-on figures only when the suite measured
    at least one; otherwise rerank off. An ``inapplicable`` rerank-on metric
    (no reranker configured) is not a figure to show in its place.
    """
    rerank_on = any(m.variant == "rerank=on" and m.value is not None for m in suite.metrics)
    headline = ("", "rerank=on" if rerank_on else "rerank=off", "defense=none")
    explained: set[tuple[str, str]] = set()
    parts: list[str] = []
    for m in [m for m in suite.metrics if m.variant in headline][:limit]:
        if m.value is not None:
            parts.append(f"{m.name}={m.value:.3f}")
            continue
        key = (m.state, _one_line(m.reason))
        detail = m.state if key in explained else f"{m.state}: {key[1]}"
        explained.add(key)
        parts.append(f"{m.name}={ABSENT} ({detail})")
    missing = sum(m.value is None and m.state != "inapplicable" for m in suite.metrics)
    inapplicable = sum(m.state == "inapplicable" for m in suite.metrics)
    counts = [f"{missing} not measured"] if missing else []
    counts += [f"{inapplicable} inapplicable"] if inapplicable else []
    if counts:
        counts[-1] += " (see summary.md)"
    return " · ".join(parts + counts)


def _one_line(text: str | None) -> str:
    return " ".join((text or "").split())


# Characters that would make a reason render as emphasis, code, a link, an
# entity or raw HTML. A reason is plain text; a backslash keeps it that way.
_MARKDOWN = re.compile(r"([\\`*_\[\]<>~&])")


def _plain(text: str | None) -> str:
    return _MARKDOWN.sub(r"\\\1", _one_line(text))


def _not_measured(metrics: Iterable[Metric]) -> list[str]:
    """Why each metric in a section has no value, one line per distinct state
    and reason. Empty when everything was measured, so a fully measured report
    is unchanged by it."""
    grouped: dict[tuple[str, str], list[str]] = {}
    for m in metrics:
        if m.value is None:
            label = _label(m)
            grouped.setdefault((m.state, _plain(m.reason)), []).append(label)
    if not grouped:
        return []
    lines = ["Not measured:", ""]
    lines += [
        f"- {', '.join(labels)} — {state}: {reason}" for (state, reason), labels in grouped.items()
    ]
    lines.append("")
    return lines


def _lift(off: Metric | None, on: Metric | None) -> str:
    if off is None or on is None or off.value is None or on.value is None:
        return ABSENT  # a difference needs both sides measured
    return f"{on.value - off.value:+.4f}"


def write_report(result: EvalRunResult, out_dir: Path) -> list[Path]:
    """Write all artifacts; returns the paths written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = [out_dir / "results.json", out_dir / "summary.md"]
    written[0].write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    written[1].write_text(render_summary(result), encoding="utf-8")
    written += _write_plots(result, out_dir)
    return written


def render_summary(result: EvalRunResult) -> str:
    lines = [
        f"# Evaluation summary — `{result.name}`",
        "",
        f"- spec hash: `{result.spec_hash[:12]}` · seed: {result.seed}",
        f"- started {result.started_at} · finished {result.finished_at}",
        "",
    ]
    retrieval = _suite(result, "retrieval")
    if retrieval is not None:
        lines += _retrieval_table(retrieval)
    faithfulness = _suite(result, "faithfulness")
    if faithfulness is not None:
        lines += _faithfulness_table(faithfulness)
    security = _suite(result, "security")
    if security is not None:
        lines += _security_table(security)
    privacy = _suite(result, "privacy")
    if privacy is not None:
        lines += _privacy_table(privacy)
    if result.stage_stats:
        lines += _latency_table(result)
    return "\n".join(lines) + "\n"


def _suite(result: EvalRunResult, name: str) -> SuiteResult | None:
    return next((s for s in result.suites if s.suite == name), None)


def _retrieval_table(suite: SuiteResult) -> list[str]:
    ranked = [m for m in suite.metrics if m.variant in ("rerank=off", "rerank=on")]
    names: list[str] = []
    for metric in ranked:  # preserve emission order, dedupe across variants
        if metric.name not in names:
            names.append(metric.name)
    off = {m.name: m for m in ranked if m.variant == "rerank=off"}
    on = {m.name: m for m in ranked if m.variant == "rerank=on"}
    # No suite emits another variant today. Listed as itself rather than as an
    # empty table row, which would show a measured value as absent.
    other = [m for m in suite.metrics if m.variant not in ("rerank=off", "rerank=on")]

    lines = ["## Retrieval", ""]
    if on:
        lines += [
            "| metric | rerank off | rerank on | lift |",
            "|---|---|---|---|",
        ]
        for name in names:
            a, b = off.get(name), on.get(name)
            lines.append(f"| {name} | {format_value(a)} | {format_value(b)} | {_lift(a, b)} |")
        lines.append("")
    elif names:
        lines += ["| metric | value |", "|---|---|"]
        lines += [f"| {name} | {format_value(off.get(name))} |" for name in names]
        lines.append("")
    if other:
        lines += [f"- {_label(m)}: {format_value(m)}" for m in other]
        lines.append("")
    lines += _not_measured(suite.metrics)
    return lines


def _label(m: Metric) -> str:
    return f"{m.name} [{m.variant}]" if m.variant else m.name


def _faithfulness_table(suite: SuiteResult) -> list[str]:
    lines = [
        "## Faithfulness",
        "",
        f"_{len(suite.records)} answers judged_",
        "",
        "| metric | value |",
        "|---|---|",
    ]
    lines += [f"| {m.name} | {format_value(m)} |" for m in suite.metrics]
    lines.append("")
    lines += _not_measured(suite.metrics)
    return lines


def _security_table(suite: SuiteResult) -> list[str]:
    """Attack success with vs. without each defense — the headline numbers.
    Rows are attack-success metrics; columns are defense conditions."""
    success = {  # (metric_name, defense) -> metric
        (m.name, m.variant.removeprefix("defense=")): m
        for m in suite.metrics
        if m.variant.startswith("defense=")
    }
    defenses: list[str] = []
    for _, defense in success:
        if defense not in defenses:
            defenses.append(defense)
    success_names: list[str] = []
    for name, _ in success:
        if name not in success_names:
            success_names.append(name)
    retrieval = {m.name: m for m in suite.metrics if m.variant == ""}

    lines = ["## Security", ""]
    if retrieval:
        lines += [f"- {name}: {format_value(metric)}" for name, metric in retrieval.items()]
        lines.append("")
    if success_names:
        header = "| security/control rate | " + " | ".join(defenses) + " |"
        lines += [header, "|" + "---|" * (len(defenses) + 1)]
        for name in success_names:
            # A metric one defense did not emit is absent there, not a zero.
            cells = " | ".join(format_value(success.get((name, d))) for d in defenses)
            lines.append(f"| {name} | {cells} |")
        lines.append("")
    lines += _not_measured(suite.metrics)
    return lines


def _privacy_table(suite: SuiteResult) -> list[str]:
    """Canary leakage with vs. without redaction, decomposed into retrieval
    exposure and generation leakage, plus the per-probe-style breakdown."""
    by_defense: dict[str, dict[str, Metric]] = {}
    for m in suite.metrics:
        if m.variant.startswith("defense="):
            by_defense.setdefault(m.variant.removeprefix("defense="), {})[m.name] = m
    by_probe = {
        m.name.removeprefix("leakage_rate@"): m
        for m in suite.metrics
        if m.name.startswith("leakage_rate@")
    }

    lines = ["## Privacy", ""]
    if by_defense:
        lines += [
            "| condition | retrieval exposure | generation leakage |",
            "|---|---|---|",
        ]
        for defense, vals in by_defense.items():
            exposure = format_value(vals.get("retrieval_exposure_rate"))
            leakage = format_value(vals.get("leakage_rate"))
            lines.append(f"| {defense} | {exposure} | {leakage} |")
        lines.append("")
    if by_probe:
        lines.append(
            "Leakage by probe style (no redaction): "
            + " · ".join(f"{style} {format_value(m, 2)}" for style, m in by_probe.items())
        )
        lines.append("")
    lines += _not_measured(suite.metrics)
    return lines


def _latency_table(result: EvalRunResult) -> list[str]:
    lines = [
        "## Latency per stage",
        "",
        "| stage | count | mean ms | p50 ms | p95 ms |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {s.stage} | {s.count} | {s.mean_ms:.1f} | {s.p50_ms:.1f} | {s.p95_ms:.1f} |"
        for s in result.stage_stats
    ]
    lines.append("")
    return lines


def _bars(
    ax: Any,
    positions: Sequence[float],
    metrics: Sequence[Metric | None],
    *,
    width: float,
    color: str,
    label: str | None = None,
) -> None:
    """One series: bars for its measured metrics only, in the series' colour.

    A metric that was not measured gets its state written in its slot instead
    of a bar, and the slot is kept inside the axes. A metric the run did not
    emit gets nothing, so its empty slot looks the same as a measured zero (a
    bar of height 0). That ambiguity predates metric states; the summary's
    table tells the two apart.
    """
    drawn = [
        (x, m.value) for x, m in zip(positions, metrics, strict=True) if m and m.value is not None
    ]
    if drawn:
        ax.bar([x for x, _ in drawn], [v for _, v in drawn], width=width, label=label, color=color)
    elif label is not None:
        # With no bar to take its colour from, the legend would give this series
        # the first series' colour. A zero-size stand-in keeps its own and draws
        # nothing.
        from matplotlib.container import BarContainer
        from matplotlib.patches import Rectangle

        stand_in = Rectangle((0, 0), 0, 0, facecolor=color)
        ax.add_container(BarContainer([stand_in], label=label))
    for x, m in zip(positions, metrics, strict=True):
        if m is not None and m.value is None:
            # The slot a bar would occupy, so the label is not drawn off the axes.
            ax.update_datalim([(x - width / 2, 0.0), (x + width / 2, 0.0)])
            ax.text(
                x, 0.02, m.state, rotation=90, ha="center", va="bottom", fontsize=8, color="0.35"
            )


def _any_measured(metrics: Iterable[Metric | None]) -> bool:
    return any(m is not None and m.value is not None for m in metrics)


def _placeholder(
    plt: Any, path: Path, title: str, metrics: Iterable[Metric | None], figsize: tuple[int, int]
) -> None:
    """The plot for a suite that ran with nothing in it measured: no axes and
    no bars, just what happened, e.g. "nothing measured: unsupported (18)".
    Written under the plot's usual name, so it replaces an earlier run's chart."""
    states: dict[str, int] = {}
    for m in metrics:
        if m is not None:
            states[m.state] = states.get(m.state, 0) + 1
    detail = " · ".join(f"{state} ({n})" for state, n in states.items()) or "no metrics to plot"
    fig, ax = plt.subplots(figsize=figsize)
    ax.set_axis_off()
    ax.set_title(title)
    ax.text(0.5, 0.55, f"nothing measured: {detail}", ha="center", va="center", fontsize=12)
    ax.text(0.5, 0.4, "see summary.md for the reasons", ha="center", va="center", color="0.35")
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _write_plots(result: EvalRunResult, out_dir: Path) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    written = []
    retrieval = _suite(result, "retrieval")
    if retrieval is not None:
        off = {m.name: m for m in retrieval.metrics if m.variant == "rerank=off"}
        on = {m.name: m for m in retrieval.metrics if m.variant == "rerank=on"}
        names = list(off)
        off_bars = [off[n] for n in names]
        on_bars: list[Metric | None] = [on.get(n) for n in names] if on else []
        path = out_dir / "retrieval.png"
        title = f"Retrieval quality — {result.name}"
        if _any_measured(off_bars + on_bars):
            _retrieval_plot(plt, path, title, names, off_bars, on_bars if on else None)
        else:
            _placeholder(plt, path, title, off_bars + on_bars, figsize=(8, 4))
        written.append(path)

    security = _suite(result, "security")
    if security is not None:
        success = {
            (m.name, m.variant.removeprefix("defense=")): m
            for m in security.metrics
            if m.variant.startswith("defense=")
        }
        names = list(dict.fromkeys(n for n, _ in success))
        defenses = list(dict.fromkeys(d for _, d in success))
        path = out_dir / "security.png"
        if not (names and defenses and _any_measured(success.values())):
            title = f"Attack success by defense — {result.name}"
            _placeholder(plt, path, title, success.values(), figsize=(8, 4))
            written.append(path)
        else:
            fig, ax = plt.subplots(figsize=(8, 4))
            x = range(len(names))
            width = 0.8 / len(defenses)
            for j, defense in enumerate(defenses):
                offset = (j - (len(defenses) - 1) / 2) * width
                _bars(
                    ax,
                    [i + offset for i in x],
                    [success.get((n, defense)) for n in names],
                    width=width,
                    color=f"C{j % 10}",  # the default cycle's own order
                    label=defense,
                )
            ax.set_xticks(list(x), names, rotation=20, ha="right")
            ax.set_ylim(0, 1.05)
            ax.set_ylabel("attack success rate")
            ax.set_title(f"Attack success by defense — {result.name}")
            ax.legend()
            fig.tight_layout()
            fig.savefig(path, dpi=120)
            plt.close(fig)
            written.append(path)

    privacy = _suite(result, "privacy")
    if privacy is not None:
        by_defense: dict[str, dict[str, Metric]] = {}
        for m in privacy.metrics:
            if m.variant.startswith("defense="):
                by_defense.setdefault(m.variant.removeprefix("defense="), {})[m.name] = m
        shown = [
            vals.get(name)
            for vals in by_defense.values()
            for name in ("retrieval_exposure_rate", "leakage_rate")
        ]
        path = out_dir / "privacy.png"
        if not (by_defense and _any_measured(shown)):
            title = f"Canary leakage by condition — {result.name}"
            _placeholder(plt, path, title, shown, figsize=(7, 4))
            written.append(path)
        else:
            conditions = list(by_defense)
            fig, ax = plt.subplots(figsize=(7, 4))
            x = range(len(conditions))
            _bars(
                ax,
                [i - 0.2 for i in x],
                [by_defense[c].get("retrieval_exposure_rate") for c in conditions],
                width=0.4,
                color="C0",
                label="retrieval exposure",
            )
            _bars(
                ax,
                [i + 0.2 for i in x],
                [by_defense[c].get("leakage_rate") for c in conditions],
                width=0.4,
                color="C1",
                label="generation leakage",
            )
            ax.set_xticks(list(x), conditions)
            ax.set_ylim(0, 1.05)
            ax.set_ylabel("rate")
            ax.set_title(f"Canary leakage by condition — {result.name}")
            ax.legend()
            fig.tight_layout()
            fig.savefig(path, dpi=120)
            plt.close(fig)
            written.append(path)

    if result.stage_stats:
        stages = [s.stage for s in result.stage_stats]
        fig, ax = plt.subplots(figsize=(7, 4))
        x = range(len(stages))
        ax.bar([i - 0.2 for i in x], [s.p50_ms for s in result.stage_stats], 0.4, label="p50")
        ax.bar([i + 0.2 for i in x], [s.p95_ms for s in result.stage_stats], 0.4, label="p95")
        ax.set_xticks(list(x), stages)
        ax.set_ylabel("ms")
        ax.set_yscale("log")
        ax.set_title(f"Per-stage latency — {result.name}")
        ax.legend()
        fig.tight_layout()
        path = out_dir / "latency.png"
        fig.savefig(path, dpi=120)
        plt.close(fig)
        written.append(path)

    return written


def _retrieval_plot(
    plt: Any,
    path: Path,
    title: str,
    names: list[str],
    off_bars: list[Metric],
    on_bars: list[Metric | None] | None,
) -> None:
    fig, ax = plt.subplots(figsize=(8, 4))
    x = range(len(names))
    if on_bars is not None:
        _bars(ax, [i - 0.2 for i in x], off_bars, width=0.4, color="C0", label="rerank off")
        _bars(ax, [i + 0.2 for i in x], on_bars, width=0.4, color="C1", label="rerank on")
        ax.legend()
    else:
        _bars(ax, list(x), off_bars, width=0.5, color="C0")
    ax.set_xticks(list(x), names, rotation=30, ha="right")
    ax.set_ylim(0, 1.05)
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
