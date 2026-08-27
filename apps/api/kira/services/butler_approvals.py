"""The approval projection: what the Butler proposed, and what became of it.

A strict projection of a LangGraph interrupt. Only the resume path transitions
a row's status, so the row and the checkpoint cannot disagree about what was
decided — and the row is readable in SQL, which the checkpoint is not.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import (
    APPROVAL_APPLIED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    ButlerApproval,
    User,
)


class ApprovalNotFound(Exception):
    """No such approval belongs to this user."""


class ApprovalSettled(Exception):
    """That approval has already been decided."""


@dataclass(frozen=True, slots=True)
class ApprovalView:
    id: uuid.UUID
    thread_id: uuid.UUID
    tool: str
    args: dict[str, Any]
    summary: str
    evidence: tuple[tuple[str, str], ...]
    status: str
    graph_thread_id: str
    tool_call_id: str
    created_at: datetime


def view(approval: ButlerApproval) -> ApprovalView:
    return ApprovalView(
        id=approval.id,
        thread_id=approval.thread_id,
        tool=approval.tool,
        args=approval.args or {},
        summary=approval.summary,
        evidence=tuple((row[0], row[1]) for row in (approval.evidence or [])),
        status=approval.status,
        graph_thread_id=approval.graph_thread_id,
        tool_call_id=approval.tool_call_id,
        created_at=approval.created_at,
    )


async def propose(
    session: AsyncSession,
    user: User,
    *,
    thread_id: uuid.UUID,
    tool: str,
    args: dict[str, Any],
    summary: str,
    evidence: list[list[str]],
    graph_thread_id: str,
    tool_call_id: str,
) -> ButlerApproval:
    """Record the proposal, or return the one already recorded.

    A resumed graph replays the node from its start, so this has to be
    idempotent on (graph thread, tool call) or a single question would be
    asked twice.
    """
    existing = (
        await session.execute(
            select(ButlerApproval).where(
                ButlerApproval.user_id == user.id,
                ButlerApproval.graph_thread_id == graph_thread_id,
                ButlerApproval.tool_call_id == tool_call_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    approval = ButlerApproval(
        user_id=user.id,
        thread_id=thread_id,
        tool=tool,
        args=args,
        summary=summary,
        evidence=evidence,
        status=APPROVAL_PENDING,
        graph_thread_id=graph_thread_id,
        tool_call_id=tool_call_id,
    )
    session.add(approval)
    await session.flush()
    return approval


async def get(session: AsyncSession, user: User, approval_id: uuid.UUID) -> ButlerApproval:
    approval = (
        await session.execute(
            select(ButlerApproval).where(
                ButlerApproval.id == approval_id, ButlerApproval.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if approval is None:
        raise ApprovalNotFound(str(approval_id))
    return approval


async def pending_for(session: AsyncSession, user: User) -> tuple[ApprovalView, ...]:
    rows = (
        await session.execute(
            select(ButlerApproval)
            .where(
                ButlerApproval.user_id == user.id,
                ButlerApproval.status == APPROVAL_PENDING,
            )
            .order_by(ButlerApproval.created_at)
        )
    ).scalars().all()
    return tuple(view(row) for row in rows)


async def settle(
    session: AsyncSession,
    approval: ButlerApproval,
    *,
    applied: bool,
    args: dict[str, Any] | None = None,
    audit_event_id: uuid.UUID | None = None,
) -> ButlerApproval:
    if approval.status != APPROVAL_PENDING:
        raise ApprovalSettled(approval.status)
    if args is not None:
        approval.args = args
    approval.status = APPROVAL_APPLIED if applied else APPROVAL_REJECTED
    approval.decided_at = datetime.now(tz=UTC)
    approval.audit_event_id = audit_event_id
    await session.flush()
    return approval
