"""Deterministic, dependency-free provider for tests and CI.

Registered like any real provider so the interface stays honest (DESIGN.md
§15 #7): CI exercises the full ingest → retrieve → rerank → generate path with
zero model downloads and byte-stable outputs.

- ``FakeEmbedder``: bag-of-hashed-tokens projection. Texts sharing vocabulary
  get similar vectors, so retrieval behaves sensibly enough to test against.
- ``FakeReranker``: Jaccard token overlap between query and document.
- ``FakeGenerator``: extractive stub — answers with the best question-
  overlapping sentence from each top context passage, cited. It parses the
  ``[n] (source: ...)`` context block headers defined in
  ``crucible.pipeline.prompts``; that format is a documented contract between
  the two modules.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence

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

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_BLOCK_RE = re.compile(
    r"\[(\d+)\] \(source: [^)]*\)\n(.*?)(?=\n\n\[\d+\] \(source: |\n\nQuestion:|\Z)",
    re.DOTALL,
)


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class FakeEmbedder:
    def __init__(self, model: str = "hash-64", dim: int = 64) -> None:
        self.model = model
        self.dim = dim

    async def embed(self, texts: Sequence[str], *, input_type: EmbedInputType) -> EmbedResult:
        vectors = [self._embed_one(t) for t in texts]
        usage = Usage(input_tokens=sum(estimate_tokens(t) for t in texts))
        return EmbedResult(vectors=vectors, model=self.model, dim=self.dim, usage=usage)

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in _tokens(text):
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            h = int.from_bytes(digest, "big")
            sign = 1.0 if (h >> 33) & 1 else -1.0
            vec[h % self.dim] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            vec[0] = 1.0
            norm = 1.0
        return [v / norm for v in vec]


class FakeReranker:
    def __init__(self, model: str = "overlap") -> None:
        self.model = model

    async def rerank(self, query: str, documents: Sequence[str], *, top_n: int) -> RerankResult:
        q = set(_tokens(query))
        scores: list[float] = []
        for doc in documents:
            d = set(_tokens(doc))
            union = q | d
            scores.append(len(q & d) / len(union) if union else 0.0)
        order = sorted(range(len(documents)), key=lambda i: (-scores[i], i))[:top_n]
        ranking = [RerankItem(index=i, score=scores[i]) for i in order]
        usage = Usage(input_tokens=sum(estimate_tokens(d) for d in documents))
        return RerankResult(ranking=ranking, model=self.model, usage=usage)


_QUESTION_RE = re.compile(r"Question:\s*(.+)")


class FakeGenerator:
    """Extractive: from each of the top context blocks, answer with the
    sentence that best token-overlaps the question, cited."""

    def __init__(self, model: str = "extractive") -> None:
        self.model = model

    async def generate(self, messages: Sequence[Message], *, params: GenParams) -> GenerateResult:
        user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        question_match = _QUESTION_RE.search(user)
        question = question_match.group(1) if question_match else user
        parts = [
            f"{_best_sentence(block, question)} [{marker}]"
            for marker, block in _BLOCK_RE.findall(user)[:2]
            if block.strip()
        ]
        text = " ".join(parts) if parts else "I don't know."
        usage = Usage(
            input_tokens=sum(estimate_tokens(m.content) for m in messages),
            output_tokens=estimate_tokens(text),
        )
        return GenerateResult(text=text, model=self.model, usage=usage)


def _best_sentence(block: str, question: str) -> str:
    """Pick the sentence with the highest Jaccard overlap to the question —
    normalizing by length is what lets a short fact sentence beat a long
    intro sentence that merely shares entity tokens."""
    flat = " ".join(block.split())
    sentences: list[str] = [s.strip() for s in re.findall(r"[^.!?]+[.!?]", flat)]
    if not sentences:
        return flat[:300]
    question_tokens = set(_tokens(question))

    def jaccard(sentence: str) -> float:
        tokens = set(_tokens(sentence))
        union = question_tokens | tokens
        return len(question_tokens & tokens) / len(union) if union else 0.0

    return max(sentences, key=jaccard)[:300]
