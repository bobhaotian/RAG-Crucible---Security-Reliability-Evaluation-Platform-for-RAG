"""Provider registry: ProviderRef (config) → provider instance (code).

All capability and dependency problems surface here, at build time, with
actionable messages — never mid-run. Hosted providers (cohere, openai) read
their credentials from environment variables at first use, not here, so the
registry stays side-effect-free and importable without keys.
"""

from __future__ import annotations

import importlib.util

from crucible.config import ProviderRef
from crucible.providers.base import Embedder, Generator, Reranker
from crucible.providers.errors import (
    CapabilityNotSupportedError,
    ProviderDependencyError,
)

_LOCAL_EXTRA_HINT = (
    "the 'local' provider needs the local-model extra: run `uv sync --extra local` "
    "(installs sentence-transformers / transformers / torch)"
)


def _require(spec_name: str, extra: str, provider: str) -> None:
    if importlib.util.find_spec(spec_name) is None:
        raise ProviderDependencyError(
            f"the '{provider}' provider needs the {extra} extra: `uv sync --extra {extra}`"
        )


def build_embedder(ref: ProviderRef) -> Embedder:
    if ref.provider == "fake":
        from crucible.providers.fake import FakeEmbedder

        return FakeEmbedder(model=ref.model)
    if ref.provider == "local":
        if importlib.util.find_spec("sentence_transformers") is None:
            raise ProviderDependencyError(_LOCAL_EXTRA_HINT)
        from crucible.providers.local import LocalEmbedder

        return LocalEmbedder(model=ref.model)
    if ref.provider == "cohere":
        _require("cohere", "cohere", "cohere")
        from crucible.providers.cohere_provider import CohereEmbedder

        return CohereEmbedder(model=ref.model)
    if ref.provider == "openai":
        _require("httpx", "openai", "openai")
        from crucible.providers.openai_provider import OpenAIEmbedder

        return OpenAIEmbedder(model=ref.model)
    raise ValueError(f"unknown provider: {ref.provider}")  # unreachable; Literal-validated


def build_reranker(ref: ProviderRef) -> Reranker:
    if ref.provider == "openai":
        raise CapabilityNotSupportedError(
            "the OpenAI-compatible API has no rerank endpoint; point the reranker "
            "stage at 'local' or 'cohere' instead"
        )
    if ref.provider == "fake":
        from crucible.providers.fake import FakeReranker

        return FakeReranker(model=ref.model)
    if ref.provider == "local":
        if importlib.util.find_spec("sentence_transformers") is None:
            raise ProviderDependencyError(_LOCAL_EXTRA_HINT)
        from crucible.providers.local import LocalReranker

        return LocalReranker(model=ref.model)
    if ref.provider == "cohere":
        _require("cohere", "cohere", "cohere")
        from crucible.providers.cohere_provider import CohereReranker

        return CohereReranker(model=ref.model)
    raise ValueError(f"unknown provider: {ref.provider}")  # unreachable; Literal-validated


def build_generator(ref: ProviderRef) -> Generator:
    if ref.provider == "fake":
        from crucible.providers.fake import FakeGenerator

        return FakeGenerator(model=ref.model)
    if ref.provider == "local":
        if importlib.util.find_spec("sentence_transformers") is None:
            raise ProviderDependencyError(_LOCAL_EXTRA_HINT)
        from crucible.providers.local import LocalGenerator

        return LocalGenerator(model=ref.model)
    if ref.provider == "cohere":
        _require("cohere", "cohere", "cohere")
        from crucible.providers.cohere_provider import CohereGenerator

        return CohereGenerator(model=ref.model)
    if ref.provider == "openai":
        _require("httpx", "openai", "openai")
        from crucible.providers.openai_provider import OpenAIGenerator

        return OpenAIGenerator(model=ref.model)
    raise ValueError(f"unknown provider: {ref.provider}")  # unreachable; Literal-validated
