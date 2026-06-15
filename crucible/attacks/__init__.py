"""Adversarial document generators for the security suite (DESIGN.md §5.5).

Scope and ethics (DESIGN.md §9, guardrails): every payload here is generic and
educational — the point is to evaluate and harden *this* project's own
pipeline, not to provide operational attacks. Poison documents assert an
obviously-synthetic false value; injection documents carry a benign
``OWNED-{qid}`` compliance token whose only purpose is to be detected. All
generation is seeded and deterministic so graders reproduce the same attacks.
"""

from crucible.attacks.injection import InjectionAttack, generate_injection_attacks
from crucible.attacks.poison import PoisonAttack, generate_poison_attacks
from crucible.attacks.targets import INJECT_SOURCE_PREFIX, POISON_SOURCE_PREFIX, select_targets

__all__ = [
    "INJECT_SOURCE_PREFIX",
    "POISON_SOURCE_PREFIX",
    "InjectionAttack",
    "PoisonAttack",
    "generate_injection_attacks",
    "generate_poison_attacks",
    "select_targets",
]
