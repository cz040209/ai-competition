"""The record of who changed what. Append-only by convention, never edited."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import AuditEvent, User

ACTOR_USER = "user"
ACTOR_BUTLER = "butler"


async def record(
    session: AsyncSession,
    user: User,
    *,
    actor: str,
    action: str,
    detail: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(user_id=user.id, actor=actor, action=action, detail=detail or {})
    session.add(event)
    await session.flush()
    return event


async def recent(session: AsyncSession, user: User, limit: int = 50) -> tuple[AuditEvent, ...]:
    rows = (
        await session.execute(
            select(AuditEvent)
            .where(AuditEvent.user_id == user.id)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
            .limit(limit)
        )
    ).scalars().all()
    return tuple(rows)
