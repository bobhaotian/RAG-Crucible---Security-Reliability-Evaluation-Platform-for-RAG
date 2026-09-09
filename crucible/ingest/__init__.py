"""Ingestion pipeline: loaders → filters → chunkers → index build."""

from crucible.ingest.build import (
    IngestReport,
    build_index,
    chunk_documents,
    embed_into_index,
    load_ingest_report,
    load_or_build_index,
)
from crucible.ingest.chunkers import chunk_document
from crucible.ingest.filters import DroppedDocument, FilterStats, apply_filters
from crucible.ingest.loaders import LoaderError, SkippedFile, load_corpus, register_loader
from crucible.ingest.pii import contains_pii, redact_pii

__all__ = [
    "DroppedDocument",
    "FilterStats",
    "IngestReport",
    "LoaderError",
    "SkippedFile",
    "apply_filters",
    "build_index",
    "chunk_document",
    "chunk_documents",
    "contains_pii",
    "embed_into_index",
    "load_corpus",
    "load_ingest_report",
    "load_or_build_index",
    "redact_pii",
    "register_loader",
]
