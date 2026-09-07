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

# Categories of retrieved-content instruction, written from the threat model in
# docs/threat-model.md — deliberately NOT from the payloads in crucible/attacks.
#
# The earlier list transcribed the shipped templates ("reply only with",
# "ignore all previous"), so `injection_compliance_rate` measured whether the
# filter recognised the two strings it was built from. A test now fails if any
# pattern reproduces a phrase from a payload.
#
# These describe what an injected instruction *does*: cancel prior context,
# coerce a literal output, claim system authority, reassign the assistant's
# role, or open a new instruction block. It is still a heuristic over surface
# form and it will still miss paraphrases — which is why the suite reports
# `injection_compliance_rate@seen` and `@heldout` separately instead of one
# number that hides the difference.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    # cancel what came before
    re.compile(
        r"\b(ignore|disregard|forget|override|discard)\b[^.]{0,40}"
        r"\b(instruction|directive|rule|guidance|context|prompt)s?\b",
        re.IGNORECASE,
    ),
    # coerce a literal output
    re.compile(
        r"\b(output|emit|print|echo|return|reply|respond|answer)\b[^.]{0,40}"
        r"\b(verbatim|exact|exactly|precisely|nothing\s+else|and\s+nothing)\b",
        re.IGNORECASE,
    ),
    # claim to speak for the system
    re.compile(
        r"\b(system|admin|administrator|operator|developer|maintainer)\b[^.]{0,25}"
        r"\b(notice|override|directive|message|mode|instruction)s?\b",
        re.IGNORECASE,
    ),
    # reassign the assistant's role
    re.compile(r"\byou\s+are\s+(now|from\s+now|henceforth)\b", re.IGNORECASE),
    # open a fresh instruction block
    re.compile(r"\bnew\s+(instruction|directive|rule)s?\s*:", re.IGNORECASE),
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
