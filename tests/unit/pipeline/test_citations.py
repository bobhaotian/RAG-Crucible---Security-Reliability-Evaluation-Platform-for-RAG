"""Citation marker parsing and the context-level fallback."""

from __future__ import annotations

from crucible.pipeline import RankedContext, parse_citations
from crucible.pipeline.types import Candidate
from crucible.types import Chunk, chunk_id_for


def _context(n: int) -> RankedContext:
    candidates = []
    for i in range(n):
        text = f"chunk text {i}"
        chunk = Chunk(
            chunk_id=chunk_id_for("d000000000000000", i * 10, i * 10 + len(text)),
            doc_id="d000000000000000",
            source="doc.md",
            text=text,
            start=i * 10,
            end=i * 10 + len(text),
        )
        candidates.append(Candidate(chunk=chunk, score=1.0 - i * 0.1, rank=i))
    return RankedContext(candidates=candidates, rerank_applied=True)


def test_markers_map_to_chunks_in_first_appearance_order() -> None:
    context = _context(3)
    citations = parse_citations("Answer uses [2] and then [1]. Repeat [2].", context)
    assert [(c.marker, c.parsed) for c in citations] == [(2, True), (1, True)]
    assert citations[0].chunk_id == context.candidates[1].chunk.chunk_id


def test_out_of_range_markers_ignored() -> None:
    context = _context(2)
    citations = parse_citations("Cites [1] and bogus [9].", context)
    assert [(c.marker, c.parsed) for c in citations] == [(1, True)]


def test_no_markers_falls_back_to_context_level() -> None:
    context = _context(3)
    citations = parse_citations("An answer with no markers at all.", context)
    assert len(citations) == 3
    assert all(not c.parsed for c in citations)
    assert [c.marker for c in citations] == [1, 2, 3]


def test_only_out_of_range_markers_also_falls_back() -> None:
    context = _context(2)
    citations = parse_citations("Only bogus [7] markers [12].", context)
    assert all(not c.parsed for c in citations)
    assert len(citations) == 2
