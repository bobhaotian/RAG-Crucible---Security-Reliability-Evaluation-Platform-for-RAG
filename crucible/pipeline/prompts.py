"""Prompt construction for the generation stage.

The context block format is a small but real contract:

    [<marker>] (source: <source>[ › <section>])
    <chunk text>

— citation parsing maps ``[n]`` markers back to blocks, and the fake
provider's extractive generator parses these headers to stay deterministic.
Defense variants (instruction isolation, content sandboxing) land in Phase 4
as alternative builders behind ``pipeline.defenses`` toggles; templates are
versioned so cached judge results invalidate correctly.
"""

from __future__ import annotations

from crucible.pipeline.types import RankedContext
from crucible.providers.base import Message

TEMPLATE_VERSION = "baseline-v1"

SYSTEM_PROMPT = (
    "You are a careful assistant that answers questions using only the provided "
    "context passages. Cite every passage you use with its bracketed number, like [1]. "
    "If the context does not contain the answer, say you don't know. Be concise."
)


def format_context_block(marker: int, source: str, section: str | None, text: str) -> str:
    label = f"{source} › {section}" if section else source
    return f"[{marker}] (source: {label})\n{text}"


def build_messages(query: str, context: RankedContext) -> list[Message]:
    blocks = [
        format_context_block(
            marker=i,
            source=candidate.chunk.source,
            section=candidate.chunk.section,
            text=candidate.chunk.text,
        )
        for i, candidate in enumerate(context.candidates, start=1)
    ]
    user = (
        "Context:\n\n"
        + "\n\n".join(blocks)
        + f"\n\nQuestion: {query}\n\nAnswer (cite passages like [1]):"
    )
    return [
        Message(role="system", content=SYSTEM_PROMPT),
        Message(role="user", content=user),
    ]
