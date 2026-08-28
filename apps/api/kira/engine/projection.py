"""Where the money goes next. Pure: no I/O, no clock, no float.

``project`` walks the median path. ``simulate`` walks it many times with the
user's own observed variation and reports a band and a probability per goal.
"""

from __future__ import annotations

from datetime import date, timedelta

from kira.engine.prng import Prng
from kira.engine.types import (
    DailySpendProfile,
    GoalInput,
    GoalOutlook,
    Projection,
    ProjectionDay,
    Simulation,
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


DEFAULT_TRIALS = 2000
DEFAULT_SEED = 20260828

_P10, _P50, _P90 = 10, 50, 90


def _percentile(sorted_values: list[int], percentile: int) -> int:
    """The value at ``percentile`` of an ascending list, by nearest rank.

    Integer throughout: the index is rounded half-up, never divided.
    """
    if not sorted_values:
        return 0
    last = len(sorted_values) - 1
    return sorted_values[round_half_up(percentile * last, 100)]


def _datable_goals(snapshot: Snapshot, days: int) -> tuple[GoalInput, ...]:
    """Goals with a target date inside the horizon. Others get no probability:
    "will I make it" is not a question until there is a "by when"."""
    horizon_end = snapshot.today + timedelta(days=days)
    return tuple(
        goal
        for goal in snapshot.goals
        if goal.target_date is not None and snapshot.today < goal.target_date <= horizon_end
    )


def simulate(
    snapshot: Snapshot,
    profile: DailySpendProfile,
    days: int,
    trials: int = DEFAULT_TRIALS,
    seed: int = DEFAULT_SEED,
) -> Simulation:
    """Walk the horizon ``trials`` times, resampling this user's own spending.

    Each day's discretionary spend is drawn by integer index from what the user
    actually spent on that weekday — no fitted distribution, no assumption of
    symmetry, and no float anywhere in the arithmetic.

    A goal is funded out of what is actually there: each day it takes its daily
    accrual from the balance above the buffer, less whatever this projection has
    already earmarked. Money set aside cannot be set aside twice, and a month
    that empties the account is a month the goal does not grow.
    """
    if isinstance(trials, bool) or not isinstance(trials, int):
        raise TypeError("trials must be an int")
    if trials <= 0:
        raise ValueError("trials must be positive")

    median = project(snapshot, profile, days)
    currency = snapshot.currency
    goals = _datable_goals(snapshot, days)
    accrual_for = {
        goal.id: round_half_up(goal.monthly.sen, snapshot.cycle_days) for goal in goals
    }
    buffer_sen = snapshot.buffer.sen

    closings: list[list[int]] = [[] for _ in range(days)]
    shortfalls: dict[str, list[int]] = {goal.id: [] for goal in goals}
    met: dict[str, int] = {goal.id: 0 for goal in goals}

    stream = Prng(seed)
    for _ in range(trials):
        balance = snapshot.balance.sen
        saved = {goal.id: goal.saved.sen for goal in goals}
        earmarked = 0
        for index, day in enumerate(median.days):
            observed = profile.by_weekday[day.on.weekday()]
            spend = observed[stream.below(len(observed))] if observed else 0
            balance += day.income.sen - day.commitments_due.sen - spend
            closings[index].append(balance)

            for goal in goals:
                if day.on > goal.target_date:
                    continue
                available = balance - buffer_sen - earmarked
                if available <= 0:
                    continue
                take = min(accrual_for[goal.id], available)
                saved[goal.id] += take
                earmarked += take

        for goal in goals:
            gap = goal.target.sen - saved[goal.id]
            if gap <= 0:
                met[goal.id] += 1
                shortfalls[goal.id].append(0)
            else:
                shortfalls[goal.id].append(gap)

    for column in closings:
        column.sort()
    for values in shortfalls.values():
        values.sort()

    bands = Projection(
        days=median.days,
        p10=tuple(Money(_percentile(column, _P10), currency) for column in closings),
        p50=tuple(Money(_percentile(column, _P50), currency) for column in closings),
        p90=tuple(Money(_percentile(column, _P90), currency) for column in closings),
    )
    outlooks = tuple(
        GoalOutlook(
            goal_id=goal.id,
            target_date=goal.target_date,
            probability_bp=round_half_up(met[goal.id] * 10000, trials),
            median_shortfall=Money(_percentile(shortfalls[goal.id], _P50), currency),
        )
        for goal in goals
    )

    return Simulation(bands=bands, outlooks=outlooks, trials=trials, seed=seed)
