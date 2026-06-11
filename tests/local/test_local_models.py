"""Exercises the real local models (downloads ~200 MB on first run).

Excluded by default (`-m "not local_models"` in addopts); run via
`make test-local`. The full generator path is covered by `make demo` instead
— pulling the 1 GB Qwen model into a test run buys nothing extra.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.local_models

pytest.importorskip("sentence_transformers")

from crucible.providers import EmbedInputType  # noqa: E402
from crucible.providers.local import LocalEmbedder, LocalReranker  # noqa: E402


async def test_minilm_embeds_with_expected_dim() -> None:
    embedder = LocalEmbedder("sentence-transformers/all-MiniLM-L6-v2")
    result = await embedder.embed(
        ["the drone battery lasts eighteen hours"], input_type=EmbedInputType.DOCUMENT
    )
    assert result.dim == 384
    assert len(result.vectors) == 1


async def test_cross_encoder_reranks_relevant_doc_first() -> None:
    reranker = LocalReranker("cross-encoder/ms-marco-MiniLM-L-6-v2")
    result = await reranker.rerank(
        "what is the battery life of the drone",
        [
            "the cafeteria menu changes weekly",
            "the drone battery lasts eighteen hours in flight",
            "returns are accepted within thirty days",
        ],
        top_n=2,
    )
    assert result.ranking[0].index == 1
