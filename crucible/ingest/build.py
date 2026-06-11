"""Ingestion orchestrator: corpus directory → saved vector index.

This is the only index-build path in the project — the attack suites (Phase 4)
build their poisoned indexes through this exact function, so there is no
second ingestion code path to drift.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from crucible.config import RunSpec
from crucible.index import FaissIndex, IndexItem, IndexMeta
from crucible.ingest.chunkers import chunk_document
from crucible.ingest.filters import FilterStats, apply_filters
from crucible.ingest.loaders import load_corpus
from crucible.providers import EmbedInputType, build_embedder
from crucible.types import Chunk, StrictModel

_EMBED_BATCH_SIZE = 32


class IngestReport(StrictModel):
    docs_loaded: int
    files_skipped: int
    filter_stats: list[FilterStats]
    docs_indexed: int
    chunks: int
    dim: int
    duration_s: float


async def build_index(spec: RunSpec, out_dir: Path) -> IngestReport:
    """Run the full ingestion pipeline for ``spec`` and save the index to
    ``out_dir``. Deterministic given the same corpus and spec."""
    if spec.index.store != "faiss":
        raise NotImplementedError("the qdrant adapter ships in Phase 6; use store: faiss")

    started = time.perf_counter()
    docs, skipped = load_corpus(spec.corpus.documents)
    kept, filter_stats = apply_filters(docs, spec.ingest.filters)

    chunks: list[Chunk] = []
    for doc in kept:
        chunks.extend(chunk_document(doc, spec.ingest.chunker))
    if not chunks:
        raise ValueError(f"corpus at {spec.corpus.documents} produced no chunks")

    embedder = build_embedder(spec.pipeline.embedder)
    index: FaissIndex | None = None
    for batch_start in range(0, len(chunks), _EMBED_BATCH_SIZE):
        batch = chunks[batch_start : batch_start + _EMBED_BATCH_SIZE]
        result = await embedder.embed([c.text for c in batch], input_type=EmbedInputType.DOCUMENT)
        if index is None:
            index = FaissIndex(result.dim)
        await index.add(
            [
                IndexItem(chunk=chunk, vector=vector)
                for chunk, vector in zip(batch, result.vectors, strict=True)
            ]
        )
    assert index is not None  # chunks is non-empty, so at least one batch ran

    meta = IndexMeta(
        embedder=spec.pipeline.embedder,
        chunker=spec.ingest.chunker,
        dim=index.dim,
        metric=spec.index.metric,
        chunk_count=await index.count(),
        fingerprint=spec.ingest_fingerprint(),
        built_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    index.save(out_dir, meta)

    return IngestReport(
        docs_loaded=len(docs),
        files_skipped=len(skipped),
        filter_stats=filter_stats,
        docs_indexed=len(kept),
        chunks=len(chunks),
        dim=index.dim,
        duration_s=round(time.perf_counter() - started, 3),
    )
