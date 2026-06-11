"""Core data contracts shared across modules.

These models are the dependency root alongside ``crucible.config``: any module
may import them, they import nothing internal. Identity rules:

- ``doc_id``  = sha1("{source}:{text}")[:16] over the loaded (pre-filter) text
- ``chunk_id`` = sha1("{doc_id}:{start}:{end}")[:16]

so the same corpus + chunker config always yields the same IDs, which is what
lets gold-passage labels, poisoned-chunk tracking, and canary tracking survive
re-indexing.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Base for all cross-module data: immutable, unknown keys are errors."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DocMeta(StrictModel):
    title: str | None = None
    filetype: str


class Document(StrictModel):
    doc_id: str
    source: str  # path relative to the corpus root, POSIX-style
    text: str
    meta: DocMeta


class Chunk(StrictModel):
    chunk_id: str
    doc_id: str
    source: str
    text: str
    start: int  # char offset into the (filtered) document text
    end: int
    section: str | None = None
    tags: tuple[str, ...] = ()


def doc_id_for(source: str, text: str) -> str:
    return hashlib.sha1(f"{source}:{text}".encode()).hexdigest()[:16]


def chunk_id_for(doc_id: str, start: int, end: int) -> str:
    return hashlib.sha1(f"{doc_id}:{start}:{end}".encode()).hexdigest()[:16]
