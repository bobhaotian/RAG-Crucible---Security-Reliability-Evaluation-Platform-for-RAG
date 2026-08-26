"""Worker end-to-end: claim → build index → evaluate → persist + report, plus the
failure paths (broken corpus, partial suite failure)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crucible.config import RunSpec
from crucible.runner import ResultStore, worker_loop

from .test_eval_e2e import TINY_QA, _eval_spec


@pytest.fixture
def store(tmp_path: Path) -> ResultStore:
    return ResultStore(tmp_path / "crucible.db")


@pytest.fixture(autouse=True)
def _isolated_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRUCIBLE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CRUCIBLE_RESULTS_DIR", str(tmp_path / "results"))


async def test_worker_executes_submitted_run(
    store: ResultStore, tiny_corpus: Path, tmp_path: Path
) -> None:
    spec = _eval_spec(tiny_corpus, tmp_path, name="worker-e2e")
    run_id = store.submit_run(spec)

    processed = await worker_loop(store, worker_id="w-test", drain=True)
    assert processed == 1

    row = store.get_run(run_id)
    assert row.status == "succeeded", row.error
    results = store.get_results(run_id)
    assert {s.suite for s in results.suites} == {"retrieval", "faithfulness"}
    assert all(s.status == "succeeded" for s in results.suites)
    assert any(m.name == "recall@5" and m.variant == "rerank=on" for m in results.metrics)
    assert results.stage_stats  # warm-up happened, timings collected
    assert len(store.get_records(run_id, suite="retrieval")) == len(TINY_QA)

    report_dir = tmp_path / "results" / spec.name / run_id
    assert {path.name for path in report_dir.iterdir()} == {
        "latency.png",
        "results.json",
        "retrieval.png",
        "summary.md",
    }
    portable = json.loads((report_dir / "results.json").read_text(encoding="utf-8"))
    assert portable["spec_hash"] == spec.spec_hash()
    assert {suite["suite"] for suite in portable["suites"]} == {
        "retrieval",
        "faithfulness",
    }


async def test_worker_marks_broken_run_failed_and_survives(
    store: ResultStore, tiny_corpus: Path, tmp_path: Path
) -> None:
    broken = _eval_spec(tiny_corpus, tmp_path, name="worker-broken").model_copy(
        update={
            "corpus": _eval_spec(tiny_corpus, tmp_path).corpus.model_copy(
                update={"documents": tmp_path / "no-such-dir"}
            )
        }
    )
    healthy = _eval_spec(tiny_corpus, tmp_path, name="worker-healthy")
    broken_id = store.submit_run(broken)
    healthy_id = store.submit_run(healthy)

    processed = await worker_loop(store, drain=True)
    assert processed == 2

    failed = store.get_run(broken_id)
    assert failed.status == "failed"
    assert failed.error is not None and "no-such-dir" in failed.error
    assert store.get_run(healthy_id).status == "succeeded"


async def test_partial_suite_failure_keeps_completed_results(
    store: ResultStore, tiny_corpus: Path, tmp_path: Path
) -> None:
    """A run whose faithfulness judge cache is read-only-and-empty fails that
    suite, but retrieval results are persisted and the run is marked failed."""
    spec = _eval_spec(tiny_corpus, tmp_path, name="worker-partial")
    raw = json.loads(spec.canonical_json())
    raw["suites"]["faithfulness"]["judge"] = {
        "kind": "llm",
        "provider": "fake",
        "model": "extractive",
        "mode": "cached",  # empty cache → every judgment is a miss → suite fails
        "cache": str(tmp_path / "empty-cache.jsonl"),
    }
    run_id = store.submit_run(RunSpec.model_validate(raw))

    await worker_loop(store, drain=True)

    row = store.get_run(run_id)
    assert row.status == "failed"
    assert row.error is not None and "faithfulness" in row.error
    results = store.get_results(run_id)
    by_suite = {s.suite: s for s in results.suites}
    assert by_suite["retrieval"].status == "succeeded"
    assert by_suite["faithfulness"].status == "failed"
    assert any(m.suite == "retrieval" for m in results.metrics)  # evidence survived

    # Partial evidence is portable as well as queryable in SQLite.
    report_dir = tmp_path / "results" / spec.name / run_id
    portable = json.loads((report_dir / "results.json").read_text(encoding="utf-8"))
    statuses = {suite["suite"]: suite["status"] for suite in portable["suites"]}
    assert statuses == {"retrieval": "succeeded", "faithfulness": "failed"}
