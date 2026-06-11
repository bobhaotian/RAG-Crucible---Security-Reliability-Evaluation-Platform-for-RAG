"""Provider registry: capability and availability errors at build time."""

from __future__ import annotations

import pytest

from crucible.config import ProviderRef
from crucible.providers import (
    CapabilityNotSupportedError,
    ProviderNotImplementedError,
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


def test_unwired_providers_point_at_phase_6() -> None:
    with pytest.raises(ProviderNotImplementedError, match="Phase 6"):
        build_embedder(ProviderRef(provider="cohere", model="embed-english-v3.0"))
    with pytest.raises(ProviderNotImplementedError, match="Phase 6"):
        build_generator(ProviderRef(provider="openai", model="gpt-4o-mini"))
