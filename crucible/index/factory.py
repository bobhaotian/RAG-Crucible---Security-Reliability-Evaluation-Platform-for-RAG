"""Vector-store selection: open a saved index regardless of backend.

A saved index is always a directory with a ``meta.json``; ``meta.store`` says
which backend owns the vectors. FAISS keeps everything on disk; Qdrant keeps
vectors server-side and ``meta.json`` is just the pointer (collection + url).
``connect_qdrant`` is the single seam tests monkeypatch to inject an in-memory
client, so the Qdrant build/open/query path is exercised without a server.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from crucible.index.base import VectorIndex
from crucible.index.faiss_index import FaissIndex, IndexMeta

DEFAULT_QDRANT_URL = "http://localhost:6333"


def qdrant_url() -> str:
    return os.environ.get("QDRANT_URL", DEFAULT_QDRANT_URL)


def connect_qdrant(location: str) -> Any:
    """Open a QdrantClient. ``location`` is a URL or ``:memory:``. The one place
    a client is created, so tests can patch it to share an in-memory instance."""
    try:
        from qdrant_client import QdrantClient
    except ImportError as exc:  # pragma: no cover - exercised via the registry path
        raise RuntimeError(
            "the qdrant store needs the qdrant extra: `uv sync --extra qdrant`"
        ) from exc
    if location == ":memory:":
        return QdrantClient(location=":memory:")
    return QdrantClient(url=location)


def read_meta(directory: Path) -> IndexMeta:
    meta_path = directory / "meta.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"no index at {directory} (run `crucible ingest` first)")
    return IndexMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))


def open_saved_index(directory: Path) -> tuple[VectorIndex, IndexMeta]:
    """Reopen an index saved at ``directory``, choosing the backend from meta."""
    meta = read_meta(directory)
    if meta.store == "qdrant":
        from crucible.index.qdrant_index import QdrantIndex

        assert meta.collection is not None
        client = connect_qdrant(qdrant_url())
        return QdrantIndex(client, meta.collection, meta.dim), meta
    index, _ = FaissIndex.load(directory)
    return index, meta
