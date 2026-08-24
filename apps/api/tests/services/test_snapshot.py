from datetime import date

from kira.db.models import TXN_CONFIRMED, TXN_DRAFT, Transaction
from kira.engine import safe_to_spend
from kira.money import Money
from kira.seed.demo import DEMO_TODAY, seed_demo_user
from kira.services.snapshot import load_snapshot


async def snapshot_for(session):
    user = await seed_demo_user(session)
    return user, await load_snapshot(session, user, DEMO_TODAY)


class TestLoadSnapshot:
    async def test_reads_the_seeded_picture(self, session):
        _, snapshot = await snapshot_for(session)
        assert snapshot.balance == Money(418040)
        assert snapshot.buffer == Money(80000)
        assert len(snapshot.commitments) == 5
        assert len(snapshot.goals) == 2
        assert snapshot.today == DEMO_TODAY
        assert snapshot.next_payday == date(2026, 9, 25)

    async def test_produces_the_golden_baseline(self, session):
        _, snapshot = await snapshot_for(session)
        result = safe_to_spend(snapshot)
        assert result.safe_today == Money(5297)


class TestDraftInvariant:
    async def test_a_draft_changes_nothing(self, session):
        user, before = await snapshot_for(session)
        session.add(
            Transaction(
                user_id=user.id,
                merchant="Big draft",
                amount=Money(50000),
                category="Food",
                occurred_on=DEMO_TODAY,
                status=TXN_DRAFT,
                source="manual",
            )
        )
        await session.flush()
        after = await load_snapshot(session, user, DEMO_TODAY)
        assert after.balance == before.balance
        assert after.spent_today == before.spent_today
        assert safe_to_spend(after) == safe_to_spend(before)

    async def test_confirming_moves_both_balance_and_spent_today(self, session):
        user, before = await snapshot_for(session)
        session.add(
            Transaction(
                user_id=user.id,
                merchant="Nasi Kandar Pelita",
                amount=Money(1890),
                category="Food",
                occurred_on=DEMO_TODAY,
                status=TXN_CONFIRMED,
                source="receipt",
            )
        )
        await session.flush()
        after = await load_snapshot(session, user, DEMO_TODAY)
        assert after.balance == before.balance - Money(1890)
        assert after.spent_today == Money(1890)
        assert safe_to_spend(after).safe_today == Money(3321)

    async def test_a_confirmed_transaction_on_another_day_is_not_spent_today(self, session):
        user, _ = await snapshot_for(session)
        session.add(
            Transaction(
                user_id=user.id,
                merchant="Yesterday's groceries",
                amount=Money(6215),
                category="Groceries",
                occurred_on=date(2026, 9, 2),
                status=TXN_CONFIRMED,
                source="manual",
            )
        )
        await session.flush()
        after = await load_snapshot(session, user, DEMO_TODAY)
        assert after.spent_today == Money.zero()
        assert after.balance == Money(418040) - Money(6215)
