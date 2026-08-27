"""What the Today screen knows, exposed to the Butler unchanged.

These read through the same `load_snapshot` and `today_dashboard` the screen
uses, so the Butler's view of money and the app's view of money cannot drift.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from kira.agent.tools.spec import EvidenceRow, ToolContext, ToolResult, ToolSpec, money_str
from kira.money import Money

MODULE = "dashboard"


class NoArgs(BaseModel):
    """Takes nothing: the snapshot is whatever is true right now."""


class AffordArgs(BaseModel):
    amount_sen: int = Field(
        gt=0, description="The amount being considered, in sen (RM1 is 100 sen)."
    )
    label: str = Field(
        default="",
        max_length=80,
        description="What the money would be spent on, e.g. 'dinner'.",
    )


async def _snapshot(ctx: ToolContext, _: NoArgs) -> ToolResult:
    board = ctx.dashboard
    currency = ctx.currency

    def money(sen: int) -> str:
        return money_str(Money(sen, currency))

    value = {
        "date": board.date.isoformat(),
        "balance_sen": board.balance_sen,
        "reserved_sen": board.reserved_sen,
        "buffer_sen": board.buffer_sen,
        "goal_reserve_sen": board.goal_reserve_sen,
        "unclaimed_sen": board.unclaimed_sen,
        "per_day_sen": board.per_day_sen,
        "spent_today_sen": board.spent_today_sen,
        "safe_today_sen": board.safe_today_sen,
        "days_to_payday": board.days_to_payday,
        "commitment_count": board.commitment_count,
        "drafts_waiting": board.drafts_waiting,
    }
    evidence = (
        EvidenceRow("Balance", money(board.balance_sen)),
        EvidenceRow("Reserved for bills", money(board.reserved_sen)),
        EvidenceRow("Buffer held back", money(board.buffer_sen)),
        EvidenceRow("Going to goals", money(board.goal_reserve_sen)),
        EvidenceRow("Days to payday", str(board.days_to_payday)),
        EvidenceRow("Safe to spend today", money(board.safe_today_sen)),
    )
    return ToolResult(value, evidence)


async def _afford(ctx: ToolContext, args: AffordArgs) -> ToolResult:
    board = ctx.dashboard
    currency = ctx.currency
    safe = Money(board.safe_today_sen, currency)
    amount = Money(args.amount_sen, currency)
    remaining = safe - amount
    # Overspending today is not forbidden, it is borrowed from the days left.
    days_left = max(1, board.days_to_payday)
    per_day_after = Money(board.per_day_sen, currency) + remaining.divide_floor(days_left)

    value = {
        "amount_sen": amount.sen,
        "safe_today_sen": safe.sen,
        "fits": remaining.sen >= 0,
        "remaining_sen": remaining.sen,
        "over_by_sen": max(0, -remaining.sen),
        "per_day_after_sen": per_day_after.sen,
        "days_to_payday": board.days_to_payday,
        "label": args.label,
    }
    evidence = (
        EvidenceRow("Safe to spend today", money_str(safe)),
        EvidenceRow(args.label.capitalize() or "Considering", money_str(amount)),
        EvidenceRow(
            "Left after it" if remaining.sen >= 0 else "Over by",
            money_str(remaining if remaining.sen >= 0 else -remaining),
        ),
        EvidenceRow("Daily room until payday", money_str(per_day_after)),
    )
    return ToolResult(value, evidence)


SPECS = (
    ToolSpec(
        name="get_financial_snapshot",
        module=MODULE,
        kind="read",
        label="Reading today's numbers",
        description=(
            "The user's whole money picture right now: balance, what is reserved for "
            "bills, the buffer, goal contributions, what is unclaimed, the daily "
            "allowance, what has been spent today and what is safe to spend. Call this "
            "before answering anything about money."
        ),
        args_model=NoArgs,
        handler=_snapshot,
    ),
    ToolSpec(
        name="calculate_safe_to_spend",
        module=MODULE,
        kind="read",
        label="Checking what today can take",
        description=(
            "Test one specific amount against today's room, and report what would be "
            "left and what the daily allowance becomes for the rest of the cycle. Use "
            "this for 'can I afford…' questions."
        ),
        args_model=AffordArgs,
        handler=_afford,
    ),
)
