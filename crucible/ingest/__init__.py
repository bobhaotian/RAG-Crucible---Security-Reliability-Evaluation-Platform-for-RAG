"""Ingestion pipeline: loaders → filters → chunkers → index build."""

from crucible.ingest.build import (
    IngestReport,
    build_index,
    chunk_documents,
    embed_into_index,
    load_or_build_index,
)
from crucible.ingest.chunkers import chunk_document
from crucible.ingest.filters import FilterStats, apply_filters
from crucible.ingest.loaders import LoaderError, load_corpus, register_loader

__all__ = [
    "FilterStats",
    "IngestReport",
    "LoaderError",
    "apply_filters",
    "build_index",
    "chunk_document",
    "chunk_documents",
    "embed_into_index",
    "load_corpus",
    "load_or_build_index",
    "register_loader",
]
