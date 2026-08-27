"""Durable, user-inspectable facts about the user.

Typed rows, no vectors: at this scale the whole working set fits in a prompt,
and a fact the user can read and correct is worth more than a fact that
retrieves marginally better.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import (
    MEMORY_ACTIVE,
    MEMORY_DELETED,
    MEMORY_KINDS,
    MEMORY_SUPERSEDED,
    ButlerMemory,
    User,
)

# Which kinds earn their place in the prompt first when the cap bites.
KIND_ORDER = ("constraint", "preference", "person", "pattern", "context")
KIND_PRIORITY = {kind: index for index, kind in enumerate(KIND_ORDER)}


class MemoryNotFound(Exception):
    """No such memory belongs to this user."""


class InvalidMemory(Exception):
    """The proposed fact is not something worth remembering."""


@dataclass(frozen=True, slots=True)
class MemoryView:
    id: uuid.UUID
    kind: str
    subject: str
    fact: str
    confidence: int
    source_message_id: uuid.UUID | None
    created_at: datetime
    last_used_at: datetime | None


def _view(memory: ButlerMemory) -> MemoryView:
    return MemoryView(
        id=memory.id,
        kind=memory.kind,
        subject=memory.subject,
        fact=memory.fact,
        confidence=memory.confidence,
        source_message_id=memory.source_message_id,
        created_at=memory.created_at,
        last_used_at=memory.last_used_at,
    )


def _now() -> datetime:
    return datetime.now(tz=UTC)


async def _owned(session: AsyncSession, user: User, memory_id: uuid.UUID) -> ButlerMemory:
    memory = (
        await session.execute(
            select(ButlerMemory).where(
                ButlerMemory.id == memory_id, ButlerMemory.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if memory is None or memory.status == MEMORY_DELETED:
        raise MemoryNotFound(str(memory_id))
    return memory


async def remember(
    session: AsyncSession,
    user: User,
    *,
    kind: str,
    subject: str,
    fact: str,
    confidence: int = 70,
    source_message_id: uuid.UUID | None = None,
) -> MemoryView:
    """Write a fact, superseding any active fact with the same (kind, subject).

    Superseding rather than overwriting keeps the trail of what Kira believed
    and when — the same discipline the ledger applies to money.
    """
    if kind not in MEMORY_KINDS:
        raise InvalidMemory(f"kind must be one of {MEMORY_KINDS}")
    if not subject.strip() or not fact.strip():
        raise InvalidMemory("a memory needs both a subject and a fact")
    if not 0 <= confidence <= 100:
        raise InvalidMemory("confidence is a percentage")

    subject = subject.strip()[:80]
    fresh = ButlerMemory(
        user_id=user.id,
        kind=kind,
        subject=subject,
        fact=fact.strip(),
        confidence=confidence,
        source_message_id=source_message_id,
        status=MEMORY_ACTIVE,
    )
    session.add(fresh)
    await session.flush()

    await session.execute(
        update(ButlerMemory)
        .where(
            ButlerMemory.user_id == user.id,
            ButlerMemory.kind == kind,
            ButlerMemory.subject == subject,
            ButlerMemory.status == MEMORY_ACTIVE,
            ButlerMemory.id != fresh.id,
        )
        .values(status=MEMORY_SUPERSEDED, superseded_by=fresh.id)
    )
    await session.flush()
    return _view(fresh)


async def list_memories(
    session: AsyncSession, user: User, limit: int | None = None
) -> tuple[MemoryView, ...]:
    """Active facts, most load-bearing kinds first, then most recently used."""
    memories = (
        await session.execute(
            select(ButlerMemory).where(
                ButlerMemory.user_id == user.id, ButlerMemory.status == MEMORY_ACTIVE
            )
        )
    ).scalars().all()
    ordered = sorted(
        memories,
        key=lambda memory: (
            KIND_PRIORITY.get(memory.kind, len(KIND_PRIORITY)),
            -(memory.last_used_at or memory.created_at).timestamp(),
            memory.subject,
        ),
    )
    if limit is not None:
        ordered = ordered[:limit]
    return tuple(_view(memory) for memory in ordered)


async def correct(
    session: AsyncSession, user: User, memory_id: uuid.UUID, fact: str
) -> MemoryView:
    memory = await _owned(session, user, memory_id)
    if not fact.strip():
        raise InvalidMemory("a memory needs a fact")
    memory.fact = fact.strip()
    memory.confidence = 100  # the user said it; nothing is more certain than that
    await session.flush()
    return _view(memory)


async def forget(session: AsyncSession, user: User, memory_id: uuid.UUID) -> MemoryView:
    memory = await _owned(session, user, memory_id)
    memory.status = MEMORY_DELETED
    await session.flush()
    return _view(memory)


async def touch(session: AsyncSession, user: User, memory_ids: list[uuid.UUID]) -> None:
    """Mark facts as used, so the retained working set converges on what matters."""
    if not memory_ids:
        return
    await session.execute(
        update(ButlerMemory)
        .where(ButlerMemory.user_id == user.id, ButlerMemory.id.in_(memory_ids))
        .values(last_used_at=_now())
    )
