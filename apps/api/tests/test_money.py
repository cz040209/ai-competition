import pytest

from kira.money import CurrencyMismatch, Money, round_half_up


class TestRoundHalfUp:
    def test_exact_division(self):
        assert round_half_up(216000, 30) == 7200

    def test_half_rounds_up(self):
        assert round_half_up(5, 2) == 3

    def test_below_half_rounds_down(self):
        assert round_half_up(4, 3) == 1

    def test_negative_half_rounds_toward_positive_infinity(self):
        # Matches JavaScript Math.round(-2.5) === -2, which the prototype relies on.
        assert round_half_up(-5, 2) == -2

    def test_rejects_non_positive_denominator(self):
        with pytest.raises(ValueError):
            round_half_up(1, 0)


class TestMoneyConstruction:
    def test_holds_integer_sen_and_currency(self):
        m = Money(1250)
        assert m.sen == 1250
        assert m.currency == "MYR"

    def test_rejects_float(self):
        with pytest.raises(TypeError):
            Money(12.5)  # type: ignore[arg-type]

    def test_rejects_bool(self):
        with pytest.raises(TypeError):
            Money(True)  # type: ignore[arg-type]

    def test_rejects_malformed_currency(self):
        with pytest.raises(ValueError):
            Money(100, "myr")

    def test_is_hashable_and_frozen(self):
        m = Money(100)
        assert {m: 1}[Money(100)] == 1
        with pytest.raises(AttributeError):
            m.sen = 200  # type: ignore[misc]


class TestMoneyArithmetic:
    def test_addition(self):
        assert Money(100) + Money(250) == Money(350)

    def test_subtraction_can_go_negative(self):
        assert Money(100) - Money(250) == Money(-150)

    def test_multiplication_by_int(self):
        assert Money(100) * 3 == Money(300)

    def test_multiplication_by_float_is_rejected(self):
        with pytest.raises(TypeError):
            Money(100) * 1.5  # type: ignore[operator]

    def test_divide_floor_rounds_toward_negative_infinity(self):
        assert Money(116540).divide_floor(22) == Money(5297)
        assert Money(-201500).divide_floor(22) == Money(-9160)

    def test_divide_floor_rejects_zero(self):
        with pytest.raises(ValueError):
            Money(100).divide_floor(0)

    def test_mixing_currencies_raises(self):
        with pytest.raises(CurrencyMismatch):
            Money(100, "MYR") + Money(100, "SGD")

    def test_comparison_respects_currency(self):
        assert Money(100) < Money(200)
        assert max(Money(0), Money(-500)) == Money(0)
        with pytest.raises(CurrencyMismatch):
            assert Money(100, "MYR") < Money(100, "SGD")

    def test_sum_of_empty_is_zero(self):
        assert Money.sum([]) == Money.zero()

    def test_sum_of_many(self):
        assert Money.sum([Money(120000), Money(8900), Money(52000)]) == Money(180900)


class TestMoneyFormatting:
    def test_ringgit_str_groups_thousands(self):
        assert Money(120000).ringgit_str() == "1,200.00"

    def test_ringgit_str_pads_sen(self):
        assert Money(5).ringgit_str() == "0.05"

    def test_ringgit_str_negative(self):
        assert Money(-1890).ringgit_str() == "-18.90"
