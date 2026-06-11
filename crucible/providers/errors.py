"""Shared provider error taxonomy (DESIGN.md §4.4).

Hosted SDK/HTTP exceptions are translated into these at the provider boundary;
nothing outside ``crucible.providers`` ever catches a vendor exception.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Base class for everything raised across the provider boundary."""


class ProviderAuthError(ProviderError):
    """Missing/invalid credentials. Never retried; message names the env var."""


class ProviderRateLimitError(ProviderError):
    """Rate limited. Retryable with backoff."""


class ProviderTransientError(ProviderError):
    """Network/5xx-style failure. Retryable with backoff."""


class ProviderInvalidRequestError(ProviderError):
    """The request itself is wrong (bug or bad config). Not retryable."""


class CapabilityNotSupportedError(ProviderError):
    """The selected provider cannot serve this pipeline stage at all
    (e.g. the OpenAI-compatible API has no rerank endpoint). Raised at
    config-validation/build time, never mid-run."""


class ProviderDependencyError(ProviderError):
    """The provider's optional dependency extra is not installed."""


class ProviderNotImplementedError(ProviderError):
    """The provider is designed but not wired yet (cohere/openai land in Phase 6)."""
