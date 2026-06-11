"""VectorIndex contract: what the pipeline needs from any vector store.

Persistence (save/load) is deliberately not part of the protocol — FAISS
persists to local files while a server-backed store (Qdrant, Phase 6) persists
server-side; only the index factory deals in concrete types.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from crucible.types import Chunk, StrictModel


class IndexItem(StrictModel):
    chunk: Chunk
    vector: list[float]


class SearchHit(StrictModel):
    chunk: Chunk
    score: float


@runtime_checkable
class VectorIndex(Protocol):
    @property
    def dim(self) -> int: ...

    async def add(self, items: Sequence[IndexItem]) -> None: ...

    async def search(self, vector: Sequence[float], k: int) -> list[SearchHit]: ...

    async def count(self) -> int: ...
