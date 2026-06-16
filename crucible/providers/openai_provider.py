"""OpenAI-compatible provider (DESIGN.md §2, §4.2).

Talks the OpenAI REST shapes (``/embeddings``, ``/chat/completions``) over
httpx, so it works against OpenAI itself or any compatible server (vLLM,
Ollama, LM Studio, …) by pointing ``OPENAI_BASE_URL`` at it. There is no
standard rerank endpoint, so the registry raises ``CapabilityNotSupported``
for the rerank stage rather than pretending — the fix is one YAML line.

The httpx transport is injectable so request/response translation is tested
without network; the registry builds a real client from ``OPENAI_API_KEY`` /
``OPENAI_BASE_URL``.
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

DEFAULT_API_KEY_ENV = "OPENAI_API_KEY"
DEFAULT_BASE_URL = "https://api.openai.com/v1"


def _build_client(api_key_env: str, base_url: str, timeout_s: float) -> Any:
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - exercised via the registry
        raise ProviderError(
            "the 'openai' provider needs the openai extra: `uv sync --extra openai`"
        ) from exc
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise ProviderAuthError(
            f"the openai provider requires the {api_key_env} environment variable"
        )
    return httpx.AsyncClient(
        base_url=base_url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout_s,
    )


def _translate_status(status: int, body: str) -> ProviderError:
    if status in (401, 403):
        return ProviderAuthError(f"openai auth failed: {body}")
    if status == 429:
        return ProviderRateLimitError(f"openai rate limited: {body}")
    if status >= 500:
        return ProviderTransientError(f"openai server error {status}: {body}")
    return ProviderInvalidRequestError(f"openai rejected the request ({status}): {body}")


class _OpenAIBase:
    def __init__(
        self,
        model: str,
        *,
        client: Any = None,
        api_key_env: str = DEFAULT_API_KEY_ENV,
        base_url: str | None = None,
        timeout_s: float = 60.0,
    ):
        self.model = model
        self._client = client
        self._api_key_env = api_key_env
        self._base_url = base_url or os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL)
        self._timeout_s = timeout_s

    def _ensure(self) -> Any:
        if self._client is None:
            self._client = _build_client(self._api_key_env, self._base_url, self._timeout_s)
        return self._client

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        import httpx

        client = self._ensure()

        async def call() -> dict[str, Any]:
            try:
                response = await client.post(path, json=payload)
            except httpx.HTTPError as exc:
                raise ProviderTransientError(f"openai request failed: {exc}") from exc
            if response.status_code >= 400:
                raise _translate_status(response.status_code, response.text)
            data: dict[str, Any] = response.json()
            return data

        return await with_retries(call)


class OpenAIEmbedder(_OpenAIBase):
    async def embed(self, texts: Sequence[str], *, input_type: EmbedInputType) -> EmbedResult:
        # The OpenAI embeddings API is symmetric; input_type is accepted and ignored.
        data = await self._post("/embeddings", {"model": self.model, "input": list(texts)})
        rows = sorted(data["data"], key=lambda d: d["index"])
        vectors = [[float(x) for x in row["embedding"]] for row in rows]
        usage = Usage(input_tokens=int(data.get("usage", {}).get("prompt_tokens", 0)))
        dim = len(vectors[0]) if vectors else 0
        return EmbedResult(vectors=vectors, model=self.model, dim=dim, usage=usage)


class OpenAIGenerator(_OpenAIBase):
    async def generate(self, messages: Sequence[Message], *, params: GenParams) -> GenerateResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": params.temperature,
            "max_tokens": params.max_tokens,
        }
        if params.stop:
            payload["stop"] = list(params.stop)
        data = await self._post("/chat/completions", payload)
        choice = data["choices"][0]
        text = str(choice["message"]["content"] or "").strip()
        usage_data = data.get("usage", {})
        usage = Usage(
            input_tokens=int(usage_data.get("prompt_tokens", 0))
            or sum(estimate_tokens(m.content) for m in messages),
            output_tokens=int(usage_data.get("completion_tokens", 0)) or estimate_tokens(text),
        )
        finish = str(choice.get("finish_reason", "stop") or "stop")
        return GenerateResult(text=text, model=self.model, finish_reason=finish, usage=usage)
