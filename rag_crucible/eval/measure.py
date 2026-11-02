"""Turn a sample into a ``Metric`` without inventing a value for an empty one.

Every rate a suite emits goes through these two functions (a count, such as
the privacy suite's dropped-canary tally, is built directly), and neither
averages an empty sample: ``rate`` takes the state and reason an empty sample gets from
its caller, which knows why it is empty (no labels, nothing configured,
nothing recorded), and records the sample size and the units set aside with
the value. ``rag_crucible.eval.catalog`` documents each metric's eligibility
and what an empty sample means for it.
"""

from __future__ import annotations

from collections.abc import Sequence

from rag_crucible.eval.metrics import mean
from rag_crucible.eval.types import Metric, NotMeasuredState


def rate(
    suite: str,
    name: str,
    values: Sequence[float],
    *,
    empty: tuple[NotMeasuredState, str],
    variant: str = "",
    excluded: int = 0,
) -> Metric:
    """The mean of ``values`` over ``n = len(values)`` units, ``excluded``
    more having been set aside as ineligible; ``empty`` when there are none."""
    if not values:
        state, reason = empty
        return not_measured(
            suite, name, state=state, reason=reason, variant=variant, n=0, excluded=excluded
        )
    return Metric(
        suite=suite,
        name=name,
        variant=variant,
        value=round(mean(values), 4),
        n=len(values),
        n_excluded=excluded,
    )


def not_measured(
    suite: str,
    name: str,
    *,
    state: NotMeasuredState,
    reason: str,
    variant: str = "",
    n: int | None = None,
    excluded: int | None = None,
) -> Metric:
    """A metric with no value: what it is instead, and why."""
    return Metric(
        suite=suite,
        name=name,
        variant=variant,
        value=None,
        state=state,
        reason=reason,
        n=n,
        n_excluded=excluded,
    )
