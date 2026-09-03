"""FAISS adapter: nearest-neighbor sanity, persistence roundtrip, staleness."""

from __future__ import annotations

from pathlib import Path

import pytest

from crucible.config import ChunkerConfig, ProviderRef
from crucible.index import FaissIndex, IndexItem, IndexMeta
from crucible.providers import EmbedInputType
from crucible.providers.fake import FakeEmbedder
from crucible.types import Chunk, Provenance, chunk_id_for


def _chunk(text: str, i: int) -> Chunk:
    return Chunk(
        chunk_id=chunk_id_for("doc0000000000000", i * 100, i * 100 + len(text)),
        doc_id="doc0000000000000",
        source="doc.md",
        text=text,
        start=i * 100,
        end=i * 100 + len(text),
        provenance=Provenance(source_type="trusted_corpus", verified=True, trust_score=1.0),
    )


TEXTS = [
    "the drone battery lasts eighteen hours in flight",
    "employees receive twenty days of paid vacation",
    "the rover reports a lidar calibration fault as error E-114",
]


async def _build_index() -> FaissIndex:
    embedder = FakeEmbedder()
    result = await embedder.embed(TEXTS, input_type=EmbedInputType.DOCUMENT)
    index = FaissIndex(result.dim)
    await index.add(
        [
            IndexItem(chunk=_chunk(text, i), vector=vector)
            for i, (text, vector) in enumerate(zip(TEXTS, result.vectors, strict=True))
        ]
    )
    return index


async def test_search_returns_most_similar_chunk_first() -> None:
    index = await _build_index()
    embedder = FakeEmbedder()
    query = await embedder.embed(["drone battery flight hours"], input_type=EmbedInputType.QUERY)
    hits = await index.search(query.vectors[0], k=3)
    assert len(hits) == 3
    assert hits[0].chunk.text == TEXTS[0]
    assert hits[0].score >= hits[1].score >= hits[2].score


async def test_k_larger_than_count_is_clamped() -> None:
    index = await _build_index()
    embedder = FakeEmbedder()
    query = await embedder.embed(["vacation"], input_type=EmbedInputType.QUERY)
    hits = await index.search(query.vectors[0], k=50)
    assert len(hits) == 3


async def test_save_load_roundtrip(tmp_path: Path) -> None:
    index = await _build_index()
    meta = IndexMeta(
        embedder=ProviderRef(provider="fake", model="hash-64"),
        chunker=ChunkerConfig(),
        dim=index.dim,
        metric="cosine",
        chunk_count=await index.count(),
        fingerprint="abc123",
        built_at="2026-06-10T00:00:00+00:00",
    )
    index.save(tmp_path / "idx", meta)

    loaded, loaded_meta = FaissIndex.load(tmp_path / "idx")
    assert loaded_meta == meta
    embedder = FakeEmbedder()
    query = await embedder.embed(["error E-114 lidar"], input_type=EmbedInputType.QUERY)
    original_hits = await index.search(query.vectors[0], k=2)
    loaded_hits = await loaded.search(query.vectors[0], k=2)
    assert [h.chunk.chunk_id for h in loaded_hits] == [h.chunk.chunk_id for h in original_hits]
    assert all(
        hit.chunk.provenance == original.chunk.provenance
        for hit, original in zip(loaded_hits, original_hits, strict=True)
    )


async def test_load_missing_index_is_actionable(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="crucible ingest"):
        FaissIndex.load(tmp_path / "nowhere")


async def test_dim_mismatch_rejected() -> None:
    index = FaissIndex(8)
    with pytest.raises(ValueError, match="dim"):
        await index.add([IndexItem(chunk=_chunk("text", 0), vector=[0.1] * 4)])
