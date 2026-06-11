"""Render an EvalRunResult to disk: results.json, summary.md, and plots.

The summary tables are the same ones the README quotes; the rerank-lift
column (on - off) is computed here so the headline report is explicit about
what the reranking stage buys.
"""

from __future__ import annotations

from pathlib import Path

from crucible.eval.types import EvalRunResult, SuiteResult


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
    if result.stage_stats:
        lines += _latency_table(result)
    return "\n".join(lines) + "\n"


def _suite(result: EvalRunResult, name: str) -> SuiteResult | None:
    return next((s for s in result.suites if s.suite == name), None)


def _retrieval_table(suite: SuiteResult) -> list[str]:
    names: list[str] = []
    for metric in suite.metrics:  # preserve emission order, dedupe across variants
        if metric.name not in names:
            names.append(metric.name)
    off = {m.name: m.value for m in suite.metrics if m.variant == "rerank=off"}
    on = {m.name: m.value for m in suite.metrics if m.variant == "rerank=on"}

    lines = ["## Retrieval", ""]
    if on:
        lines += [
            "| metric | rerank off | rerank on | lift |",
            "|---|---|---|---|",
        ]
        for name in names:
            lift = on[name] - off[name]
            lines.append(f"| {name} | {off[name]:.4f} | {on[name]:.4f} | {lift:+.4f} |")
    else:
        lines += ["| metric | value |", "|---|---|"]
        lines += [f"| {name} | {off[name]:.4f} |" for name in names]
    lines.append("")
    return lines


def _faithfulness_table(suite: SuiteResult) -> list[str]:
    lines = [
        "## Faithfulness",
        "",
        f"_{len(suite.records)} answers judged_",
        "",
        "| metric | value |",
        "|---|---|",
    ]
    lines += [f"| {m.name} | {m.value:.4f} |" for m in suite.metrics]
    lines.append("")
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


def _write_plots(result: EvalRunResult, out_dir: Path) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    written = []
    retrieval = _suite(result, "retrieval")
    if retrieval is not None:
        off = {m.name: m.value for m in retrieval.metrics if m.variant == "rerank=off"}
        on = {m.name: m.value for m in retrieval.metrics if m.variant == "rerank=on"}
        names = list(off)
        fig, ax = plt.subplots(figsize=(8, 4))
        x = range(len(names))
        if on:
            ax.bar([i - 0.2 for i in x], [off[n] for n in names], width=0.4, label="rerank off")
            ax.bar([i + 0.2 for i in x], [on[n] for n in names], width=0.4, label="rerank on")
            ax.legend()
        else:
            ax.bar(list(x), [off[n] for n in names], width=0.5)
        ax.set_xticks(list(x), names, rotation=30, ha="right")
        ax.set_ylim(0, 1.05)
        ax.set_title(f"Retrieval quality — {result.name}")
        fig.tight_layout()
        path = out_dir / "retrieval.png"
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
