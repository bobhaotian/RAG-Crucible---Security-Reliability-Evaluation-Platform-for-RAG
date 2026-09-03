"""Query-time defenses against retrieved-content attacks (DESIGN.md §5.5).

Three independent, toggleable mechanisms the security suite measures:

- ``injection_filter`` — a heuristic classifier that screens candidate chunks
  for imperative adversarial instructions ("ignore previous instructions",
  "reply only with …") and drops the matches before they reach the prompt.
  Deterministic, provider-agnostic; it removes the attack surface rather than
  hoping the model resists it.
- ``prompt_isolation`` — a hardened system prompt (in ``prompts.py``) that
  frames retrieved text as untrusted data the model must never obey. This
  only influences instruction-following models; it is the defense for cases a
  pattern filter misses.
- ``answer_integrity`` — provenance filtering plus numeric consistency
  resolution (in ``consistency.py``); it keeps a unique verified winner and
  abstains when trusted evidence conflicts or no trusted evidence remains.

A real deployment would layer both; the suite reports each in isolation so the
contribution of each is legible.
"""

from __future__ import annotations

import re

from crucible.pipeline.types import RankedContext

# Patterns an indirect-injection payload almost always contains. Tuned to catch
# the attack templates in ``crucible/attacks`` (and common real variants)
# without flagging ordinary documentation prose.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(all\s+|any\s+)?(previous|prior|above|the\s+above)", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+|any\s+)?(previous|prior|above|the)", re.IGNORECASE),
    re.compile(r"reply\s+only\s+with", re.IGNORECASE),
    re.compile(r"respond\s+(only\s+)?with\s+(the\s+)?(exact|following|word|text)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\b", re.IGNORECASE),
    re.compile(r"system\s+(override|prompt)\b", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
)


def looks_like_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in _INJECTION_PATTERNS)


def filter_injected_chunks(context: RankedContext) -> tuple[RankedContext, int]:
    """Drop candidate chunks that look like injection payloads. Returns the
    screened context and the number of chunks removed."""
    kept = [c for c in context.candidates if not looks_like_injection(c.chunk.text)]
    removed = len(context.candidates) - len(kept)
    if removed == 0:
        return context, 0
    return RankedContext(candidates=kept, rerank_applied=context.rerank_applied), removed


def filter_untrusted_chunks(
    context: RankedContext, *, minimum_trust: float = 0.5
) -> tuple[RankedContext, int]:
    """Drop chunks whose server-assigned provenance is not trustworthy."""
    kept = [
        candidate
        for candidate in context.candidates
        if candidate.chunk.provenance.verified
        and candidate.chunk.provenance.trust_score >= minimum_trust
    ]
    removed = len(context.candidates) - len(kept)
    if removed == 0:
        return context, 0
    return RankedContext(candidates=kept, rerank_applied=context.rerank_applied), removed
