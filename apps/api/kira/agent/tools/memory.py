"""The Butler's memory, as tools the user can direct.

Passive extraction writes to `butler_memories` on its own (see
`nodes/memory.py`); these two are the explicit, user-directed path, and they
are writes like any other — "remember that" is a request the user gets to
confirm in the same words Kira will keep.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from kira.agent.tools.spec import EvidenceRow, ToolContext, ToolResult, ToolSpec
from kira.db.models import MEMORY_KINDS
from kira.services import butler_memory

MODULE = "memory"


class RememberArgs(BaseModel):
    kind: str = Field(description=f"One of: {', '.join(MEMORY_KINDS)}.")
    subject: str = Field(
        min_length=1,
        max_length=80,
        description="A short noun phrase naming what the fact is about, e.g. 'housemate'.",
    )
    fact: str = Field(
        min_length=1,
        max_length=280,
        description="One sentence, written so the user would recognise it as their own.",
    )
    confidence: int = Field(default=90, ge=0, le=100)


class ForgetArgs(BaseModel):
    memory_id: uuid.UUID = Field(description="The remembered fact to delete.")


async def _remember(ctx: ToolContext, args: RememberArgs) -> ToolResult:
    view = await butler_memory.remember(
        ctx.session,
        ctx.user,
        kind=args.kind,
        subject=args.subject,
        fact=args.fact,
        confidence=args.confidence,
    )
    return ToolResult(
        {"id": str(view.id), "fact": view.fact},
        (EvidenceRow("Remembered", view.fact),),
    )


async def _forget(ctx: ToolContext, args: ForgetArgs) -> ToolResult:
    view = await butler_memory.forget(ctx.session, ctx.user, args.memory_id)
    return ToolResult(
        {"id": str(view.id)},
        (EvidenceRow("Forgotten", view.fact),),
    )


SPECS = (
    ToolSpec(
        name="remember",
        module=MODULE,
        kind="write",
        label="Remembering that",
        description=(
            "Keep a durable fact about the user that should shape future answers. Use "
            "it when they ask to be remembered, or state a standing rule."
        ),
        args_model=RememberArgs,
        handler=_remember,
        summarise=lambda args: f"Remember: {args.fact}",
    ),
    ToolSpec(
        name="forget",
        module=MODULE,
        kind="write",
        label="Forgetting that",
        description="Delete a remembered fact by id.",
        args_model=ForgetArgs,
        handler=_forget,
        summarise=lambda args: f"Forget memory {args.memory_id}.",
    ),
)
