"""OpenAI-compatible provider, exercised against an httpx MockTransport — real
httpx request/response handling, no network."""

from __future__ import annotations

import json

import httpx
import pytest

from crucible.providers import EmbedInputType, GenParams, Message
from crucible.providers.errors import ProviderAuthError, ProviderInvalidRequestError
from crucible.providers.openai_provider import OpenAIEmbedder, OpenAIGenerator


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://example.test/v1",
        headers={"Authorization": "Bearer test"},
        transport=handler,
    )


async def test_embed_posts_and_parses_sorted_vectors() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.4, 0.5]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ],
                "usage": {"prompt_tokens": 7},
            },
        )

    embedder = OpenAIEmbedder(
        "text-embedding-3-small", client=_client(httpx.MockTransport(handler))
    )
    result = await embedder.embed(["a", "b"], input_type=EmbedInputType.QUERY)

    assert seen["url"] == "https://example.test/v1/embeddings"
    assert result.vectors == [[0.1, 0.2], [0.4, 0.5]]  # reordered by index
    assert result.dim == 2
    assert result.usage.input_tokens == 7


async def test_generate_posts_chat_and_parses_choice() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hello there"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )

    generator = OpenAIGenerator("gpt-4o-mini", client=_client(httpx.MockTransport(handler)))
    result = await generator.generate(
        [Message(role="user", content="hi")], params=GenParams(max_tokens=8)
    )
    assert result.text == "hello there"
    assert result.usage.input_tokens == 5 and result.usage.output_tokens == 2


async def test_http_errors_translate(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(_: float) -> None:
        return None

    monkeypatch.setattr("crucible.providers.retry.asyncio.sleep", _noop)

    def unauthorized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    embedder = OpenAIEmbedder("m", client=_client(httpx.MockTransport(unauthorized)))
    with pytest.raises(ProviderAuthError):
        await embedder.embed(["x"], input_type=EmbedInputType.DOCUMENT)

    def bad_request(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "nope"})

    embedder2 = OpenAIGenerator("m", client=_client(httpx.MockTransport(bad_request)))
    with pytest.raises(ProviderInvalidRequestError):
        await embedder2.generate([Message(role="user", content="x")], params=GenParams())
