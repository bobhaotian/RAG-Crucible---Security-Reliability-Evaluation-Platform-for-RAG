"""Vector store adapters behind the VectorIndex protocol."""

from crucible.index.base import IndexItem, SearchHit, VectorIndex
from crucible.index.faiss_index import FaissIndex, IndexMeta, IndexStaleError

__all__ = [
    "FaissIndex",
    "IndexItem",
    "IndexMeta",
    "IndexStaleError",
    "SearchHit",
    "VectorIndex",
]
