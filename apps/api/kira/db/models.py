"""Persistent financial data, with balance derived from confirmed transactions."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kira.db.base import Base
from kira.db.types import MoneyType
from kira.money import Money

TXN_DRAFT = "draft"
TXN_CONFIRMED = "confirmed"
TXN_STATUSES = (TXN_DRAFT, TXN_CONFIRMED)

SOURCE_MANUAL = "manual"
SOURCE_RECEIPT = "receipt"
SOURCE_VOICE = "voice"
SOURCE_IMPORT = "import"

HORIZON_SHORT = "short"
HORIZON_LONG = "long"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(80))
    currency: Mapped[str] = mapped_column(String(3), default="MYR")
    buffer: Mapped[Money] = mapped_column(MoneyType(), default=lambda: Money(0))
    next_payday: Mapped[date] = mapped_column(Date)
    cycle_start: Mapped[date] = mapped_column(Date)
    cycle_days: Mapped[int] = mapped_column(Integer, default=30)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    accounts: Mapped[list[Account]] = relationship(back_populates="user", lazy="selectin")
    commitments: Mapped[list[Commitment]] = relationship(back_populates="user", lazy="selectin")
    goals: Mapped[list[Goal]] = relationship(back_populates="user", lazy="selectin")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(24))  # bank | ewallet | cash
    opening_balance: Mapped[Money] = mapped_column(MoneyType())

    user: Mapped[User] = relationship(back_populates="accounts")


class Commitment(Base):
    __tablename__ = "commitments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    amount: Mapped[Money] = mapped_column(MoneyType())
    due_date: Mapped[date] = mapped_column(Date, index=True)
    protected: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="commitments")


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    horizon: Mapped[str] = mapped_column(String(8))  # short | long
    target: Mapped[Money] = mapped_column(MoneyType())
    saved: Mapped[Money] = mapped_column(MoneyType())
    monthly: Mapped[Money] = mapped_column(MoneyType())
    note: Mapped[str] = mapped_column(Text, default="")

    user: Mapped[User] = relationship(back_populates="goals")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    merchant: Mapped[str] = mapped_column(String(120))
    amount: Mapped[Money] = mapped_column(MoneyType())
    category: Mapped[str] = mapped_column(String(40), default="Uncategorised")
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(12), default=TXN_DRAFT, index=True)
    source: Mapped[str] = mapped_column(String(12), default=SOURCE_MANUAL)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
