from datetime import date

import sqlalchemy as sa

from kira.db.models import TXN_DRAFT, Account, Commitment, Goal, Transaction, User
from kira.money import Money
from kira.seed.demo import DEMO_EMAIL, seed_demo_user


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
        assert balance == Money(418040)
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

    async def test_seeds_two_waiting_drafts_and_no_confirmed_spend(self, session):
        await seed_demo_user(session)
        txns = (await session.execute(sa.select(Transaction))).scalars().all()
        assert len(txns) == 2
        assert all(txn.status == TXN_DRAFT for txn in txns)

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
