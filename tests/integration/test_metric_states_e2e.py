"""Metrics that could not be measured, produced by real runs.

Before B4's third step a run invented a zero (``mean([])``) or left a metric
out. These drive each case through ``run_eval`` and, for one, the result
store and the API, which is where a reader sees it.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from rag_crucible.api.main import create_app
from rag_crucible.config import (
    AttackKindConfig,
    FaithfulnessSuiteConfig,
    JudgeConfig,
    RetrievalSuiteConfig,
    RunSpec,
    SecuritySuiteConfig,
    SuitesConfig,
)
from rag_crucible.eval import EvalRunResult, run_eval
from rag_crucible.eval.report import describe_suite, render_summary
from rag_crucible.index import FaissIndex
from rag_crucible.ingest import build_index
from rag_crucible.runner import ResultStore

from ..conftest import make_fake_spec
from .test_eval_e2e import TINY_QA

UNLABELLED = [
    {"qid": "u001", "question": "What does the Widget X1 transmit over?"},
    {"qid": "u002", "question": "How fine is the Gadget Z9's temperature resolution?"},
]


def _spec(
    tiny_corpus: Path, tmp_path: Path, rows: list[dict[str, str]], suites: SuitesConfig
) -> RunSpec:
    qa_path = tmp_path / "qa.jsonl"
    qa_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    base = make_fake_spec(tiny_corpus, name="states")
    return base.model_copy(
        update={"corpus": base.corpus.model_copy(update={"qa": qa_path}), "suites": suites}
    )


async def _run(spec: RunSpec, tmp_path: Path) -> EvalRunResult:
    await build_index(spec, tmp_path / "index")
    index, _ = FaissIndex.load(tmp_path / "index")
    return await run_eval(spec, index)


async def test_a_partially_labelled_set_is_scored_over_its_labelled_questions(
    tiny_corpus: Path, tmp_path: Path
) -> None:
    suites = SuitesConfig(retrieval=RetrievalSuiteConfig(k_values=(1, 5)))
    result = await _run(_spec(tiny_corpus, tmp_path, TINY_QA + UNLABELLED, suites), tmp_path)

    suite = result.suites[0]
    assert suite.status == "succeeded" and suite.error is None
    assert {r.qid for r in suite.records} == {"t001", "t002", "t003"}  # unlabelled not run
    for metric in suite.metrics:
        assert metric.value is not None and (metric.n, metric.n_excluded) == (3, 2)
    # And it says so wherever it is read.
    assert "scored over 3 of 5; 2 excluded" in render_summary(result)
    assert "(3 of 5)" in describe_suite(suite)


async def test_an_unlabelled_set_skips_retrieval_and_reaches_the_api_unsupported(
    tiny_corpus: Path, tmp_path: Path
) -> None:
    suites = SuitesConfig(
        retrieval=RetrievalSuiteConfig(k_values=(1,)),
        faithfulness=FaithfulnessSuiteConfig(judge=JudgeConfig(kind="heuristic")),
    )
    spec = _spec(tiny_corpus, tmp_path, UNLABELLED, suites)
    result = await _run(spec, tmp_path)

    retrieval = next(s for s in result.suites if s.suite == "retrieval")
    assert retrieval.status == "skipped" and retrieval.error is None
    assert {m.state for m in retrieval.metrics} == {"unsupported"}
    faithfulness = next(s for s in result.suites if s.suite == "faithfulness")
    accuracy = next(m for m in faithfulness.metrics if m.name == "answer_accuracy")
    assert accuracy.state == "unsupported" and (accuracy.n, accuracy.n_excluded) == (0, 2)

    store = ResultStore(tmp_path / "crucible.db")
    run_id = store.submit_run(spec)
    store.save_result(run_id, result)
    store.mark_succeeded(run_id)
    client = TestClient(create_app(db_path=tmp_path / "crucible.db"))
    body = client.get(f"/runs/{run_id}/results").json()

    suites_by_name = {s["suite"]: s for s in body["suites"]}
    assert suites_by_name["retrieval"]["status"] == "skipped"
    assert suites_by_name["retrieval"]["error"] is None
    mrr = next(m for m in body["metrics"] if m["name"] == "mrr")
    assert mrr["value"] is None and mrr["state"] == "unsupported"
    assert (mrr["n"], mrr["n_excluded"]) == (0, 2)
    assert "no question carries a retrieval label" in mrr["reason"]


async def test_a_disabled_attack_is_skipped_not_absent(tiny_corpus: Path, tmp_path: Path) -> None:
    suites = SuitesConfig(
        security=SecuritySuiteConfig(
            poisoning=AttackKindConfig(targets=2),
            injection=AttackKindConfig(enabled=False),
            defenses=("none",),
            clean_control_sample=2,
        )
    )
    result = await _run(_spec(tiny_corpus, tmp_path, TINY_QA, suites), tmp_path)

    by_name = {(m.name, m.variant): m for m in result.suites[0].metrics}
    compliance = by_name[("injection_compliance_rate", "defense=none")]
    assert compliance.value is None and compliance.state == "skipped"
    assert compliance.reason == "injection attacks are disabled in this spec"
    corruption = by_name[("knowledge_corruption_rate", "defense=none")]
    assert corruption.value is not None and corruption.n == 2
