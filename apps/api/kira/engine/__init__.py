"""Pure finance calculations. This package imports nothing from the rest of Kira."""

from kira.engine.goals import months_to_goal
from kira.engine.safe_to_spend import safe_to_spend
from kira.engine.types import CommitmentInput, GoalInput, SafeToSpend, Snapshot

__all__ = [
    "CommitmentInput",
    "GoalInput",
    "SafeToSpend",
    "Snapshot",
    "months_to_goal",
    "safe_to_spend",
]
