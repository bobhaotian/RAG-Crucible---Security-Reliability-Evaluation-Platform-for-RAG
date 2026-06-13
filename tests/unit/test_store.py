"""Result store + job queue semantics."""

from __future__ import annotations

from pathlib import Path

import pytest

from crucible.config import RunSpec
from crucible.eval.types import EvalRunResult, Metric, RetrievalRecord, SuiteResult
from crucible.runner import DuplicateRunError, ResultStore, RunNotFoundError
from crucible.runner.ids import new_run_id

from ..conftest import make_fake_spec


@pytest.fixture
def store(tmp_path: Path) -> ResultStore:
    return ResultStore(tmp_path / "crucible.db")


def _spec(tmp_path: Path, name: str = "store-test") -> RunSpec:
    return make_fake_spec(tmp_path / "corpus", name=name)


def _result(spec: RunSpec) -> EvalRunResult:
    record = RetrievalRecord(
        qid="q1",
        question="?",
        first_hit_rank_initial=1,
        first_hit_rank_reranked=None,
        retrieved_initial=("c1", "c2"),
        retrieved_reranked=(),
    )
    suite = SuiteResult(
        suite="retrieval",
        metrics=(Metric(suite="retrieval", name="mrr", variant="rerank=off", value=0.5),),
        records=(record,),
    )
    return EvalRunResult(
        name=spec.name,
        spec_hash=spec.spec_hash(),
        seed=spec.seed,
        started_at="2026-06-12T00:00:00+00:00",
        finished_at="2026-06-12T00:00:01+00:00",
        suites=(suite,),
        stage_stats=(),
        spec=spec,
    )


def test_submit_claim_lifecycle(store: ResultStore, tmp_path: Path) -> None:
    run_id = store.submit_run(_spec(tmp_path))
    assert store.get_run(run_id).status == "pending"

    claimed = store.claim_next("w1")
    assert claimed is not None and claimed.id == run_id
    assert store.get_run(run_id).status == "running"
    assert store.get_run(run_id).claimed_by == "w1"
    assert store.claim_next("w2") is None  # nothing else queued

    store.mark_succeeded(run_id)
    row = store.get_run(run_id)
    assert row.status == "succeeded" and row.finished_at is not None


def test_duplicate_spec_requires_force(store: ResultStore, tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    first = store.submit_run(spec)
    with pytest.raises(DuplicateRunError) as excinfo:
        store.submit_run(spec)
    assert excinfo.value.existing_run_id == first
    second = store.submit_run(spec, force=True)
    assert second != first
    # a failed run does not block resubmission
    store.claim_next("w")
    store.claim_next("w")
    store.mark_failed(first, "boom")
    store.mark_failed(second, "boom")
    assert store.submit_run(spec)


def test_claim_is_fifo(store: ResultStore, tmp_path: Path) -> None:
    first = store.submit_run(_spec(tmp_path, name="run-a"))
    second = store.submit_run(_spec(tmp_path, name="run-b"))
    claimed_first = store.claim_next("w")
    claimed_second = store.claim_next("w")
    assert claimed_first is not None and claimed_first.id == first
    assert claimed_second is not None and claimed_second.id == second


def test_save_and_read_results(store: ResultStore, tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    run_id = store.submit_run(spec)
    store.claim_next("w")
    store.save_result(run_id, _result(spec))
    store.mark_succeeded(run_id)

    results = store.get_results(run_id)
    assert results.run.status == "succeeded"
    assert results.suites[0].suite == "retrieval"
    assert results.suites[0].record_count == 1
    assert results.metrics == [
        Metric(suite="retrieval", name="mrr", variant="rerank=off", value=0.5)
    ]

    records = store.get_records(run_id, suite="retrieval")
    assert len(records) == 1
    assert records[0].kind == "retrieval"
    roundtrip = RetrievalRecord.model_validate_json(records[0].payload_json)
    assert roundtrip.qid == "q1"


def test_records_pagination(store: ResultStore, tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    run_id = store.submit_run(spec)
    base = _result(spec)
    many = base.model_copy(
        update={
            "suites": (base.suites[0].model_copy(update={"records": base.suites[0].records * 5}),)
        }
    )
    store.save_result(run_id, many)
    page_one = store.get_records(run_id, limit=2, offset=0)
    page_two = store.get_records(run_id, limit=2, offset=2)
    assert len(page_one) == 2 and len(page_two) == 2
    assert {r.id for r in page_one}.isdisjoint({r.id for r in page_two})


def test_cancel_only_pending(store: ResultStore, tmp_path: Path) -> None:
    run_id = store.submit_run(_spec(tmp_path))
    assert store.cancel_run(run_id) is True
    assert store.get_run(run_id).status == "cancelled"

    second = store.submit_run(_spec(tmp_path), force=True)
    store.claim_next("w")
    assert store.cancel_run(second) is False  # already running


def test_unknown_run_raises(store: ResultStore) -> None:
    with pytest.raises(RunNotFoundError):
        store.get_run("NOPE")
    with pytest.raises(RunNotFoundError):
        store.get_records("NOPE")


def test_run_ids_sort_by_time_and_are_unique() -> None:
    ids = [new_run_id() for _ in range(200)]
    assert len(set(ids)) == 200
    assert all(len(run_id) == 26 for run_id in ids)
