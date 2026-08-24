"""The versioned demo user, maintained alongside the product's prototype figures."""

from __future__ import annotations

from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import (
    HORIZON_LONG,
    HORIZON_SHORT,
    SOURCE_RECEIPT,
    SOURCE_VOICE,
    TXN_DRAFT,
    Account,
    Commitment,
    Goal,
    Transaction,
    User,
)
from kira.money import Money
from kira.services.auth import hash_password

DEMO_EMAIL = "demo@kira.app"
DEMO_PASSWORD = "demo-money-butler"
DEMO_TODAY = date(2026, 9, 3)
DEMO_PAYDAY = date(2026, 9, 25)
DEMO_CYCLE_START = date(2026, 8, 26)

COMMITMENTS = (
    ("Rent", 120000, date(2026, 9, 5), True),
    ("Phone bill", 8900, date(2026, 9, 8), False),
    ("Car loan minimum", 52000, date(2026, 9, 10), True),
    ("Streaming bundle", 5500, date(2026, 9, 14), False),
    ("Home internet", 13900, date(2026, 9, 18), False),
)

GOALS = (
    (
        "Emergency top-up",
        HORIZON_SHORT,
        250000,
        115000,
        27000,
        "Three weeks of expenses, kept separate from the buffer.",
    ),
    (
        "Wedding",
        HORIZON_LONG,
        800000,
        329000,
        52500,
        "Deposit and banquet, split with Aida.",
    ),
)

DRAFTS = (
    (
        "Nasi Kandar Pelita",
        1890,
        "Food",
        SOURCE_RECEIPT,
        94,
        "Line item total matched, tax line ignored.",
    ),
    (
        "Grab — office to KLCC",
        1400,
        "Transport",
        SOURCE_VOICE,
        71,
        "Heard 'fourteen ringgit'. Amount is worth a second look.",
    ),
)


async def seed_demo_user(session: AsyncSession) -> User:
    """Create or reset the demo user's financial picture without duplicates."""
    user = (
        await session.execute(select(User).where(User.email == DEMO_EMAIL))
    ).scalar_one_or_none()

    if user is None:
        user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            display_name="Floyd",
            currency="MYR",
            buffer=Money(80000),
            next_payday=DEMO_PAYDAY,
            cycle_start=DEMO_CYCLE_START,
            cycle_days=30,
        )
        session.add(user)
        await session.flush()
    else:
        user.password_hash = hash_password(DEMO_PASSWORD)
        user.display_name = "Floyd"
        user.currency = "MYR"
        user.buffer = Money(80000)
        user.next_payday = DEMO_PAYDAY
        user.cycle_start = DEMO_CYCLE_START
        user.cycle_days = 30
        for model in (Transaction, Goal, Commitment, Account):
            await session.execute(delete(model).where(model.user_id == user.id))

    session.add(
        Account(
            user_id=user.id,
            name="Maybank current",
            kind="bank",
            opening_balance=Money(418040),
        )
    )

    for name, sen, due_date, protected in COMMITMENTS:
        session.add(
            Commitment(
                user_id=user.id,
                name=name,
                amount=Money(sen),
                due_date=due_date,
                protected=protected,
            )
        )

    for name, horizon, target, saved, monthly, note in GOALS:
        session.add(
            Goal(
                user_id=user.id,
                name=name,
                horizon=horizon,
                target=Money(target),
                saved=Money(saved),
                monthly=Money(monthly),
                note=note,
            )
        )

    # Drafts are intentionally excluded from all Today calculations until confirmed.
    for merchant, sen, category, source, confidence, note in DRAFTS:
        session.add(
            Transaction(
                user_id=user.id,
                merchant=merchant,
                amount=Money(sen),
                category=category,
                occurred_on=DEMO_TODAY,
                status=TXN_DRAFT,
                source=source,
                confidence=confidence,
                note=note,
            )
        )

    await session.flush()
    return user
