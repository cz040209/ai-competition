"""Commitments: the bills that are reserved before anything is safe to spend."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import Commitment, User
from kira.money import Money


class CommitmentNotFound(Exception):
    """No such commitment belongs to this user."""


class InvalidCommitment(Exception):
    """The proposed commitment is not a bill that can be reserved for."""


class CommitmentProtected(Exception):
    """A protected commitment is not the Butler's to change."""


@dataclass(frozen=True, slots=True)
class CommitmentView:
    id: uuid.UUID
    name: str
    amount_sen: int
    due_date: date
    days_until: int
    protected: bool


def _view(commitment: Commitment, today: date) -> CommitmentView:
    return CommitmentView(
        id=commitment.id,
        name=commitment.name,
        amount_sen=commitment.amount.sen,
        due_date=commitment.due_date,
        days_until=(commitment.due_date - today).days,
        protected=commitment.protected,
    )


async def _owned(session: AsyncSession, user: User, commitment_id: uuid.UUID) -> Commitment:
    commitment = (
        await session.execute(
            select(Commitment).where(
                Commitment.id == commitment_id, Commitment.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if commitment is None:
        raise CommitmentNotFound(str(commitment_id))
    return commitment


async def list_commitments(
    session: AsyncSession, user: User, today: date, *, upcoming_only: bool = False
) -> tuple[CommitmentView, ...]:
    commitments = (
        await session.execute(
            select(Commitment)
            .where(Commitment.user_id == user.id)
            .order_by(Commitment.due_date, Commitment.name)
        )
    ).scalars().all()
    return tuple(
        _view(commitment, today)
        for commitment in commitments
        if not upcoming_only or commitment.due_date >= today
    )


async def create_commitment(
    session: AsyncSession,
    user: User,
    *,
    name: str,
    amount_sen: int,
    due_date: date,
    protected: bool = False,
) -> CommitmentView:
    if not name.strip():
        raise InvalidCommitment("a commitment needs a name")
    if amount_sen <= 0:
        raise InvalidCommitment("a commitment needs a positive amount")
    commitment = Commitment(
        user_id=user.id,
        name=name.strip(),
        amount=Money(amount_sen, user.currency),
        due_date=due_date,
        protected=protected,
    )
    session.add(commitment)
    await session.flush()
    return _view(commitment, due_date)


async def update_commitment(
    session: AsyncSession,
    user: User,
    commitment_id: uuid.UUID,
    today: date,
    *,
    name: str | None = None,
    amount_sen: int | None = None,
    due_date: date | None = None,
) -> CommitmentView:
    """Change a bill. Protected bills refuse every change, from any caller."""
    commitment = await _owned(session, user, commitment_id)
    if commitment.protected:
        raise CommitmentProtected(commitment.name)
    if name is not None:
        if not name.strip():
            raise InvalidCommitment("a commitment needs a name")
        commitment.name = name.strip()
    if amount_sen is not None:
        if amount_sen <= 0:
            raise InvalidCommitment("a commitment needs a positive amount")
        commitment.amount = Money(amount_sen, user.currency)
    if due_date is not None:
        commitment.due_date = due_date
    await session.flush()
    return _view(commitment, today)
