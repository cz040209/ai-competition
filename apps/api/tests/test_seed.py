from datetime import date

import sqlalchemy as sa

from kira.categories import slugs
from kira.db.models import (
    TXN_CONFIRMED,
    TXN_DRAFT,
    Account,
    Commitment,
    Goal,
    Transaction,
    User,
)
from kira.money import Money
from kira.seed.demo import DEMO_EMAIL, DEMO_TODAY, seed_demo_user


class TestSeed:
    async def test_creates_the_demo_user_and_their_picture(self, session):
        user = await seed_demo_user(session)
        assert user.email == DEMO_EMAIL
        assert user.display_name == "Floyd"
        assert user.buffer == Money(80000)
        assert user.next_payday == date(2026, 9, 25)
        assert user.cycle_start == date(2026, 8, 26)
        assert user.cycle_days == 30

    async def test_seeds_the_prototype_figures(self, session):
        await seed_demo_user(session)
        balance = (
            await session.execute(sa.select(sa.func.sum(Account.opening_balance)))
        ).scalar_one()
        assert balance == Money(481175)
        commitments = (await session.execute(sa.select(Commitment))).scalars().all()
        assert sum(commitment.amount.sen for commitment in commitments) == 200300
        assert {commitment.name for commitment in commitments} == {
            "Rent",
            "Phone bill",
            "Car loan minimum",
            "Streaming bundle",
            "Home internet",
        }
        goals = (await session.execute(sa.select(Goal))).scalars().all()
        assert {goal.name for goal in goals} == {"Emergency top-up", "Wedding"}
        assert sum(goal.monthly.sen for goal in goals) == 79500

    async def test_seeds_two_waiting_drafts(self, session):
        await seed_demo_user(session)
        txns = (await session.execute(sa.select(Transaction))).scalars().all()
        drafts = [txn for txn in txns if txn.status == TXN_DRAFT]
        assert len(drafts) == 2

    async def test_seeds_a_spending_history_that_leaves_the_balance_unchanged(self, session):
        await seed_demo_user(session)
        opening = (
            await session.execute(sa.select(sa.func.sum(Account.opening_balance)))
        ).scalar_one()
        confirmed = (
            await session.execute(
                sa.select(Transaction).where(Transaction.status == TXN_CONFIRMED)
            )
        ).scalars().all()
        assert len(confirmed) == 16
        assert opening - Money.sum((txn.amount for txn in confirmed), "MYR") == Money(418040)

    async def test_categorises_every_transaction_from_the_vocabulary(self, session):
        await seed_demo_user(session)
        txns = (await session.execute(sa.select(Transaction))).scalars().all()
        assert {txn.category for txn in txns} <= set(slugs())

    async def test_spreads_the_history_widely_enough_to_filter(self, session):
        await seed_demo_user(session)
        confirmed = (
            await session.execute(
                sa.select(Transaction).where(Transaction.status == TXN_CONFIRMED)
            )
        ).scalars().all()
        categories = {txn.category for txn in confirmed}
        assert len(categories) >= 8
        assert {"family", "charity", "shopping"} <= categories

    async def test_never_confirms_spending_dated_today(self, session):
        await seed_demo_user(session)
        confirmed = (
            await session.execute(
                sa.select(Transaction).where(Transaction.status == TXN_CONFIRMED)
            )
        ).scalars().all()
        assert confirmed
        assert all(txn.occurred_on < DEMO_TODAY for txn in confirmed)

    async def test_is_idempotent(self, session):
        first = await seed_demo_user(session)
        second = await seed_demo_user(session)
        assert first.id == second.id
        user_count = (
            await session.execute(sa.select(sa.func.count()).select_from(User))
        ).scalar_one()
        assert user_count == 1
        assert (
            await session.execute(sa.select(sa.func.count()).select_from(Commitment))
        ).scalar_one() == 5
