from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace

import pytest

import crucible.index.factory as index_factory
import crucible.ingest.build as build_module
from crucible.config import ChunkerConfig
from crucible.ingest.build import (
    _collection_name,
    chunk_documents,
    embed_chunks,
    embed_into_index,
    load_or_build_index,
)
from crucible.providers import EmbedInputType, EmbedResult, Usage
from crucible.types import Chunk, DocMeta, Document, chunk_id_for, doc_id_for

from ...conftest import make_fake_spec


def _chunk(number: int) -> Chunk:
    text = f"chunk number {number}"
    doc_id = "doc-id"
    return Chunk(
        chunk_id=chunk_id_for(doc_id, number * 20, number * 20 + len(text)),
        doc_id=doc_id,
        source="doc.txt",
        text=text,
        start=number * 20,
        end=number * 20 + len(text),
    )


class RecordingEmbedder:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], EmbedInputType]] = []

    async def embed(self, texts: Sequence[str], *, input_type: EmbedInputType) -> EmbedResult:
        self.calls.append((list(texts), input_type))
        return EmbedResult(
            vectors=[[float(i + 1), 1.0] for i in range(len(texts))],
            model="recording",
            dim=2,
            usage=Usage(),
        )


def test_chunk_documents_flattens_chunks_in_document_order() -> None:
    texts = ["first document with enough text", "second document with enough text"]
    documents = [
        Document(
            doc_id=doc_id_for(f"{i}.txt", text),
            source=f"{i}.txt",
            text=text,
            meta=DocMeta(filetype="txt"),
        )
        for i, text in enumerate(texts)
    ]

    chunks = chunk_documents(
        documents, ChunkerConfig(type="fixed", size_tokens=20, overlap_tokens=0)
    )

    assert [chunk.source for chunk in chunks] == ["0.txt", "1.txt"]


async def test_embed_chunks_batches_and_uses_document_input_type() -> None:
    chunks = [_chunk(i) for i in range(33)]
    embedder = RecordingEmbedder()

    items = await embed_chunks(chunks, embedder)

    assert [len(call[0]) for call in embedder.calls] == [32, 1]
    assert all(call[1] is EmbedInputType.DOCUMENT for call in embedder.calls)
    assert [item.chunk for item in items] == chunks


async def test_embed_chunks_rejects_an_empty_index() -> None:
    with pytest.raises(ValueError, match="zero chunks"):
        await embed_chunks([], RecordingEmbedder())


async def test_embed_into_index_returns_searchable_faiss_index() -> None:
    chunks = [_chunk(0), _chunk(1)]
    index = await embed_into_index(chunks, RecordingEmbedder())

    assert index.dim == 2
    assert await index.count() == 2


def test_collection_name_is_stable_and_namespaced(tmp_path) -> None:
    spec = make_fake_spec(tmp_path, name="example")

    assert _collection_name(spec) == f"crucible_example_{spec.ingest_fingerprint()[:8]}"


async def test_load_or_build_index_reuses_matching_saved_index(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = make_fake_spec(tmp_path, name="reuse")
    directory = tmp_path / "indexes" / "reuse"
    directory.mkdir(parents=True)
    (directory / "meta.json").write_text("{}", encoding="utf-8")
    saved_index = object()
    builds: list[object] = []
    monkeypatch.setattr(build_module, "index_dir_for", lambda name: directory)
    monkeypatch.setattr(
        index_factory,
        "open_saved_index",
        lambda path: (saved_index, SimpleNamespace(fingerprint=spec.ingest_fingerprint())),
    )

    async def record_build(spec_arg, directory_arg) -> None:  # type: ignore[no-untyped-def]
        builds.append((spec_arg, directory_arg))

    monkeypatch.setattr(build_module, "build_index", record_build)

    assert await load_or_build_index(spec) is saved_index
    assert builds == []


async def test_load_or_build_index_rebuilds_stale_index(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = make_fake_spec(tmp_path, name="stale")
    directory = tmp_path / "indexes" / "stale"
    directory.mkdir(parents=True)
    (directory / "meta.json").write_text("{}", encoding="utf-8")
    rebuilt_index = object()
    opens = iter(
        [
            (object(), SimpleNamespace(fingerprint="old")),
            (rebuilt_index, SimpleNamespace(fingerprint=spec.ingest_fingerprint())),
        ]
    )
    builds: list[tuple[object, object]] = []
    monkeypatch.setattr(build_module, "index_dir_for", lambda name: directory)
    monkeypatch.setattr(index_factory, "open_saved_index", lambda path: next(opens))

    async def record_build(spec_arg, directory_arg) -> None:  # type: ignore[no-untyped-def]
        builds.append((spec_arg, directory_arg))

    monkeypatch.setattr(build_module, "build_index", record_build)

    assert await load_or_build_index(spec) is rebuilt_index
    assert builds == [(spec, directory)]
