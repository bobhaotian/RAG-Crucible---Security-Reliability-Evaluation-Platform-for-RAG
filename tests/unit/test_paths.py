from __future__ import annotations

from pathlib import Path

import pytest

from crucible.paths import (
    artifacts_dir,
    default_db_path,
    index_dir_for,
    results_dir,
    submitted_run_results_dir,
)


def test_paths_respect_environment_overrides(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "custom-artifacts"
    database = tmp_path / "custom.db"
    reports = tmp_path / "custom-results"
    monkeypatch.setenv("CRUCIBLE_ARTIFACTS_DIR", str(root))
    monkeypatch.setenv("CRUCIBLE_DB", str(database))
    monkeypatch.setenv("CRUCIBLE_RESULTS_DIR", str(reports))

    assert artifacts_dir() == root
    assert index_dir_for("demo") == root / "indexes" / "demo"
    assert default_db_path() == database
    assert results_dir() == reports
    assert submitted_run_results_dir("demo", "01RUN") == reports / "demo" / "01RUN"

    monkeypatch.delenv("CRUCIBLE_DB")
    assert default_db_path() == root / "crucible.db"

    monkeypatch.delenv("CRUCIBLE_RESULTS_DIR")
    assert results_dir() == Path("results")
