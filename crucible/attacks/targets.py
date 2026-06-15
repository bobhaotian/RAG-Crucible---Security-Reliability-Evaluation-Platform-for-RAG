"""Shared helpers for attack generation: deterministic target selection and
the source-path prefixes that tag attack documents inside an index."""

from __future__ import annotations

import random

from crucible.qa import QAItem

POISON_SOURCE_PREFIX = "__poison__"
INJECT_SOURCE_PREFIX = "__inject__"


def select_targets(items: list[QAItem], n: int | None, seed: int) -> list[QAItem]:
    """Pick ``n`` QA items to attack (all if ``n`` is None or too large),
    deterministically and stably ordered by qid."""
    if n is None or n >= len(items):
        return sorted(items, key=lambda item: item.qid)
    chosen = random.Random(seed).sample(items, n)
    return sorted(chosen, key=lambda item: item.qid)
