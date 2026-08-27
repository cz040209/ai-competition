"""The conversation itself: one thread per user, and the turns inside it."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import ROLE_KIRA, ROLE_USER, ButlerMessage, ButlerThread, User

DEFAULT_HISTORY = 12


class ThreadNotFound(Exception):
    """No such thread belongs to this user."""


@dataclass(frozen=True, slots=True)
class MessageView:
    id: uuid.UUID
    role: str
    content: str
    evidence: tuple[tuple[str, str], ...]
    attachment: dict[str, Any] | None
    created_at: datetime


def _view(message: ButlerMessage) -> MessageView:
    return MessageView(
        id=message.id,
        role=message.role,
        content=message.content,
        evidence=tuple((row[0], row[1]) for row in (message.evidence or [])),
        attachment=message.attachment,
        created_at=message.created_at,
    )


async def ensure_thread(session: AsyncSession, user: User) -> ButlerThread:
    """One conversation per user by default; created on first use."""
    thread = (
        await session.execute(
            select(ButlerThread)
            .where(ButlerThread.user_id == user.id)
            .order_by(ButlerThread.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if thread is None:
        thread = ButlerThread(user_id=user.id, title="Butler")
        session.add(thread)
        await session.flush()
    return thread


async def get_thread(session: AsyncSession, user: User, thread_id: uuid.UUID) -> ButlerThread:
    thread = (
        await session.execute(
            select(ButlerThread).where(
                ButlerThread.id == thread_id, ButlerThread.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if thread is None:
        raise ThreadNotFound(str(thread_id))
    return thread


async def append(
    session: AsyncSession,
    user: User,
    thread: ButlerThread,
    *,
    role: str,
    content: str,
    evidence: list[list[str]] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    attachment: dict[str, Any] | None = None,
) -> MessageView:
    if role not in (ROLE_USER, ROLE_KIRA):
        raise ValueError(f"unknown role {role!r}")
    message = ButlerMessage(
        thread_id=thread.id,
        user_id=user.id,
        role=role,
        content=content,
        evidence=evidence or [],
        tool_calls=tool_calls or [],
        attachment=attachment,
    )
    session.add(message)
    await session.flush()
    return _view(message)


async def messages(
    session: AsyncSession, thread: ButlerThread, limit: int | None = None
) -> tuple[MessageView, ...]:
    """The thread in order. `limit` returns the most recent turns, still in order."""
    query = select(ButlerMessage).where(ButlerMessage.thread_id == thread.id)
    if limit is None:
        rows = (
            await session.execute(
                query.order_by(ButlerMessage.created_at, ButlerMessage.id)
            )
        ).scalars().all()
    else:
        rows = list(
            reversed(
                (
                    await session.execute(
                        query.order_by(
                            ButlerMessage.created_at.desc(), ButlerMessage.id.desc()
                        ).limit(limit)
                    )
                ).scalars().all()
            )
        )
    return tuple(_view(row) for row in rows)
