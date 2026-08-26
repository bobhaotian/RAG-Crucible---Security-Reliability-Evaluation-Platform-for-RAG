"""CLI smoke tests: ingest + query through Typer, exit codes and output."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from crucible.cli import app
from crucible.runner import ResultStore

from ..conftest import make_fake_spec
from .test_eval_e2e import _eval_spec

runner = CliRunner()


@pytest.fixture
def spec_file(tiny_corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)  # artifacts/ lands in the test sandbox
    spec = make_fake_spec(tiny_corpus, name="cli-smoke")
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(spec.model_dump(mode="json")), encoding="utf-8")
    return path


def test_ingest_then_query(spec_file: Path) -> None:
    result = runner.invoke(app, ["ingest", str(spec_file)])
    assert result.exit_code == 0, result.output
    assert "chunks" in result.output
    assert "filter dedup" in result.output

    again = runner.invoke(app, ["ingest", str(spec_file)])
    assert again.exit_code == 0
    assert "up to date" in again.output

    query = runner.invoke(
        app, ["query", str(spec_file), "What is the battery life of the Widget X1?"]
    )
    assert query.exit_code == 0, query.output
    assert "A:" in query.output
    assert "Citations:" in query.output
    assert "Timings (ms):" in query.output


def test_query_without_index_is_actionable(spec_file: Path) -> None:
    result = runner.invoke(app, ["query", str(spec_file), "anything"])
    assert result.exit_code == 2
    assert "crucible ingest" in result.output


def test_invalid_spec_fails_with_field_name(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: x\nbogus_key: 1\n", encoding="utf-8")
    result = runner.invoke(app, ["ingest", str(bad)])
    assert result.exit_code == 2
    assert "bogus_key" in result.output


def test_submit_completes_run_and_writes_db_and_report(
    tiny_corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    spec = _eval_spec(tiny_corpus, tmp_path, name="cli-submit")
    spec_path = tmp_path / "submit.yaml"
    spec_path.write_text(yaml.safe_dump(spec.model_dump(mode="json")), encoding="utf-8")
    db_path = tmp_path / "crucible.db"

    submitted = runner.invoke(app, ["submit", str(spec_path), "--db", str(db_path)])
    assert submitted.exit_code == 0, submitted.output
    assert "running evaluation" in submitted.output
    assert "succeeded" in submitted.output

    rows = ResultStore(db_path).list_runs()
    assert len(rows) == 1 and rows[0].status == "succeeded"
    report_dir = tmp_path / "results" / spec.name / rows[0].id
    assert (report_dir / "results.json").is_file()
    assert (report_dir / "summary.md").is_file()


def test_submit_queue_only_returns_with_pending_run(
    tiny_corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    spec = _eval_spec(tiny_corpus, tmp_path, name="cli-queued")
    spec_path = tmp_path / "queued.yaml"
    spec_path.write_text(yaml.safe_dump(spec.model_dump(mode="json")), encoding="utf-8")
    db_path = tmp_path / "queued.db"

    submitted = runner.invoke(
        app,
        ["submit", str(spec_path), "--queue-only", "--db", str(db_path)],
    )
    assert submitted.exit_code == 0, submitted.output
    assert "a `crucible worker` must process this run" in submitted.output
    rows = ResultStore(db_path).list_runs()
    assert len(rows) == 1 and rows[0].status == "pending"
    assert not (tmp_path / "results" / spec.name / rows[0].id).exists()


def test_submit_completes_matching_run_already_pending(
    tiny_corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    spec = _eval_spec(tiny_corpus, tmp_path, name="cli-existing")
    spec_path = tmp_path / "existing.yaml"
    spec_path.write_text(yaml.safe_dump(spec.model_dump(mode="json")), encoding="utf-8")
    db_path = tmp_path / "existing.db"
    store = ResultStore(db_path)
    existing_id = store.submit_run(spec)

    submitted = runner.invoke(app, ["submit", str(spec_path), "--db", str(db_path)])
    assert submitted.exit_code == 0, submitted.output
    assert "attaching to existing pending run" in submitted.output
    assert store.get_run(existing_id).status == "succeeded"
    assert len(store.list_runs()) == 1
    assert (tmp_path / "results" / spec.name / existing_id / "results.json").is_file()


def test_version_runs() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
