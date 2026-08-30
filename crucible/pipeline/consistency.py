"""Deterministic numeric-claim conflict detection over retrieved context.

The checker is query-conditioned: quantities found in independently sourced
chunks retrieved for one question are comparable when their normalized units
match.  This intentionally small first version handles the benchmark's exact
numbers (hours, days, prices, weights, and similar measurements) without an
LLM judge.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Literal

from crucible.pipeline.types import RankedContext
from crucible.types import StrictModel

_QUANTITY_RE = re.compile(
    r"(?<![\w-])(?P<value>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>hours?|hrs?|days?|minutes?|mins?|kg|kilograms?|usd|dollars?|m/s|percent|%)\b",
    re.IGNORECASE,
)

_UNIT_ALIASES = {
    "hour": "hours",
    "hr": "hours",
    "hrs": "hours",
    "day": "days",
    "minute": "minutes",
    "min": "minutes",
    "mins": "minutes",
    "kilogram": "kg",
    "kilograms": "kg",
    "dollar": "usd",
    "dollars": "usd",
    "%": "percent",
}


class NumericClaim(StrictModel):
    query: str
    value: str
    unit: str
    chunk_id: str
    doc_id: str
    source: str
    verified: bool
    trust_score: float


class ClaimConflict(StrictModel):
    unit: str
    values: tuple[str, ...]
    claims: tuple[NumericClaim, ...]


class ConsistencyDecision(StrictModel):
    action: Literal["proceed", "abstain"]
    context: RankedContext
    conflicts: tuple[ClaimConflict, ...] = ()
    removed_chunks: int = 0
    reason: str | None = None


def extract_numeric_claims(query: str, context: RankedContext) -> list[NumericClaim]:
    """Extract normalized quantities from each independently identified chunk."""
    claims: list[NumericClaim] = []
    seen: set[tuple[str, str, str]] = set()
    for candidate in context.candidates:
        chunk = candidate.chunk
        for match in _QUANTITY_RE.finditer(chunk.text):
            value = _normalize_value(match.group("value"))
            unit = _normalize_unit(match.group("unit"))
            identity = (chunk.doc_id, value, unit)
            if identity in seen:
                continue
            seen.add(identity)
            claims.append(
                NumericClaim(
                    query=query,
                    value=value,
                    unit=unit,
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    source=chunk.source,
                    verified=chunk.provenance.verified,
                    trust_score=chunk.provenance.trust_score,
                )
            )
    return claims


def find_numeric_conflicts(query: str, context: RankedContext) -> list[ClaimConflict]:
    """Find units for which independent retrieved documents assert different values."""
    by_unit: dict[str, list[NumericClaim]] = defaultdict(list)
    for claim in extract_numeric_claims(query, context):
        by_unit[claim.unit].append(claim)

    conflicts: list[ClaimConflict] = []
    for unit, claims in sorted(by_unit.items()):
        values = tuple(sorted({claim.value for claim in claims}, key=_numeric_sort_key))
        documents = {claim.doc_id for claim in claims}
        if len(values) > 1 and len(documents) > 1:
            conflicts.append(ClaimConflict(unit=unit, values=values, claims=tuple(claims)))
    return conflicts


def resolve_numeric_conflicts(query: str, context: RankedContext) -> ConsistencyDecision:
    """Resolve conflicts using independent-source trust, or abstain when ambiguous."""
    conflicts = find_numeric_conflicts(query, context)
    if not conflicts:
        return ConsistencyDecision(action="proceed", context=context)

    rejected_chunk_ids: set[str] = set()
    for conflict in conflicts:
        scores, verified = _evidence_by_value(conflict)
        ranked = sorted(scores, key=lambda value: (-scores[value], _numeric_sort_key(value)))
        winner = ranked[0]
        runner_up_score = scores[ranked[1]]
        if not verified[winner] or scores[winner] <= runner_up_score:
            return ConsistencyDecision(
                action="abstain",
                context=context,
                conflicts=tuple(conflicts),
                reason="conflicting_sources_without_a_unique_verified_winner",
            )
        rejected_chunk_ids.update(
            claim.chunk_id for claim in conflict.claims if claim.value != winner
        )

    kept = [
        candidate
        for candidate in context.candidates
        if candidate.chunk.chunk_id not in rejected_chunk_ids
    ]
    resolved = RankedContext(candidates=kept, rerank_applied=context.rerank_applied)
    return ConsistencyDecision(
        action="proceed",
        context=resolved,
        conflicts=tuple(conflicts),
        removed_chunks=len(context.candidates) - len(kept),
        reason="selected_unique_verified_winner",
    )


def _evidence_by_value(
    conflict: ClaimConflict,
) -> tuple[dict[str, float], dict[str, bool]]:
    per_document: dict[str, dict[str, float]] = defaultdict(dict)
    verified: dict[str, bool] = defaultdict(bool)
    for claim in conflict.claims:
        current = per_document[claim.value].get(claim.doc_id, 0.0)
        per_document[claim.value][claim.doc_id] = max(current, claim.trust_score)
        verified[claim.value] = verified[claim.value] or claim.verified
    scores = {
        value: sum(document_scores.values()) for value, document_scores in per_document.items()
    }
    return scores, dict(verified)


def _normalize_value(value: str) -> str:
    normalized = value.replace(",", "")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized


def _normalize_unit(unit: str) -> str:
    lowered = unit.lower()
    return _UNIT_ALIASES.get(lowered, lowered)


def _numeric_sort_key(value: str) -> float:
    return float(value)
