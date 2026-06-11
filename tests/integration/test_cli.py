"""CLI smoke tests: ingest + query through Typer, exit codes and output."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from crucible.cli import app

from ..conftest import make_fake_spec

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


def test_version_runs() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
