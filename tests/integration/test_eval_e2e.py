"""End-to-end evaluation on the fake provider: deterministic metrics,
rerank-lift variants, report artifacts, CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from crucible.cli import app
from crucible.config import (
    FaithfulnessSuiteConfig,
    JudgeConfig,
    RetrievalSuiteConfig,
    RunSpec,
    SuitesConfig,
)
from crucible.eval import EvalRunResult, run_eval
from crucible.eval.report import write_report
from crucible.index import FaissIndex
from crucible.ingest import build_index

from ..conftest import make_fake_spec

TINY_QA = [
    {
        "qid": "t001",
        "question": "What is the battery life of the Widget X1?",
        "answer": "72 hours",
        "gold_doc": "products/widget-spec.md",
        "gold_fact": "The X1 has a battery life of 72 hours.",
    },
    {
        "qid": "t002",
        "question": "How many images does the Gadget Z9 store?",
        "answer": "4000",
        "gold_doc": "products/gadget-spec.md",
        "gold_fact": "The Z9 stores 4000 images.",
    },
    {
        "qid": "t003",
        "question": "Within how many days can customers return a product?",
        "answer": "45 days",
        "gold_doc": "handbook/returns.txt",
        "gold_fact": "Customers may return any product within 45 days of delivery.",
    },
]


def _eval_spec(tiny_corpus: Path, tmp_path: Path, name: str = "eval-fake") -> RunSpec:
    qa_path = tmp_path / "qa.jsonl"
    qa_path.write_text("\n".join(json.dumps(row) for row in TINY_QA) + "\n", encoding="utf-8")
    base = make_fake_spec(tiny_corpus, name=name)
    return base.model_copy(
        update={
            "corpus": base.corpus.model_copy(update={"qa": qa_path}),
            "suites": SuitesConfig(
                retrieval=RetrievalSuiteConfig(k_values=(1, 3, 5), rerank_lift=True),
                faithfulness=FaithfulnessSuiteConfig(judge=JudgeConfig(kind="heuristic")),
                concurrency=3,  # exercise the parallel path; determinism test covers it
            ),
        }
    )


async def _run(spec: RunSpec, tmp_path: Path) -> EvalRunResult:
    index_dir = tmp_path / "index"
    if not (index_dir / "meta.json").is_file():
        await build_index(spec, index_dir)
    index, _ = FaissIndex.load(index_dir)
    return await run_eval(spec, index)


async def test_eval_produces_both_suites_with_variants(tiny_corpus: Path, tmp_path: Path) -> None:
    result = await _run(_eval_spec(tiny_corpus, tmp_path), tmp_path)

    assert {s.suite for s in result.suites} == {"retrieval", "faithfulness"}
    retrieval = next(s for s in result.suites if s.suite == "retrieval")
    variants = {m.variant for m in retrieval.metrics}
    assert variants == {"rerank=off", "rerank=on"}
    for variant in variants:
        recall_5 = result.metric("retrieval", "recall@5", variant)
        recall_1 = result.metric("retrieval", "recall@1", variant)
        assert recall_5 is not None and recall_1 is not None
        assert 0.0 <= recall_1 <= recall_5 <= 1.0  # monotone in k

    # the tiny corpus is easy: everything should be found by k=5
    assert result.metric("retrieval", "recall@5", "rerank=on") == 1.0
    assert len(retrieval.records) == len(TINY_QA)

    faithfulness = next(s for s in result.suites if s.suite == "faithfulness")
    names = {m.name for m in faithfulness.metrics}
    assert {"groundedness", "hallucination_rate", "answer_accuracy", "citation_parse_rate"} <= names
    accuracy = result.metric("faithfulness", "answer_accuracy")
    assert accuracy is not None and accuracy >= 2 / 3  # extractive stub finds the facts

    stages = {s.stage for s in result.stage_stats}
    assert {"embed_query", "retrieve", "rerank", "generate"} <= stages


async def test_eval_is_deterministic(tiny_corpus: Path, tmp_path: Path) -> None:
    spec = _eval_spec(tiny_corpus, tmp_path)
    first = await _run(spec, tmp_path)
    second = await _run(spec, tmp_path)
    assert first.suites == second.suites  # records and metrics, bit-for-bit


async def test_faithfulness_sampling_is_seeded(tiny_corpus: Path, tmp_path: Path) -> None:
    spec = _eval_spec(tiny_corpus, tmp_path)
    assert spec.suites is not None and spec.suites.faithfulness is not None
    sampled = spec.model_copy(
        update={
            "suites": SuitesConfig(
                faithfulness=FaithfulnessSuiteConfig(
                    judge=JudgeConfig(kind="heuristic"), sample_size=2
                )
            )
        }
    )
    first = await _run(sampled, tmp_path)
    second = await _run(sampled, tmp_path)
    qids = [r.qid for r in first.suites[0].records]
    assert len(qids) == 2
    assert qids == [r.qid for r in second.suites[0].records]


async def test_report_writes_json_summary_and_plots(tiny_corpus: Path, tmp_path: Path) -> None:
    result = await _run(_eval_spec(tiny_corpus, tmp_path), tmp_path)
    out = tmp_path / "report"
    written = write_report(result, out)

    assert (out / "results.json").is_file()
    assert (out / "summary.md").is_file()
    assert (out / "retrieval.png").is_file()
    assert (out / "latency.png").is_file()
    assert len(written) == 4

    roundtrip = EvalRunResult.model_validate_json(
        (out / "results.json").read_text(encoding="utf-8")
    )
    assert roundtrip == result  # spec + records survive serialization

    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "| metric | rerank off | rerank on | lift |" in summary
    assert "hallucination_rate" in summary
    assert "p95 ms" in summary


def test_cli_eval_smoke(tiny_corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    spec = _eval_spec(tiny_corpus, tmp_path, name="cli-eval")
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec.model_dump(mode="json")), encoding="utf-8")

    runner = CliRunner()
    assert runner.invoke(app, ["ingest", str(spec_path)]).exit_code == 0
    result = runner.invoke(app, ["eval", str(spec_path), "--out", "out"])
    assert result.exit_code == 0, result.output
    assert "retrieval:" in result.output
    assert Path("out/results.json").is_file()
