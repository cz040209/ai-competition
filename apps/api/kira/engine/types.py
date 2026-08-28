"""Inputs and outputs of the finance engine. Plain data, no behaviour."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from kira.money import CurrencyMismatch, Money


@dataclass(frozen=True, slots=True)
class GoalInput:
    """A savings goal's claim on the cycle, expressed as its monthly contribution."""

    id: str
    monthly: Money


@dataclass(frozen=True, slots=True)
class CommitmentInput:
    """A known bill and the day it falls due."""

    id: str
    amount: Money
    due_date: date


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Everything the engine needs. Assembled by the caller; the engine reads no clock."""

    balance: Money
    buffer: Money
    spent_today: Money
    commitments: tuple[CommitmentInput, ...]
    goals: tuple[GoalInput, ...]
    today: date
    next_payday: date
    cycle_start: date
    cycle_days: int
    # What lands on each payday. Zero by default, so safe_to_spend and every
    # golden fixture — none of which look past the next payday — are untouched.
    income: Money = Money(0)

    def __post_init__(self) -> None:
        if self.cycle_days <= 0:
            raise ValueError("cycle_days must be positive")
        currency = self.balance.currency
        others = [self.buffer, self.spent_today, self.income]
        others += [c.amount for c in self.commitments]
        others += [g.monthly for g in self.goals]
        for amount in others:
            if amount.currency != currency:
                raise CurrencyMismatch(
                    f"snapshot mixes {currency} with {amount.currency}"
                )

    @property
    def currency(self) -> str:
        return self.balance.currency


@dataclass(frozen=True, slots=True)
class SafeToSpend:
    """The engine's answer, with every intermediate the UI shows in 'the working'."""

    days_to_payday: int
    cycle_elapsed: int
    balance: Money
    reserved: Money
    buffer: Money
    goal_reserve: Money
    unclaimed: Money
    per_day: Money
    spent_today: Money
    safe_today: Money
