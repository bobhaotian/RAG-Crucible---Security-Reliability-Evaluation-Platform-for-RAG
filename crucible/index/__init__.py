"""Vector store adapters behind the VectorIndex protocol."""

from crucible.index.base import IndexItem, SearchHit, VectorIndex
from crucible.index.factory import connect_qdrant, open_saved_index, qdrant_url
from crucible.index.faiss_index import FaissIndex, IndexMeta, IndexStaleError

__all__ = [
    "FaissIndex",
    "IndexItem",
    "IndexMeta",
    "IndexStaleError",
    "SearchHit",
    "VectorIndex",
    "connect_qdrant",
    "open_saved_index",
    "qdrant_url",
]
