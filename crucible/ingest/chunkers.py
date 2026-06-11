"""Chunkers: fixed-size-with-overlap and structure-aware (DESIGN.md §15 #10).

Both work in character offsets into the (filtered) document text — chunk text
is always exactly ``doc.text[start:end]`` — with the size budget expressed in
estimated tokens (~4 chars/token, see ``providers.base``). No tokenizer in the
core path keeps chunk identities deterministic across providers.

- ``fixed``: word-boundary-respecting windows with overlap.
- ``structure``: split at markdown headings (which HTML loaders also emit),
  carrying the heading path as the chunk's section label; oversized sections
  fall back to fixed splitting within the section; documents with no headings
  degrade to plain fixed chunking.
"""

from __future__ import annotations

import re

from crucible.config import ChunkerConfig
from crucible.providers.base import CHARS_PER_TOKEN
from crucible.types import Chunk, Document, chunk_id_for

_WORD_RE = re.compile(r"\S+")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def chunk_document(doc: Document, config: ChunkerConfig) -> list[Chunk]:
    size_chars = config.size_tokens * CHARS_PER_TOKEN
    overlap_chars = config.overlap_tokens * CHARS_PER_TOKEN
    spans: list[tuple[int, int, str | None]]
    if config.type == "fixed":
        spans = [(s, e, None) for s, e in _fixed_spans(doc.text, size_chars, overlap_chars)]
    else:
        spans = _structure_spans(doc.text, size_chars, overlap_chars)
    chunks: list[Chunk] = []
    for start, end, section in spans:
        text = doc.text[start:end]
        if not text.strip():
            continue
        chunks.append(
            Chunk(
                chunk_id=chunk_id_for(doc.doc_id, start, end),
                doc_id=doc.doc_id,
                source=doc.source,
                text=text,
                start=start,
                end=end,
                section=section,
            )
        )
    return chunks


def _fixed_spans(text: str, size_chars: int, overlap_chars: int) -> list[tuple[int, int]]:
    words = [(m.start(), m.end()) for m in _WORD_RE.finditer(text)]
    if not words:
        return []
    spans: list[tuple[int, int]] = []
    i = 0
    while i < len(words):
        start = words[i][0]
        j = i
        while j + 1 < len(words) and words[j + 1][1] - start <= size_chars:
            j += 1
        end = words[j][1]
        spans.append((start, end))
        if j + 1 >= len(words):
            break
        # Step the window back by the overlap, but always make progress.
        target = end - overlap_chars
        next_i = j + 1
        while next_i - 1 > i and words[next_i - 1][0] >= target:
            next_i -= 1
        i = max(next_i, i + 1)
    return spans


def _structure_spans(
    text: str, size_chars: int, overlap_chars: int
) -> list[tuple[int, int, str | None]]:
    sections = _split_sections(text)
    if not sections:
        return [(s, e, None) for s, e in _fixed_spans(text, size_chars, overlap_chars)]
    spans: list[tuple[int, int, str | None]] = []
    for start, end, label in sections:
        if end - start <= size_chars:
            spans.append((start, end, label))
        else:
            for sub_start, sub_end in _fixed_spans(text[start:end], size_chars, overlap_chars):
                spans.append((start + sub_start, start + sub_end, label))
    return spans


def _split_sections(text: str) -> list[tuple[int, int, str | None]]:
    """Contiguous (start, end, heading-path) slices, splitting at headings.
    Each section includes its own heading line. Returns [] if the document has
    no headings at all."""
    boundaries: list[tuple[int, int, str]] = []  # (offset, level, title)
    offset = 0
    for line in text.splitlines(keepends=True):
        match = _HEADING_RE.match(line.rstrip("\n"))
        if match:
            boundaries.append((offset, len(match.group(1)), match.group(2)))
        offset += len(line)
    if not boundaries:
        return []

    sections: list[tuple[int, int, str | None]] = []
    if boundaries[0][0] > 0:  # preamble before the first heading
        sections.append((0, boundaries[0][0], None))
    stack: list[tuple[int, str]] = []  # (level, title)
    for idx, (start, level, title) in enumerate(boundaries):
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        end = boundaries[idx + 1][0] if idx + 1 < len(boundaries) else len(text)
        sections.append((start, end, " › ".join(t for _, t in stack)))
    return sections
