"""The SQLAlchemy boundary for money. A float cannot physically reach a column."""

from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Dialect
from sqlalchemy.types import TypeDecorator

from kira.money import Money


class MoneyType(TypeDecorator):
    """Store Money as an integer count of sen in a fixed currency column."""

    impl = BigInteger
    cache_ok = True

    def __init__(self, currency: str = "MYR") -> None:
        super().__init__()
        self.currency = currency

    def process_bind_param(self, value: Any, dialect: Dialect) -> int | None:
        if value is None:
            return None
        if not isinstance(value, Money):
            raise TypeError(
                f"money columns take a Money, got {type(value).__name__}: {value!r}"
            )
        if value.currency != self.currency:
            raise ValueError(f"column holds {self.currency}, got {value.currency}")
        return value.sen

    def process_result_value(self, value: Any, dialect: Dialect) -> Money | None:
        if value is None:
            return None
        return Money(int(value), self.currency)
