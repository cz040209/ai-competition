"""Turns a JSON golden case into engine inputs and an expected-output dict."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from kira.engine.types import CommitmentInput, GoalInput, Snapshot
from kira.money import Money

CASES_DIR = Path(__file__).parent / "cases"


def load_cases() -> list[tuple[str, dict[str, Any]]]:
    return [(path.stem, json.loads(path.read_text())) for path in sorted(CASES_DIR.glob("*.json"))]


def build_snapshot(spec: dict[str, Any]) -> Snapshot:
    currency = spec.get("currency", "MYR")
    return Snapshot(
        balance=Money(spec["balance"], currency),
        buffer=Money(spec["buffer"], currency),
        spent_today=Money(spec["spent_today"], currency),
        commitments=tuple(
            CommitmentInput(
                c["id"], Money(c["amount"], currency), date.fromisoformat(c["due_date"])
            )
            for c in spec["commitments"]
        ),
        goals=tuple(
            GoalInput(g["id"], Money(g["monthly"], currency)) for g in spec["goals"]
        ),
        today=date.fromisoformat(spec["today"]),
        next_payday=date.fromisoformat(spec["next_payday"]),
        cycle_start=date.fromisoformat(spec["cycle_start"]),
        cycle_days=spec["cycle_days"],
    )


def actual_output(result) -> dict[str, int]:
    """Flatten a SafeToSpend into the plain-int shape the golden files record."""
    return {
        "days_to_payday": result.days_to_payday,
        "cycle_elapsed": result.cycle_elapsed,
        "reserved": result.reserved.sen,
        "goal_reserve": result.goal_reserve.sen,
        "unclaimed": result.unclaimed.sen,
        "per_day": result.per_day.sen,
        "safe_today": result.safe_today.sen,
    }
