"""Provider registry: ProviderRef (config) → provider instance (code).

All capability problems surface here, at build time, with actionable messages
— never mid-run. The shared retry wrapper for hosted providers lands with the
cohere/openai implementations in Phase 6.
"""

from __future__ import annotations

import importlib.util

from crucible.config import ProviderRef
from crucible.providers.base import Embedder, Generator, Reranker
from crucible.providers.errors import (
    CapabilityNotSupportedError,
    ProviderDependencyError,
    ProviderNotImplementedError,
)

_LOCAL_EXTRA_HINT = (
    "the 'local' provider needs the local-model extra: run `uv sync --extra local` "
    "(installs sentence-transformers / transformers / torch)"
)
_PHASE6_HINT = "the '{name}' provider ships in Phase 6; use 'local' or 'fake' for now"


def _require_local_extra() -> None:
    if importlib.util.find_spec("sentence_transformers") is None:
        raise ProviderDependencyError(_LOCAL_EXTRA_HINT)


def build_embedder(ref: ProviderRef) -> Embedder:
    if ref.provider == "fake":
        from crucible.providers.fake import FakeEmbedder

        return FakeEmbedder(model=ref.model)
    if ref.provider == "local":
        _require_local_extra()
        from crucible.providers.local import LocalEmbedder

        return LocalEmbedder(model=ref.model)
    raise ProviderNotImplementedError(_PHASE6_HINT.format(name=ref.provider))


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
        _require_local_extra()
        from crucible.providers.local import LocalReranker

        return LocalReranker(model=ref.model)
    raise ProviderNotImplementedError(_PHASE6_HINT.format(name=ref.provider))


def build_generator(ref: ProviderRef) -> Generator:
    if ref.provider == "fake":
        from crucible.providers.fake import FakeGenerator

        return FakeGenerator(model=ref.model)
    if ref.provider == "local":
        _require_local_extra()
        from crucible.providers.local import LocalGenerator

        return LocalGenerator(model=ref.model)
    raise ProviderNotImplementedError(_PHASE6_HINT.format(name=ref.provider))
