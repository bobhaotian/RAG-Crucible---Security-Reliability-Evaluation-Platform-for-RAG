"""The provider contract: embed / rerank / generate behind one interface.

This is the single most important abstraction in the project (DESIGN.md §4).
Selecting a provider is config, never code; each pipeline stage selects its
provider independently. Interfaces are async-first — hosted providers are
I/O-bound, local ones wrap compute in ``asyncio.to_thread``.

``EmbedInputType`` is part of the interface because asymmetric embedding
(document vs query encoding) is semantically load-bearing for Cohere Embed v3;
providers that don't distinguish simply ignore it.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from crucible.types import StrictModel


class EmbedInputType(StrEnum):
    DOCUMENT = "document"  # Cohere: input_type="search_document"
    QUERY = "query"  # Cohere: input_type="search_query"


class Usage(StrictModel):
    """Token accounting. Local providers report estimates where the model has
    no native tokenizer-billed notion of usage."""

    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


class Message(StrictModel):
    role: Literal["system", "user", "assistant"]
    content: str


class GenParams(StrictModel):
    temperature: float = 0.0
    max_tokens: int = 512
    seed: int | None = None
    stop: tuple[str, ...] = ()


class EmbedResult(StrictModel):
    vectors: list[list[float]]
    model: str
    dim: int
    usage: Usage


class RerankItem(StrictModel):
    index: int  # position in the input document list
    score: float


class RerankResult(StrictModel):
    """Indices into the caller's document list, best first, length == top_n.
    Returning indices (not document copies) keeps chunk ownership with the
    caller — the pipeline just reorders its own candidates."""

    ranking: list[RerankItem]
    model: str
    usage: Usage


class GenerateResult(StrictModel):
    text: str
    model: str
    finish_reason: str = "stop"
    usage: Usage


@runtime_checkable
class Embedder(Protocol):
    async def embed(self, texts: Sequence[str], *, input_type: EmbedInputType) -> EmbedResult: ...


@runtime_checkable
class Reranker(Protocol):
    async def rerank(self, query: str, documents: Sequence[str], *, top_n: int) -> RerankResult: ...


@runtime_checkable
class Generator(Protocol):
    async def generate(
        self, messages: Sequence[Message], *, params: GenParams
    ) -> GenerateResult: ...


# Tokenizer-free token estimate used by providers that don't report real usage
# and by the chunker's size budget. ~4 chars/token is the standard rough rule;
# exactness is deliberately not load-bearing anywhere this is used.
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)
