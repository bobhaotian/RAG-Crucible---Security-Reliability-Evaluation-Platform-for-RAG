"""Qdrant-backed VectorIndex — the server option that proves the abstraction.

The point of this adapter is that the ``VectorIndex`` protocol isn't secretly
FAISS-shaped: the pipeline and eval suites work unchanged against a server-
backed store. Cosine similarity is configured on the collection; the Chunk
payload rides along in each point so search returns full chunks like FAISS does.

Construction takes a ``QdrantClient``, so tests use the client's in-memory mode
(``QdrantClient(":memory:")``) — real adapter behavior, no server. The index
factory builds a server client from the spec for ``store: qdrant``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from crucible.index.base import IndexItem, SearchHit
from crucible.types import Chunk


class QdrantIndex:
    def __init__(self, client: Any, collection: str, dim: int) -> None:
        from qdrant_client import models

        self._client = client
        self._collection = collection
        self._dim = dim
        if not client.collection_exists(collection):
            client.create_collection(
                collection_name=collection,
                vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
            )

    @property
    def dim(self) -> int:
        return self._dim

    async def add(self, items: Sequence[IndexItem]) -> None:
        if not items:
            return
        from qdrant_client import models

        points = [
            models.PointStruct(
                id=str(uuid.uuid4()),
                vector=item.vector,
                payload={"chunk": item.chunk.model_dump(mode="json")},
            )
            for item in items
        ]
        self._client.upsert(collection_name=self._collection, points=points)

    async def search(self, vector: Sequence[float], k: int) -> list[SearchHit]:
        hits = self._client.query_points(
            collection_name=self._collection, query=list(vector), limit=k, with_payload=True
        ).points
        return [
            SearchHit(chunk=Chunk.model_validate(hit.payload["chunk"]), score=float(hit.score))
            for hit in hits
        ]

    async def count(self) -> int:
        return int(self._client.count(collection_name=self._collection).count)
