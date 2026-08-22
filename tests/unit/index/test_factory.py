from __future__ import annotations

import pytest

from crucible.index.factory import DEFAULT_QDRANT_URL, qdrant_url, read_meta


def test_qdrant_url_uses_default_and_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QDRANT_URL", raising=False)
    assert qdrant_url() == DEFAULT_QDRANT_URL

    monkeypatch.setenv("QDRANT_URL", ":memory:")
    assert qdrant_url() == ":memory:"


def test_read_meta_missing_index_has_actionable_error(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="crucible ingest"):
        read_meta(tmp_path / "missing")
