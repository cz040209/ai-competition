"""Where the money goes next. Pure: no I/O, no clock, no float.

``project`` walks the median path. ``simulate`` walks it many times with the
user's own observed variation and reports a band and a probability per goal.
"""

from __future__ import annotations

from datetime import date, timedelta

from kira.engine.types import (
    DailySpendProfile,
    Projection,
    ProjectionDay,
    Snapshot,
)
from kira.money import Money, round_half_up


def _payday_dates(snapshot: Snapshot, days: int) -> frozenset[date]:
    """Payday, and every cycle length after it, within the horizon."""
    last = snapshot.today + timedelta(days=days)
    paydays: set[date] = set()
    when = snapshot.next_payday
    while when <= last:
        if when > snapshot.today:
            paydays.add(when)
        when += timedelta(days=snapshot.cycle_days)
    return frozenset(paydays)


def _daily_goal_accrual(snapshot: Snapshot) -> Money:
    """Each goal's monthly contribution, spread over the cycle and rounded once."""
    currency = snapshot.currency
    return Money.sum(
        (
            Money(round_half_up(goal.monthly.sen, snapshot.cycle_days), currency)
            for goal in snapshot.goals
        ),
        currency,
    )


def _commitments_by_day(snapshot: Snapshot) -> dict[date, Money]:
    """Bills still ahead of us. Anything already due has already been paid."""
    currency = snapshot.currency
    due: dict[date, Money] = {}
    for commitment in snapshot.commitments:
        if commitment.due_date > snapshot.today:
            due[commitment.due_date] = (
                due.get(commitment.due_date, Money.zero(currency)) + commitment.amount
            )
    return due


def project(snapshot: Snapshot, profile: DailySpendProfile, days: int) -> Projection:
    """The median path over ``days`` days, starting the day after ``snapshot.today``."""
    if isinstance(days, bool) or not isinstance(days, int):
        raise TypeError("days must be an int")
    if days <= 0:
        raise ValueError("days must be positive")

    currency = snapshot.currency
    paydays = _payday_dates(snapshot, days)
    accrual = _daily_goal_accrual(snapshot)
    due = _commitments_by_day(snapshot)

    walked: list[ProjectionDay] = []
    balance = snapshot.balance
    for step in range(1, days + 1):
        on = snapshot.today + timedelta(days=step)
        income = snapshot.income if on in paydays else Money.zero(currency)
        commitments_due = due.get(on, Money.zero(currency))
        spend = Money(profile.median_for(on.weekday()), currency)
        opening = balance
        balance = opening + income - commitments_due - spend
        walked.append(
            ProjectionDay(
                on=on,
                opening=opening,
                income=income,
                commitments_due=commitments_due,
                expected_spend=spend,
                goal_accrual=accrual,
                closing=balance,
            )
        )

    return Projection(days=tuple(walked))
