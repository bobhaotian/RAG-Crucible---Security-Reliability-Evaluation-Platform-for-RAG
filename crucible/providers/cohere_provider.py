"""Cohere provider — the first-class hosted path (DESIGN.md §2, §4.2).

Embed v3, Rerank 3.5, and Command behind the same interface as every other
provider, via the Cohere v2 async SDK. The ``EmbedInputType`` in the interface
maps directly onto Embed v3's asymmetric ``input_type`` (search_document vs
search_query) — the reason that distinction is in the contract at all.

The SDK client is injectable so the request/response translation is unit-tested
without a key or network; the registry builds a real ``cohere.AsyncClientV2``
from ``COHERE_API_KEY``. Vendor exceptions are translated to the shared
taxonomy at this boundary and retryable failures go through ``with_retries``.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

from crucible.providers.base import (
    EmbedInputType,
    EmbedResult,
    GenerateResult,
    GenParams,
    Message,
    RerankItem,
    RerankResult,
    Usage,
    estimate_tokens,
)
from crucible.providers.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderInvalidRequestError,
    ProviderRateLimitError,
    ProviderTransientError,
)
from crucible.providers.retry import with_retries

_INPUT_TYPE = {
    EmbedInputType.DOCUMENT: "search_document",
    EmbedInputType.QUERY: "search_query",
}
DEFAULT_API_KEY_ENV = "COHERE_API_KEY"


def _build_client(api_key_env: str) -> Any:
    try:
        import cohere
    except ImportError as exc:  # pragma: no cover - exercised via the registry
        raise ProviderError(
            "the 'cohere' provider needs the cohere extra: `uv sync --extra cohere`"
        ) from exc
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise ProviderAuthError(
            f"the cohere provider requires the {api_key_env} environment variable"
        )
    return cohere.AsyncClientV2(api_key=api_key)


def _translate(exc: Exception) -> ProviderError:
    """Map a Cohere SDK exception onto the shared taxonomy by status code."""
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return ProviderAuthError(f"cohere auth failed: {exc}")
    if status == 429:
        return ProviderRateLimitError(f"cohere rate limited: {exc}")
    if status is not None and status >= 500:
        return ProviderTransientError(f"cohere server error: {exc}")
    if status is not None and 400 <= status < 500:
        return ProviderInvalidRequestError(f"cohere rejected the request: {exc}")
    return ProviderTransientError(f"cohere call failed: {exc}")


class _CohereBase:
    def __init__(self, model: str, *, client: Any = None, api_key_env: str = DEFAULT_API_KEY_ENV):
        self.model = model
        self._client = client
        self._api_key_env = api_key_env

    def _ensure(self) -> Any:
        if self._client is None:
            self._client = _build_client(self._api_key_env)
        return self._client


class CohereEmbedder(_CohereBase):
    async def embed(self, texts: Sequence[str], *, input_type: EmbedInputType) -> EmbedResult:
        client = self._ensure()

        async def call() -> Any:
            try:
                return await client.embed(
                    texts=list(texts),
                    model=self.model,
                    input_type=_INPUT_TYPE[input_type],
                    embedding_types=["float"],
                )
            except ProviderError:
                raise
            except Exception as exc:
                raise _translate(exc) from exc

        response = await with_retries(call)
        vectors = [[float(x) for x in vec] for vec in response.embeddings.float]
        usage = Usage(input_tokens=sum(estimate_tokens(t) for t in texts))
        dim = len(vectors[0]) if vectors else 0
        return EmbedResult(vectors=vectors, model=self.model, dim=dim, usage=usage)


class CohereReranker(_CohereBase):
    async def rerank(self, query: str, documents: Sequence[str], *, top_n: int) -> RerankResult:
        client = self._ensure()

        async def call() -> Any:
            try:
                return await client.rerank(
                    model=self.model,
                    query=query,
                    documents=list(documents),
                    top_n=min(top_n, len(documents)),
                )
            except ProviderError:
                raise
            except Exception as exc:
                raise _translate(exc) from exc

        response = await with_retries(call)
        ranking = [
            RerankItem(index=int(r.index), score=float(r.relevance_score)) for r in response.results
        ]
        usage = Usage(input_tokens=sum(estimate_tokens(d) for d in documents))
        return RerankResult(ranking=ranking, model=self.model, usage=usage)


class CohereGenerator(_CohereBase):
    async def generate(self, messages: Sequence[Message], *, params: GenParams) -> GenerateResult:
        client = self._ensure()
        payload = [{"role": m.role, "content": m.content} for m in messages]

        async def call() -> Any:
            try:
                return await client.chat(
                    model=self.model,
                    messages=payload,
                    temperature=params.temperature,
                    max_tokens=params.max_tokens,
                )
            except ProviderError:
                raise
            except Exception as exc:
                raise _translate(exc) from exc

        response = await with_retries(call)
        text = _extract_text(response)
        usage = _usage(response) or Usage(
            input_tokens=sum(estimate_tokens(m.content) for m in messages),
            output_tokens=estimate_tokens(text),
        )
        finish = str(getattr(response, "finish_reason", "stop") or "stop")
        return GenerateResult(text=text, model=self.model, finish_reason=finish, usage=usage)


def _extract_text(response: Any) -> str:
    """Command v2 returns message.content as a list of typed blocks."""
    content = getattr(getattr(response, "message", None), "content", None)
    if isinstance(content, list):
        return "".join(getattr(block, "text", "") for block in content).strip()
    return str(content or "").strip()


def _usage(response: Any) -> Usage | None:
    usage = getattr(response, "usage", None)
    tokens = getattr(usage, "tokens", None) if usage is not None else None
    if tokens is None:
        return None
    return Usage(
        input_tokens=int(getattr(tokens, "input_tokens", 0) or 0),
        output_tokens=int(getattr(tokens, "output_tokens", 0) or 0),
    )
