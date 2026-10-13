"""Shared helpers for attack generation: deterministic target selection and
the source-path prefixes that tag attack documents inside an index."""

from __future__ import annotations

import hashlib

from rag_crucible.qa import QAItem

POISON_SOURCE_PREFIX = "__poison__"
INJECT_SOURCE_PREFIX = "__inject__"


def select_targets(items: list[QAItem], n: int | None, seed: int) -> list[QAItem]:
    """Pick ``n`` QA items to attack (all if ``n`` is None or too large),
    using a stable, seed-keyed ranking independent of input order.

    Unlike ``random.sample``, an item's rank depends only on its qid and the
    run seed. Reordering the QA file or appending a lower-ranked question does
    not reshuffle the existing target set.
    """
    if n is None or n >= len(items):
        return sorted(items, key=lambda item: item.qid)
    chosen = sorted(items, key=lambda item: _target_score(item.qid, seed))[:n]
    return sorted(chosen, key=lambda item: item.qid)


def _target_score(qid: str, seed: int) -> bytes:
    return hashlib.sha256(f"{seed}\0{qid}".encode()).digest()
