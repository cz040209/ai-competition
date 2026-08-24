from datetime import date

import pytest
import sqlalchemy as sa

from kira.db.models import Account, User
from kira.money import Money


async def make_user(session) -> User:
    user = User(
        email="a@example.com",
        password_hash="x",
        display_name="A",
        buffer=Money(80000),
        next_payday=date(2026, 9, 25),
        cycle_start=date(2026, 8, 26),
        cycle_days=30,
    )
    session.add(user)
    await session.flush()
    return user


class TestMoneyType:
    async def test_round_trips_money(self, session):
        user = await make_user(session)
        session.add(
            Account(user_id=user.id, name="Main", kind="bank", opening_balance=Money(418040))
        )
        await session.flush()
        session.expunge_all()

        account = (await session.execute(sa.select(Account))).scalar_one()
        assert account.opening_balance == Money(418040)
        assert isinstance(account.opening_balance, Money)

    async def test_stores_integer_sen_in_the_column(self, session):
        user = await make_user(session)
        session.add(
            Account(user_id=user.id, name="Main", kind="bank", opening_balance=Money(418040))
        )
        await session.flush()

        raw = (await session.execute(sa.text("SELECT opening_balance FROM accounts"))).scalar_one()
        assert raw == 418040

    async def test_rejects_a_float(self, session):
        user = await make_user(session)
        session.add(Account(user_id=user.id, name="Main", kind="bank", opening_balance=4180.40))
        with pytest.raises((TypeError, sa.exc.StatementError), match="money columns take a Money"):
            await session.flush()

    async def test_rejects_a_bare_int(self, session):
        user = await make_user(session)
        session.add(Account(user_id=user.id, name="Main", kind="bank", opening_balance=418040))
        with pytest.raises((TypeError, sa.exc.StatementError), match="money columns take a Money"):
            await session.flush()

    async def test_rejects_the_wrong_currency(self, session):
        user = await make_user(session)
        session.add(
            Account(user_id=user.id, name="Main", kind="bank", opening_balance=Money(1, "SGD"))
        )
        with pytest.raises((ValueError, sa.exc.StatementError), match="column holds MYR, got SGD"):
            await session.flush()
