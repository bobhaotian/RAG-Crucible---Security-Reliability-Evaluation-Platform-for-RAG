"""Provider registry: capability and availability errors at build time."""

from __future__ import annotations

import pytest

from crucible.config import ProviderRef
from crucible.providers import (
    CapabilityNotSupportedError,
    ProviderDependencyError,
    build_embedder,
    build_generator,
    build_reranker,
)
from crucible.providers.fake import FakeEmbedder, FakeGenerator, FakeReranker


def test_fake_provider_builds_all_stages() -> None:
    assert isinstance(build_embedder(ProviderRef(provider="fake", model="m")), FakeEmbedder)
    assert isinstance(build_reranker(ProviderRef(provider="fake", model="m")), FakeReranker)
    assert isinstance(build_generator(ProviderRef(provider="fake", model="m")), FakeGenerator)


def test_openai_rerank_is_a_capability_error_with_a_fix() -> None:
    with pytest.raises(CapabilityNotSupportedError, match="no rerank endpoint"):
        build_reranker(ProviderRef(provider="openai", model="anything"))


def test_openai_provider_builds_with_httpx_present() -> None:
    # httpx is a dev dependency, so the openai stage builds without keys (auth
    # only happens on first call, not at build time).
    from crucible.providers.openai_provider import OpenAIEmbedder, OpenAIGenerator

    assert isinstance(
        build_embedder(ProviderRef(provider="openai", model="text-embedding-3-small")),
        OpenAIEmbedder,
    )
    assert isinstance(
        build_generator(ProviderRef(provider="openai", model="gpt-4o-mini")), OpenAIGenerator
    )


def test_cohere_build_depends_on_the_extra() -> None:
    import importlib.util

    ref = ProviderRef(provider="cohere", model="embed-english-v3.0")
    if importlib.util.find_spec("cohere") is None:
        with pytest.raises(ProviderDependencyError, match="cohere extra"):
            build_embedder(ref)
    else:
        from crucible.providers.cohere_provider import CohereEmbedder

        assert isinstance(build_embedder(ref), CohereEmbedder)
