"""End-to-end on the Qdrant store: build → persist pointer → reopen → query →
evaluate, all against one in-memory Qdrant client. Proves a spec with
``store: qdrant`` runs the whole pipeline unchanged, no server needed."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("qdrant_client")

from qdrant_client import QdrantClient

import crucible.index.factory as factory
from crucible.index import open_saved_index
from crucible.ingest import build_index, load_or_build_index
from crucible.pipeline import build_pipeline

from ..conftest import make_fake_spec


@pytest.fixture
def shared_qdrant(monkeypatch: pytest.MonkeyPatch) -> QdrantClient:
    """One in-memory client shared by build and reopen (the real flow uses two
    connections to the same server; in-memory state is per-client, so tests
    pin a single instance)."""
    client = QdrantClient(location=":memory:")
    monkeypatch.setattr(factory, "connect_qdrant", lambda _location: client)
    return client


def _qdrant_spec(tiny_corpus: Path):  # type: ignore[no-untyped-def]
    base = make_fake_spec(tiny_corpus, name="qdrant-e2e")
    return base.model_copy(update={"index": base.index.model_copy(update={"store": "qdrant"})})


async def test_build_persists_pointer_and_reopens(
    shared_qdrant: QdrantClient, tiny_corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CRUCIBLE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    spec = _qdrant_spec(tiny_corpus)

    report = await build_index(spec, tmp_path / "idx")
    assert report.chunks >= 3
    # only the pointer is on disk; vectors live in the (in-memory) server
    meta_text = (tmp_path / "idx" / "meta.json").read_text()
    assert '"store": "qdrant"' in meta_text
    assert not (tmp_path / "idx" / "index.faiss").exists()

    index, meta = open_saved_index(tmp_path / "idx")
    assert meta.store == "qdrant" and meta.collection is not None
    assert await index.count() == report.chunks


async def test_pipeline_and_eval_run_on_qdrant(
    shared_qdrant: QdrantClient, tiny_corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CRUCIBLE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    spec = _qdrant_spec(tiny_corpus)

    index = await load_or_build_index(spec)  # builds, then the pipeline queries it
    pipeline = build_pipeline(spec, index)
    answer = await pipeline.answer("What is the battery life of the Widget X1?")
    assert "72 hours" in answer.text
    assert answer.citations  # the Chunk payload round-tripped through Qdrant
