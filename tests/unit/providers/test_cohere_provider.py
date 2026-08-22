"""Cohere provider request/response translation, via an injected fake client
(no SDK, key, or network needed)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from crucible.providers import EmbedInputType, GenParams, Message
from crucible.providers.cohere_provider import (
    CohereEmbedder,
    CohereGenerator,
    CohereReranker,
)
from crucible.providers.errors import ProviderAuthError, ProviderRateLimitError


class FakeCohereClient:
    """Mimics the slices of cohere.AsyncClientV2 the provider uses."""

    def __init__(self) -> None:
        self.calls: dict[str, Any] = {}

    async def embed(self, **kwargs: Any) -> Any:
        self.calls["embed"] = kwargs
        return SimpleNamespace(embeddings=SimpleNamespace(float=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]))

    async def rerank(self, **kwargs: Any) -> Any:
        self.calls["rerank"] = kwargs
        return SimpleNamespace(
            results=[
                SimpleNamespace(index=2, relevance_score=0.9),
                SimpleNamespace(index=0, relevance_score=0.4),
            ]
        )

    async def chat(self, **kwargs: Any) -> Any:
        self.calls["chat"] = kwargs
        return SimpleNamespace(
            message=SimpleNamespace(content=[SimpleNamespace(text="the answer")]),
            finish_reason="complete",
            usage=SimpleNamespace(tokens=SimpleNamespace(input_tokens=11, output_tokens=3)),
        )


async def test_embed_maps_input_type_and_parses_vectors() -> None:
    client = FakeCohereClient()
    embedder = CohereEmbedder("embed-english-v3.0", client=client)
    result = await embedder.embed(["a", "b"], input_type=EmbedInputType.QUERY)

    assert client.calls["embed"]["input_type"] == "search_query"
    assert client.calls["embed"]["model"] == "embed-english-v3.0"
    assert result.vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert result.dim == 3


async def test_rerank_returns_indices_and_scores() -> None:
    client = FakeCohereClient()
    reranker = CohereReranker("rerank-v3.5", client=client)
    result = await reranker.rerank("q", ["d0", "d1", "d2"], top_n=2)

    assert client.calls["rerank"]["top_n"] == 2
    assert [(r.index, r.score) for r in result.ranking] == [(2, 0.9), (0, 0.4)]


async def test_generate_extracts_text_and_usage() -> None:
    client = FakeCohereClient()
    generator = CohereGenerator("command-r-08-2024", client=client)
    result = await generator.generate(
        [Message(role="user", content="hi")], params=GenParams(max_tokens=16)
    )

    assert result.text == "the answer"
    assert result.finish_reason == "complete"
    assert result.usage.input_tokens == 11 and result.usage.output_tokens == 3
    assert client.calls["chat"]["messages"] == [{"role": "user", "content": "hi"}]


async def test_vendor_errors_translate_to_taxonomy() -> None:
    class Failing:
        def __init__(self, status: int) -> None:
            self.status = status

        async def embed(self, **kwargs: Any) -> Any:
            raise _StatusError(self.status)

    auth = CohereEmbedder("m", client=Failing(401))
    with pytest.raises(ProviderAuthError):
        await auth.embed(["x"], input_type=EmbedInputType.DOCUMENT)

    # 429 is retryable, so it surfaces as a rate-limit error after retries
    rate = CohereEmbedder("m", client=Failing(429))
    with pytest.raises(ProviderRateLimitError):
        await rate.embed(["x"], input_type=EmbedInputType.DOCUMENT)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(_: float) -> None:
        return None

    monkeypatch.setattr("crucible.providers.retry.asyncio.sleep", _noop)


class _StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"http {status_code}")
