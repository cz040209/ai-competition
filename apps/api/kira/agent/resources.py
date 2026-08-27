"""Building the ToolContext once per run, and rebuilding it after a resume.

An approved write resumes a checkpoint that may have been created minutes ago
in another process, so the snapshot cannot be carried in the state. It is
rebuilt here, from the database, at the moment it is needed.
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from kira.agent.state import ButlerContext
from kira.agent.tools import ToolContext
from kira.services.dashboard import DashboardToday, today_dashboard
from kira.services.snapshot import load_snapshot


async def dashboard_for(runtime: Runtime[ButlerContext]) -> DashboardToday:
    context = runtime.context
    board = context.cache.get("board")
    if board is None:
        board = await today_dashboard(context.session, context.user, context.today)
        context.cache["board"] = board
    return board


async def tool_context(
    runtime: Runtime[ButlerContext], attachment: dict[str, Any] | None = None
) -> ToolContext:
    context = runtime.context
    board = await dashboard_for(runtime)
    snapshot = context.cache.get("snapshot")
    if snapshot is None:
        snapshot = await load_snapshot(context.session, context.user, context.today)
        context.cache["snapshot"] = snapshot
    return ToolContext(
        session=context.session,
        user=context.user,
        today=context.today,
        snapshot=snapshot,
        dashboard=board,
        attachment=attachment,
    )


def invalidate(runtime: Runtime[ButlerContext]) -> None:
    """After a write, the cached money picture is a lie. Drop it."""
    runtime.context.cache.pop("board", None)
    runtime.context.cache.pop("snapshot", None)
