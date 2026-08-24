"""The one place the system reads a calendar."""

from __future__ import annotations

from datetime import UTC, date, datetime

from kira.config import get_settings


def today_for() -> date:
    """Return today's date, or the pinned demo date when configured."""
    settings = get_settings()
    if settings.demo_today is not None:
        return settings.demo_today
    return datetime.now(UTC).date()
