"""Chunker invariants: exact offsets, overlap, determinism, structure labels."""

from __future__ import annotations

from itertools import pairwise

from crucible.config import ChunkerConfig
from crucible.ingest import chunk_document
from crucible.types import DocMeta, Document, doc_id_for


def _doc(text: str, source: str = "doc.md") -> Document:
    return Document(
        doc_id=doc_id_for(source, text),
        source=source,
        text=text,
        meta=DocMeta(filetype="md"),
    )


def test_fixed_chunks_slice_exactly_and_overlap() -> None:
    text = " ".join(f"word{i:04d}" for i in range(400))
    doc = _doc(text)
    config = ChunkerConfig(type="fixed", size_tokens=50, overlap_tokens=10)
    chunks = chunk_document(doc, config)

    assert len(chunks) > 3
    for chunk in chunks:
        assert chunk.text == text[chunk.start : chunk.end]
        assert len(chunk.text) <= 50 * 4 + 8  # one word may straddle the budget
    assert chunks[0].start == 0
    assert chunks[-1].end == len(text)
    for prev, nxt in pairwise(chunks):
        assert nxt.start < prev.end  # windows overlap
        assert nxt.start > prev.start  # and always make progress


def test_fixed_chunking_is_deterministic() -> None:
    text = "alpha beta gamma " * 200
    config = ChunkerConfig(type="fixed", size_tokens=40, overlap_tokens=8)
    first = chunk_document(_doc(text), config)
    second = chunk_document(_doc(text), config)
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert [(c.start, c.end) for c in first] == [(c.start, c.end) for c in second]


def test_structure_chunker_labels_sections() -> None:
    text = (
        "Preamble line before any heading.\n\n"
        "# Title\n\nIntro paragraph.\n\n"
        "## Specs\n\nSpec sentence one. Spec sentence two.\n\n"
        "## Pricing\n\nPrice sentence.\n"
    )
    doc = _doc(text)
    chunks = chunk_document(doc, ChunkerConfig(type="structure", size_tokens=200))

    sections = [c.section for c in chunks]
    assert sections[0] is None  # preamble
    assert "Title" in sections
    assert "Title › Specs" in sections
    assert "Title › Pricing" in sections
    for chunk in chunks:
        assert chunk.text == text[chunk.start : chunk.end]


def test_structure_chunker_splits_oversized_sections() -> None:
    body = " ".join(f"filler{i}" for i in range(300))
    text = f"# Big\n\n{body}\n"
    config = ChunkerConfig(type="structure", size_tokens=50, overlap_tokens=10)
    chunks = chunk_document(_doc(text), config)
    assert len(chunks) > 2
    assert all(c.section == "Big" for c in chunks)


def test_structure_chunker_falls_back_without_headings() -> None:
    text = "Just plain text. " * 100
    fixed = chunk_document(
        _doc(text), ChunkerConfig(type="fixed", size_tokens=50, overlap_tokens=10)
    )
    structured = chunk_document(
        _doc(text), ChunkerConfig(type="structure", size_tokens=50, overlap_tokens=10)
    )
    assert [(c.start, c.end) for c in structured] == [(c.start, c.end) for c in fixed]
    assert all(c.section is None for c in structured)


def test_chunk_ids_depend_on_doc_and_span() -> None:
    text = "some words here " * 50
    chunks_a = chunk_document(_doc(text, "a.md"), ChunkerConfig(size_tokens=30, overlap_tokens=6))
    chunks_b = chunk_document(_doc(text, "b.md"), ChunkerConfig(size_tokens=30, overlap_tokens=6))
    assert [(c.start, c.end) for c in chunks_a] == [(c.start, c.end) for c in chunks_b]
    assert all(a.chunk_id != b.chunk_id for a, b in zip(chunks_a, chunks_b, strict=True))
