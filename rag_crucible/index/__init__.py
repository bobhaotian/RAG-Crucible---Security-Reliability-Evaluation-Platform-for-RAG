"""Vector store adapters behind the VectorIndex protocol."""

from rag_crucible.index.base import IndexItem, SearchHit, VectorIndex
from rag_crucible.index.factory import connect_qdrant, open_saved_index, qdrant_url
from rag_crucible.index.faiss_index import FaissIndex, IndexMeta, IndexStaleError

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
