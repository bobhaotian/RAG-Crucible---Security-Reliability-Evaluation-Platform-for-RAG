"""FAISS-backed VectorIndex (the zero-infra default).

Cosine similarity implemented as inner product over L2-normalized vectors on
``IndexFlatIP`` — exact search, which at evaluation-corpus scale beats any ANN
recall/complexity trade. A saved index is a directory:

    index.faiss   — the FAISS index
    chunks.jsonl  — one Chunk per line, in insertion (= FAISS id) order
    meta.json     — IndexMeta incl. the ingest fingerprint (staleness check)
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Sequence
from pathlib import Path

# faiss-cpu and torch each bundle their own libomp on macOS; loading both in
# one process aborts with "duplicate OpenMP runtime" depending on
# initialization order. Two defensive measures, both required:
#   1. allow the duplicate runtime (the documented risk — silently wrong
#      parallel results — is neutralized by 2.);
#   2. import torch first and cap faiss to a single thread: IndexFlat search
#      is exact and tiny at evaluation-corpus scale, so OpenMP parallelism in
#      faiss buys nothing here anyway.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
with contextlib.suppress(ImportError):
    import torch  # noqa: F401

import faiss
import numpy as np
import numpy.typing as npt

from crucible.config import ChunkerConfig, ProviderRef
from crucible.index.base import IndexItem, SearchHit
from crucible.types import Chunk, StrictModel

faiss.omp_set_num_threads(1)


class IndexMeta(StrictModel):
    embedder: ProviderRef
    chunker: ChunkerConfig
    dim: int
    metric: str
    chunk_count: int
    fingerprint: str  # RunSpec.ingest_fingerprint() of the spec that built this
    built_at: str  # ISO-8601 UTC
    store: str = "faiss"
    collection: str | None = None  # qdrant collection name (None for faiss)


class IndexStaleError(Exception):
    """The on-disk index was built from a different ingest configuration."""


def _normalize(matrix: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return np.asarray(matrix / norms, dtype=np.float32)


class FaissIndex:
    def __init__(self, dim: int) -> None:
        self._dim = dim
        self._index: faiss.Index = faiss.IndexFlatIP(dim)
        self._chunks: list[Chunk] = []

    @property
    def dim(self) -> int:
        return self._dim

    async def add(self, items: Sequence[IndexItem]) -> None:
        if not items:
            return
        matrix = np.asarray([item.vector for item in items], dtype=np.float32)
        if matrix.shape[1] != self._dim:
            raise ValueError(f"vector dim {matrix.shape[1]} != index dim {self._dim}")
        self._index.add(_normalize(matrix))
        self._chunks.extend(item.chunk for item in items)

    async def search(self, vector: Sequence[float], k: int) -> list[SearchHit]:
        if not self._chunks:
            return []
        query = np.asarray([vector], dtype=np.float32)
        scores, ids = self._index.search(_normalize(query), min(k, len(self._chunks)))
        return [
            SearchHit(chunk=self._chunks[idx], score=float(score))
            for idx, score in zip(ids[0], scores[0], strict=True)
            if idx != -1
        ]

    async def count(self) -> int:
        return len(self._chunks)

    def save(self, directory: Path, meta: IndexMeta) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(directory / "index.faiss"))
        with (directory / "chunks.jsonl").open("w", encoding="utf-8") as fh:
            for chunk in self._chunks:
                fh.write(chunk.model_dump_json() + "\n")
        (directory / "meta.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> tuple[FaissIndex, IndexMeta]:
        meta_path = directory / "meta.json"
        if not meta_path.is_file():
            raise FileNotFoundError(f"no index at {directory} (run `crucible ingest` first)")
        meta = IndexMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
        instance = cls(meta.dim)
        instance._index = faiss.read_index(str(directory / "index.faiss"))
        with (directory / "chunks.jsonl").open(encoding="utf-8") as fh:
            instance._chunks = [Chunk.model_validate_json(line) for line in fh if line.strip()]
        if len(instance._chunks) != meta.chunk_count:
            raise ValueError(
                f"index at {directory} is corrupt: {len(instance._chunks)} chunks "
                f"on disk, meta says {meta.chunk_count}"
            )
        return instance, meta
