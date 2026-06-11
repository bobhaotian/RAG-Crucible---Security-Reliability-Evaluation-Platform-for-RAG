"""Map ``[n]`` markers in generated text back to context chunks.

Two fidelity levels, reported honestly (DESIGN.md §3): if the generator emitted
parseable markers we return those (``parsed=True``, deduplicated, in order of
first appearance; out-of-range markers are ignored). If it cited nothing, we
fall back to the full context (``parsed=False``) — the chunks *were* in the
prompt, and the faithfulness suite scores the difference rather than hiding it.
"""

from __future__ import annotations

import re

from crucible.pipeline.types import Citation, RankedContext

_MARKER_RE = re.compile(r"\[(\d{1,3})\]")


def parse_citations(text: str, context: RankedContext) -> list[Citation]:
    n = len(context.candidates)
    seen: set[int] = set()
    citations: list[Citation] = []
    for raw in _MARKER_RE.findall(text):
        marker = int(raw)
        if marker < 1 or marker > n or marker in seen:
            continue
        seen.add(marker)
        citations.append(
            Citation(
                chunk_id=context.candidates[marker - 1].chunk.chunk_id,
                marker=marker,
                parsed=True,
            )
        )
    if citations:
        return citations
    return [
        Citation(chunk_id=candidate.chunk.chunk_id, marker=i, parsed=False)
        for i, candidate in enumerate(context.candidates, start=1)
    ]
