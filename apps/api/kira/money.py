"""Money as integer sen. No float ever participates in a monetary calculation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


class CurrencyMismatch(ValueError):
    """Raised when two Money values of different currencies are combined."""


def round_half_up(numerator: int, denominator: int) -> int:
    """Divide two integers, rounding halves toward positive infinity.

    This matches JavaScript's ``Math.round``, which the UI prototype uses.
    Python's built-in ``round`` rounds halves to even and must not be used on
    money. The arithmetic here is entirely integral, so no float is involved.
    """
    if not isinstance(numerator, int) or isinstance(numerator, bool):
        raise TypeError("numerator must be an int")
    if not isinstance(denominator, int) or isinstance(denominator, bool):
        raise TypeError("denominator must be an int")
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    return (2 * numerator + denominator) // (2 * denominator)


def _check_sen(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"Money.sen must be an int number of sen, got {type(value).__name__}")


def _check_currency(value: Any) -> None:
    if not isinstance(value, str) or len(value) != 3 or not value.isalpha() or not value.isupper():
        raise ValueError(f"currency must be a three-letter uppercase ISO code, got {value!r}")


@dataclass(frozen=True, slots=True)
class Money:
    """An exact amount, held as an integer count of the currency's minor unit."""

    sen: int
    currency: str = "MYR"

    def __post_init__(self) -> None:
        _check_sen(self.sen)
        _check_currency(self.currency)

    @classmethod
    def zero(cls, currency: str = "MYR") -> Money:
        return cls(0, currency)

    @classmethod
    def sum(cls, items: Iterable[Money], currency: str = "MYR") -> Money:
        total = cls.zero(currency)
        for item in items:
            total = total + item
        return total

    def _same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatch(f"cannot combine {self.currency} with {other.currency}")

    def __add__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_currency(other)
        return Money(self.sen + other.sen, self.currency)

    def __sub__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_currency(other)
        return Money(self.sen - other.sen, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.sen, self.currency)

    def __mul__(self, factor: int) -> Money:
        if isinstance(factor, bool) or not isinstance(factor, int):
            raise TypeError("Money can only be multiplied by an int")
        return Money(self.sen * factor, self.currency)

    __rmul__ = __mul__

    def divide_floor(self, divisor: int) -> Money:
        """Split into ``divisor`` parts, rounding toward negative infinity.

        Floor, not truncation: a negative amount spread over days must round
        away from zero so the daily allowance never flatters an overdraft.
        """
        if isinstance(divisor, bool) or not isinstance(divisor, int):
            raise TypeError("divisor must be an int")
        if divisor <= 0:
            raise ValueError("divisor must be positive")
        return Money(self.sen // divisor, self.currency)

    def __lt__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_currency(other)
        return self.sen < other.sen

    def __le__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_currency(other)
        return self.sen <= other.sen

    def __gt__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_currency(other)
        return self.sen > other.sen

    def __ge__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_currency(other)
        return self.sen >= other.sen

    def ringgit_str(self) -> str:
        """Format as a grouped major-unit string, e.g. ``1,200.00``."""
        sign = "-" if self.sen < 0 else ""
        major, minor = divmod(abs(self.sen), 100)
        return f"{sign}{major:,}.{minor:02d}"

    def __str__(self) -> str:
        return f"{self.currency} {self.ringgit_str()}"
