"""Ingestion orchestrator: corpus directory → saved vector index.

This is the only index-build path in the project — the attack suites (Phase 4)
build their poisoned indexes through this exact function, so there is no
second ingestion code path to drift.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from crucible.config import ChunkerConfig, RunSpec
from crucible.index import FaissIndex, IndexItem, IndexMeta, VectorIndex
from crucible.ingest.chunkers import chunk_document
from crucible.ingest.filters import FilterStats, apply_filters
from crucible.ingest.loaders import load_corpus
from crucible.ingest.provenance import SourceChannel, assign_document_provenance
from crucible.paths import index_dir_for
from crucible.providers import Embedder, EmbedInputType, build_embedder
from crucible.types import Chunk, Document, StrictModel

_EMBED_BATCH_SIZE = 32


class IngestReport(StrictModel):
    docs_loaded: int
    files_skipped: int
    filter_stats: list[FilterStats]
    docs_indexed: int
    chunks: int
    dim: int
    duration_s: float


def chunk_documents(
    docs: list[Document],
    chunker: ChunkerConfig,
    *,
    source_channel: SourceChannel = "trusted_corpus",
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for doc in docs:
        assigned_doc = assign_document_provenance(doc, source_channel)
        chunks.extend(chunk_document(assigned_doc, chunker))
    return chunks


async def embed_chunks(chunks: list[Chunk], embedder: Embedder) -> list[IndexItem]:
    """Embed chunks (DOCUMENT input type) into IndexItems. The single embedding
    path shared by FAISS ingestion, the Qdrant build, and the security/privacy
    suites — so there is no second path to drift."""
    if not chunks:
        raise ValueError("cannot build an index from zero chunks")
    items: list[IndexItem] = []
    for batch_start in range(0, len(chunks), _EMBED_BATCH_SIZE):
        batch = chunks[batch_start : batch_start + _EMBED_BATCH_SIZE]
        result = await embedder.embed([c.text for c in batch], input_type=EmbedInputType.DOCUMENT)
        items.extend(
            IndexItem(chunk=chunk, vector=vector)
            for chunk, vector in zip(batch, result.vectors, strict=True)
        )
    return items


async def embed_into_index(chunks: list[Chunk], embedder: Embedder) -> FaissIndex:
    """Embed chunks into a fresh in-memory FAISS index (used by the eval suites
    that build ephemeral poisoned/canary indexes)."""
    items = await embed_chunks(chunks, embedder)
    index = FaissIndex(len(items[0].vector))
    await index.add(items)
    return index


async def build_index(spec: RunSpec, out_dir: Path) -> IngestReport:
    """Run the full ingestion pipeline for ``spec`` and persist the index at
    ``out_dir``. FAISS stores everything on disk; Qdrant stores vectors
    server-side and ``out_dir/meta.json`` is the pointer. Deterministic given
    the same corpus and spec."""
    started = time.perf_counter()
    docs, skipped = load_corpus(spec.corpus.documents)
    kept, filter_stats = apply_filters(docs, spec.ingest.filters)

    chunks = chunk_documents(kept, spec.ingest.chunker)
    if not chunks:
        raise ValueError(f"corpus at {spec.corpus.documents} produced no chunks")

    items = await embed_chunks(chunks, build_embedder(spec.pipeline.embedder))
    dim = len(items[0].vector)
    meta = IndexMeta(
        embedder=spec.pipeline.embedder,
        chunker=spec.ingest.chunker,
        dim=dim,
        metric=spec.index.metric,
        chunk_count=len(items),
        fingerprint=spec.ingest_fingerprint(),
        built_at=datetime.now(UTC).isoformat(timespec="seconds"),
        store=spec.index.store,
        collection=_collection_name(spec) if spec.index.store == "qdrant" else None,
    )

    if spec.index.store == "faiss":
        index = FaissIndex(dim)
        await index.add(items)
        index.save(out_dir, meta)
    else:  # qdrant: vectors live server-side; meta.json is the on-disk pointer
        from crucible.index.factory import connect_qdrant, qdrant_url
        from crucible.index.qdrant_index import QdrantIndex

        client = connect_qdrant(qdrant_url())
        assert meta.collection is not None
        if client.collection_exists(meta.collection):
            client.delete_collection(meta.collection)  # clean rebuild
        await QdrantIndex(client, meta.collection, dim).add(items)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "meta.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")

    return IngestReport(
        docs_loaded=len(docs),
        files_skipped=len(skipped),
        filter_stats=filter_stats,
        docs_indexed=len(kept),
        chunks=len(chunks),
        dim=dim,
        duration_s=round(time.perf_counter() - started, 3),
    )


def _collection_name(spec: RunSpec) -> str:
    return f"crucible_{spec.name}_{spec.ingest_fingerprint()[:8]}"


async def load_or_build_index(spec: RunSpec) -> VectorIndex:
    """Load the index at the conventional location for ``spec``; (re)build it
    first when missing or built from a different ingest configuration. The
    worker and API use this; the CLI keeps `crucible ingest` explicit."""
    from crucible.index.factory import open_saved_index

    directory = index_dir_for(spec.name)
    if (directory / "meta.json").is_file():
        index, meta = open_saved_index(directory)
        if meta.fingerprint == spec.ingest_fingerprint():
            return index
    await build_index(spec, directory)
    index, _ = open_saved_index(directory)
    return index
