"""Pure goal projections."""

from __future__ import annotations

from kira.money import Money


def months_to_goal(target: Money, saved: Money, monthly: Money) -> int:
    """Return whole months to fund a goal, rounding part-months up."""
    if monthly.sen <= 0:
        raise ValueError("monthly contribution must be positive")
    remaining = (target - saved).sen
    if remaining <= 0:
        return 1
    return max(1, -(-remaining // monthly.sen))
