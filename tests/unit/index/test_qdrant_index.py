"""Qdrant adapter against the client's in-memory mode — real adapter behavior,
no server. Proves the VectorIndex protocol isn't FAISS-shaped."""

from __future__ import annotations

import pytest

pytest.importorskip("qdrant_client")

from qdrant_client import QdrantClient

from crucible.index import IndexItem
from crucible.index.qdrant_index import QdrantIndex
from crucible.providers import EmbedInputType
from crucible.providers.fake import FakeEmbedder
from crucible.types import Chunk, chunk_id_for

TEXTS = [
    "the drone battery lasts eighteen hours in flight",
    "employees receive twenty days of paid vacation",
    "the rover reports a lidar calibration fault as error E-114",
]


def _chunk(text: str, i: int) -> Chunk:
    return Chunk(
        chunk_id=chunk_id_for("d000000000000000", i, i + len(text)),
        doc_id="d000000000000000",
        source=f"doc{i}.md",
        text=text,
        start=i,
        end=i + len(text),
    )


async def _populated_index() -> QdrantIndex:
    embedder = FakeEmbedder()
    result = await embedder.embed(TEXTS, input_type=EmbedInputType.DOCUMENT)
    index = QdrantIndex(QdrantClient(location=":memory:"), "test", result.dim)
    await index.add(
        [
            IndexItem(chunk=_chunk(text, i), vector=vector)
            for i, (text, vector) in enumerate(zip(TEXTS, result.vectors, strict=True))
        ]
    )
    return index


async def test_search_returns_most_similar_chunk_with_payload() -> None:
    index = await _populated_index()
    assert await index.count() == 3
    embedder = FakeEmbedder()
    query = await embedder.embed(["drone battery flight hours"], input_type=EmbedInputType.QUERY)
    hits = await index.search(query.vectors[0], k=3)
    assert len(hits) == 3
    assert hits[0].chunk.text == TEXTS[0]  # full Chunk round-trips through the payload
    assert hits[0].score >= hits[1].score


async def test_empty_add_is_noop() -> None:
    index = QdrantIndex(QdrantClient(location=":memory:"), "empty", 8)
    await index.add([])
    assert await index.count() == 0
