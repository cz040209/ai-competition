"""Shared serialization for the exact engine input behind a daily advice row."""

from __future__ import annotations

from kira.engine.types import Snapshot


def snapshot_json(snapshot: Snapshot) -> dict:
    """Make an engine snapshot durable without converting money to floats."""
    return {
        "balance": snapshot.balance.sen,
        "buffer": snapshot.buffer.sen,
        "spent_today": snapshot.spent_today.sen,
        "income": snapshot.income.sen,
        "today": snapshot.today.isoformat(),
        "next_payday": snapshot.next_payday.isoformat(),
        "cycle_start": snapshot.cycle_start.isoformat(),
        "cycle_days": snapshot.cycle_days,
        "commitments": [
            {"id": item.id, "amount": item.amount.sen, "due_date": item.due_date.isoformat()}
            for item in snapshot.commitments
        ],
        "goals": [{"id": item.id, "monthly": item.monthly.sen} for item in snapshot.goals],
    }
