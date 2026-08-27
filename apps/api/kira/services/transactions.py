"""Read the ledger, and settle drafts. The only place a transaction's status moves."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from itertools import groupby

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.categories import label_for
from kira.db.models import (
    SOURCE_MANUAL,
    TXN_CONFIRMED,
    TXN_DISCARDED,
    TXN_DRAFT,
    Transaction,
    User,
)
from kira.money import Money


class TransactionNotFound(Exception):
    """No such transaction belongs to this user."""


class AlreadySettled(Exception):
    """The transaction has already been confirmed or discarded."""


class NotConfirmed(Exception):
    """Only a confirmed transaction can be returned to the drafts."""


class InvalidTransaction(Exception):
    """The proposed transaction is not something that can go on the ledger."""


@dataclass(frozen=True, slots=True)
class TransactionView:
    id: uuid.UUID
    merchant: str
    amount_sen: int
    category: str
    category_label: str
    occurred_on: date
    status: str
    source: str
    confidence: int | None
    note: str


@dataclass(frozen=True, slots=True)
class ActivityDay:
    date: date
    total_sen: int
    transactions: tuple[TransactionView, ...]


@dataclass(frozen=True, slots=True)
class CategorySummary:
    slug: str
    label: str
    spent_this_cycle_sen: int
    count: int


@dataclass(frozen=True, slots=True)
class Activity:
    drafts: tuple[TransactionView, ...]
    draft_total_sen: int
    days: tuple[ActivityDay, ...]
    spent_this_cycle_sen: int
    categories: tuple[CategorySummary, ...]


def _view(txn: Transaction) -> TransactionView:
    return TransactionView(
        id=txn.id,
        merchant=txn.merchant,
        amount_sen=txn.amount.sen,
        category=txn.category,
        category_label=label_for(txn.category),
        occurred_on=txn.occurred_on,
        status=txn.status,
        source=txn.source,
        confidence=txn.confidence,
        note=txn.note,
    )


def _total(txns: Iterable[TransactionView], currency: str) -> int:
    return Money.sum((Money(txn.amount_sen, currency) for txn in txns), currency).sen


def _summarise(
    confirmed: Iterable[Transaction], cycle_start: date, currency: str
) -> tuple[CategorySummary, ...]:
    """One chip per category present this cycle, dearest first."""
    totals: dict[str, list[int]] = {}
    for txn in confirmed:
        if txn.occurred_on < cycle_start:
            continue
        running = totals.setdefault(txn.category, [0, 0])
        running[0] += txn.amount.sen
        running[1] += 1
    return tuple(
        CategorySummary(
            slug=slug,
            label=label_for(slug),
            spent_this_cycle_sen=Money(spent, currency).sen,
            count=count,
        )
        for slug, (spent, count) in sorted(
            totals.items(), key=lambda item: (-item[1][0], item[0])
        )
    )


async def list_activity(
    session: AsyncSession, user: User, category: str | None = None
) -> Activity:
    """Drafts waiting for a decision, then confirmed spending grouped by day.

    `category` narrows the ledger only. The waiting drafts and the chips are
    always the whole picture, so a filter can never hide a pending decision.
    """
    drafts = (
        await session.execute(
            select(Transaction)
            .where(Transaction.user_id == user.id, Transaction.status == TXN_DRAFT)
            .order_by(Transaction.created_at.desc(), Transaction.id)
        )
    ).scalars().all()

    confirmed = (
        await session.execute(
            select(Transaction)
            .where(Transaction.user_id == user.id, Transaction.status == TXN_CONFIRMED)
            .order_by(
                Transaction.occurred_on.desc(), Transaction.created_at.desc(), Transaction.id
            )
        )
    ).scalars().all()
    categories = _summarise(confirmed, user.cycle_start, user.currency)
    shown = [txn for txn in confirmed if category is None or txn.category == category]

    days = tuple(
        ActivityDay(
            date=occurred_on,
            total_sen=_total(rows := tuple(_view(txn) for txn in group), user.currency),
            transactions=rows,
        )
        for occurred_on, group in groupby(shown, key=lambda txn: txn.occurred_on)
    )

    draft_views = tuple(_view(txn) for txn in drafts)
    return Activity(
        drafts=draft_views,
        draft_total_sen=_total(draft_views, user.currency),
        days=days,
        spent_this_cycle_sen=_total(
            (_view(txn) for txn in shown if txn.occurred_on >= user.cycle_start),
            user.currency,
        ),
        categories=categories,
    )


async def create_transaction(
    session: AsyncSession,
    user: User,
    *,
    merchant: str,
    amount_sen: int,
    occurred_on: date,
    category: str = "uncategorised",
    source: str = SOURCE_MANUAL,
    confidence: int | None = None,
    note: str = "",
) -> TransactionView:
    """Add a transaction as a draft. Nothing enters the ledger unconfirmed.

    Every capture path — typed, scanned, spoken, imported — lands here, so the
    rule that a machine-read amount is a proposal and not a fact is enforced in
    one place rather than at each caller.
    """
    if not merchant.strip():
        raise InvalidTransaction("a transaction needs a merchant")
    if amount_sen <= 0:
        raise InvalidTransaction("a transaction needs a positive amount")
    if confidence is not None and not 0 <= confidence <= 100:
        raise InvalidTransaction("confidence is a percentage")
    txn = Transaction(
        user_id=user.id,
        merchant=merchant.strip(),
        amount=Money(amount_sen, user.currency),
        category=category,
        occurred_on=occurred_on,
        status=TXN_DRAFT,
        source=source,
        confidence=confidence,
        note=note,
    )
    session.add(txn)
    await session.flush()
    return _view(txn)


async def get_transaction(
    session: AsyncSession, user: User, transaction_id: uuid.UUID
) -> TransactionView:
    txn = (
        await session.execute(
            select(Transaction).where(
                Transaction.id == transaction_id, Transaction.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if txn is None:
        raise TransactionNotFound(str(transaction_id))
    return _view(txn)


async def _move(
    session: AsyncSession,
    user: User,
    transaction_id: uuid.UUID,
    *,
    expected: str,
    to: str,
    refusal: type[Exception],
) -> TransactionView:
    """Move one of the user's transactions between statuses, or refuse to."""
    txn = (
        await session.execute(
            select(Transaction).where(
                Transaction.id == transaction_id, Transaction.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if txn is None:
        raise TransactionNotFound(str(transaction_id))
    if txn.status != expected:
        raise refusal(txn.status)
    txn.status = to
    await session.flush()
    return _view(txn)


async def confirm_draft(
    session: AsyncSession, user: User, transaction_id: uuid.UUID
) -> TransactionView:
    """Put a draft on the ledger, where safe-to-spend can finally see it."""
    return await _move(
        session,
        user,
        transaction_id,
        expected=TXN_DRAFT,
        to=TXN_CONFIRMED,
        refusal=AlreadySettled,
    )


async def discard_draft(
    session: AsyncSession, user: User, transaction_id: uuid.UUID
) -> TransactionView:
    """Retire a draft. The row stays for the record; the money never counted."""
    return await _move(
        session,
        user,
        transaction_id,
        expected=TXN_DRAFT,
        to=TXN_DISCARDED,
        refusal=AlreadySettled,
    )


async def unconfirm(
    session: AsyncSession, user: User, transaction_id: uuid.UUID
) -> TransactionView:
    """Take a transaction back off the ledger, undoing what a mis-tap counted."""
    return await _move(
        session,
        user,
        transaction_id,
        expected=TXN_CONFIRMED,
        to=TXN_DRAFT,
        refusal=NotConfirmed,
    )
