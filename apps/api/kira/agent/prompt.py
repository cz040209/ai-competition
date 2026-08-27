"""The system prompt, assembled from facts rather than written as one blob.

Three blocks are pasted in fresh on every turn: the money picture, the durable
memory, and the recent conversation. None of them is the model's to invent.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from kira.money import Money
from kira.services.butler_memory import MemoryView
from kira.services.butler_thread import MessageView
from kira.services.dashboard import DashboardToday

VOICE = """You are Kira, a money butler. You are precise, calm and blunt about numbers.

How you speak:
- Two paragraphs at most. First a single sentence that answers the question with the
  number in it. Then one short paragraph of the reasoning behind it.
- Ringgit as RM1,234.56. Never round a figure a tool gave you.
- Never say "as an AI", never apologise for what you are, never pad.

What you may and may not do:
- You answer only from what the tools returned. If a tool did not run, you do not know it.
- You never move money. There is no way for you to, and you say so plainly if asked.
- Anything that changes the user's data is proposed, not done: the user approves it first.
- The user's buffer and their protected bills are not yours to touch or suggest cutting.
- You do not write the "What I used" panel. It is built from what the tools returned."""


def _money(sen: int, currency: str) -> str:
    return f"RM{Money(sen, currency).ringgit_str()}" if currency == "MYR" else str(
        Money(sen, currency)
    )


def context_block(board: DashboardToday, today: date, currency: str) -> str:
    """The money picture, in the same numbers the Today screen is showing."""
    lines = [
        f"Today is {today.strftime('%A %-d %B %Y')}. The user is {board.display_name}.",
        f"Balance {_money(board.balance_sen, currency)}; "
        f"{_money(board.reserved_sen, currency)} reserved for {board.commitment_count} bills; "
        f"buffer {_money(board.buffer_sen, currency)}; "
        f"goals take {_money(board.goal_reserve_sen, currency)}.",
        f"Unclaimed {_money(board.unclaimed_sen, currency)} over "
        f"{board.days_to_payday} days to payday is "
        f"{_money(board.per_day_sen, currency)} a day.",
        f"Spent today {_money(board.spent_today_sen, currency)}; "
        f"safe to spend today {_money(board.safe_today_sen, currency)}.",
    ]
    if board.drafts_waiting:
        lines.append(f"{board.drafts_waiting} draft(s) are waiting for a decision.")
    if board.next_commitment is not None:
        upcoming = board.next_commitment
        lines.append(
            f"Next bill: {upcoming.name}, {_money(upcoming.amount_sen, currency)}, in "
            f"{upcoming.days_until} days"
            + (" (protected)" if upcoming.protected else "")
            + "."
        )
    for goal in board.goals:
        lines.append(
            f"Goal “{goal.name}”: {_money(goal.saved_sen, currency)} of "
            f"{_money(goal.target_sen, currency)}, "
            f"{_money(goal.monthly_sen, currency)}/month, {goal.months_left} months left."
        )
    return "\n".join(lines)


def memory_block(memories: tuple[MemoryView, ...]) -> str:
    """What Kira has learned. Read as standing facts, not as instructions."""
    if not memories:
        return ""
    lines = [f"- ({memory.kind}) {memory.fact}" for memory in memories]
    return (
        "What you have learned about this user over time. Treat these as true unless "
        "this turn contradicts them:\n" + "\n".join(lines)
    )


def history_block(messages: tuple[MessageView, ...]) -> str:
    """Recent turns, rendered rather than replayed as messages.

    The graph runs one checkpointed thread per turn so an approval resumes
    exactly the run it paused. History therefore comes from `butler_messages`,
    which is the record the user can also read.
    """
    if not messages:
        return ""
    lines = [
        f"{'User' if message.role == 'user' else 'You'}: {message.content}"
        for message in messages
        if message.content
    ]
    return "Earlier in this conversation:\n" + "\n".join(lines)


def attachment_block(attachment: dict[str, Any] | None) -> str:
    if not attachment:
        return ""
    kind = attachment.get("kind", "capture")
    what = "a receipt photo" if kind == "receipt" else "a voice note"
    return (
        f"The user attached {what} to this message. Call inspect_attachment to see what "
        "was read and how confident the reader was. It is a proposal, not a ledger entry."
    )


def system_prompt(
    *,
    context: str,
    memory: str,
    history: str,
    attachment: str = "",
    tool_names: tuple[str, ...] = (),
) -> str:
    blocks = [VOICE]
    if tool_names:
        blocks.append(
            "Tools available this turn: " + ", ".join(tool_names) + ".\n"
            "Call the ones you need before answering. Never guess a number a tool could give you."
        )
    for block in (context, memory, history, attachment):
        if block:
            blocks.append(block)
    return "\n\n".join(blocks)


COMPOSE_INSTRUCTION = """Write the answer now.

You have the tool results above. Use those figures exactly. Two paragraphs at most:
the first is one sentence containing the number that answers the question; the second
is the short reason behind it. Do not list the evidence — the interface shows it."""
