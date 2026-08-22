"""The fake provider must be deterministic and directionally sensible."""

from __future__ import annotations

from crucible.providers import EmbedInputType, GenParams, Message
from crucible.providers.fake import FakeEmbedder, FakeGenerator, FakeReranker


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


async def test_embeddings_deterministic_and_normalized() -> None:
    embedder = FakeEmbedder()
    first = await embedder.embed(["battery life of the drone"], input_type=EmbedInputType.QUERY)
    second = await embedder.embed(["battery life of the drone"], input_type=EmbedInputType.QUERY)
    assert first.vectors == second.vectors
    assert first.dim == 64
    assert abs(_dot(first.vectors[0], first.vectors[0]) - 1.0) < 1e-9


async def test_embeddings_reflect_token_overlap() -> None:
    embedder = FakeEmbedder()
    result = await embedder.embed(
        [
            "battery life of the inspection drone",
            "the drone battery lasts many hours of inspection",
            "completely unrelated cooking recipe with garlic",
        ],
        input_type=EmbedInputType.DOCUMENT,
    )
    query, similar, unrelated = result.vectors
    assert _dot(query, similar) > _dot(query, unrelated)


async def test_reranker_prefers_overlapping_documents() -> None:
    reranker = FakeReranker()
    result = await reranker.rerank(
        "battery life drone",
        ["a cooking recipe", "drone battery life details", "shipping policy"],
        top_n=2,
    )
    assert len(result.ranking) == 2
    assert result.ranking[0].index == 1
    assert result.ranking[0].score > result.ranking[1].score


async def test_generator_extracts_and_cites_from_context_blocks() -> None:
    user = (
        "Context:\n\n"
        "[1] (source: products/x1.md › Specs)\n"
        "The X1 has a battery life of 72 hours. More detail follows here.\n\n"
        "[2] (source: handbook/returns.txt)\n"
        "Customers may return any product within 45 days of delivery.\n\n"
        "Question: What is the battery life?\n\nAnswer (cite passages like [1]):"
    )
    generator = FakeGenerator()
    result = await generator.generate(
        [Message(role="system", content="sys"), Message(role="user", content=user)],
        params=GenParams(),
    )
    assert "[1]" in result.text
    assert "battery life of 72 hours" in result.text


async def test_generator_without_context_says_so() -> None:
    generator = FakeGenerator()
    result = await generator.generate(
        [Message(role="user", content="Question: anything?")], params=GenParams()
    )
    assert result.text == "I don't know."
