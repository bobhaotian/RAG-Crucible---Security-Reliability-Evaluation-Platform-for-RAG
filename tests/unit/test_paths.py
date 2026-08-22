from __future__ import annotations

import pytest

from crucible.paths import artifacts_dir, default_db_path, index_dir_for


def test_paths_respect_environment_overrides(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "custom-artifacts"
    database = tmp_path / "custom.db"
    monkeypatch.setenv("CRUCIBLE_ARTIFACTS_DIR", str(root))
    monkeypatch.setenv("CRUCIBLE_DB", str(database))

    assert artifacts_dir() == root
    assert index_dir_for("demo") == root / "indexes" / "demo"
    assert default_db_path() == database

    monkeypatch.delenv("CRUCIBLE_DB")
    assert default_db_path() == root / "crucible.db"
