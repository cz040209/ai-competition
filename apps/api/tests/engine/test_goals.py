import pytest

from kira.engine import months_to_goal
from kira.money import Money


class TestMonthsToGoal:
    def test_rounds_up_to_the_next_whole_month(self):
        assert months_to_goal(Money(250000), Money(115000), Money(27000)) == 5

    def test_a_goal_already_met_still_reports_one_month(self):
        assert months_to_goal(Money(100), Money(500), Money(1000)) == 1

    def test_exact_division_is_not_rounded_up(self):
        assert months_to_goal(Money(30000), Money(0), Money(10000)) == 3

    def test_zero_contribution_is_rejected(self):
        with pytest.raises(ValueError):
            months_to_goal(Money(100), Money(0), Money(0))
