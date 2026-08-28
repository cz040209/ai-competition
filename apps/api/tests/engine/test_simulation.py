"""Many futures, honestly summarised."""

from datetime import date

import pytest

from kira.engine.projection import simulate
from kira.engine.types import CommitmentInput, DailySpendProfile, GoalInput, Snapshot
from kira.money import Money

VARIED = DailySpendProfile(
    by_weekday=tuple((500, 1500, 2500) for _ in range(7)), lookback_days=90
)
FLAT = DailySpendProfile(by_weekday=tuple((1000,) for _ in range(7)), lookback_days=90)
NOTHING = DailySpendProfile(by_weekday=tuple(() for _ in range(7)), lookback_days=0)


def snapshot(**overrides) -> Snapshot:
    fields = dict(
        balance=Money(500000),
        buffer=Money(0),
        spent_today=Money.zero(),
        commitments=(),
        goals=(),
        today=date(2026, 9, 3),
        next_payday=date(2026, 9, 25),
        cycle_start=date(2026, 8, 26),
        cycle_days=30,
        income=Money(650000),
    )
    fields.update(overrides)
    return Snapshot(**fields)


def test_the_same_seed_reproduces_the_run_exactly():
    a = simulate(snapshot(), VARIED, 60, trials=200, seed=7)
    b = simulate(snapshot(), VARIED, 60, trials=200, seed=7)
    assert a == b


def test_a_different_seed_gives_a_different_run():
    a = simulate(snapshot(), VARIED, 60, trials=200, seed=7)
    b = simulate(snapshot(), VARIED, 60, trials=200, seed=8)
    assert a.bands.p50 != b.bands.p50


def test_the_bands_are_ordered():
    result = simulate(snapshot(), VARIED, 60, trials=300, seed=11)
    for low, mid, high in zip(result.bands.p10, result.bands.p50, result.bands.p90):
        assert low <= mid <= high


def test_the_band_widens_with_the_horizon():
    result = simulate(snapshot(), VARIED, 60, trials=400, seed=11)
    early = result.bands.p90[0].sen - result.bands.p10[0].sen
    late = result.bands.p90[-1].sen - result.bands.p10[-1].sen
    assert late > early, "uncertainty accumulates; a flat band would be a lie"


def test_a_profile_with_no_variation_collapses_the_band_onto_the_median():
    result = simulate(snapshot(), FLAT, 30, trials=100, seed=3)
    assert result.bands.p10 == result.bands.p90


def test_a_reachable_goal_is_near_certain():
    goal = GoalInput("g1", Money(50000), Money(60000), Money(50000), date(2026, 11, 1))
    result = simulate(snapshot(goals=(goal,)), NOTHING, 90, trials=200, seed=5)
    assert result.outlooks[0].probability_bp >= 9500
    assert result.outlooks[0].median_shortfall.sen == 0


def test_an_unreachable_goal_is_near_impossible():
    goal = GoalInput("g2", Money(10000), Money(900000), Money(0), date(2026, 11, 1))
    result = simulate(snapshot(goals=(goal,)), NOTHING, 90, trials=200, seed=5)
    assert result.outlooks[0].probability_bp <= 500
    assert result.outlooks[0].median_shortfall.sen > 0


def test_a_goal_without_a_target_date_gets_no_outlook():
    result = simulate(
        snapshot(goals=(GoalInput("g3", Money(10000)),)), NOTHING, 90, trials=50, seed=5
    )
    assert result.outlooks == ()


def test_a_goal_beyond_the_horizon_gets_no_outlook():
    goal = GoalInput("g4", Money(10000), Money(20000), Money(0), date(2030, 1, 1))
    result = simulate(snapshot(goals=(goal,)), NOTHING, 90, trials=50, seed=5)
    assert result.outlooks == ()


def test_a_goal_cannot_be_funded_out_of_money_that_is_not_there():
    """A commitment that empties the account stops the goal accruing."""
    goal = GoalInput("g5", Money(50000), Money(100000), Money(0), date(2026, 12, 1))
    lean = snapshot(
        balance=Money(200000), income=Money.zero(), next_payday=date(2026, 12, 25),
        goals=(goal,),
    )
    easy = simulate(lean, NOTHING, 90, trials=100, seed=13)
    squeezed = simulate(
        Snapshot(
            **{
                **{f.name: getattr(lean, f.name) for f in lean.__dataclass_fields__.values()},
                "commitments": (CommitmentInput("loan", Money(150000), date(2026, 9, 20)),),
            }
        ),
        NOTHING,
        90,
        trials=100,
        seed=13,
    )
    assert easy.outlooks[0].probability_bp > squeezed.outlooks[0].probability_bp


def test_a_goal_is_never_credited_past_its_target_date():
    goal = GoalInput("g6", Money(30000), Money(500000), Money(0), date(2026, 9, 10))
    result = simulate(snapshot(goals=(goal,)), NOTHING, 90, trials=50, seed=5)
    # Seven days of accrual at 1000 a day, against a target of 500000.
    assert result.outlooks[0].median_shortfall.sen == 500000 - 7000


def test_trials_must_be_positive():
    with pytest.raises(ValueError):
        simulate(snapshot(), VARIED, 30, trials=0, seed=1)


def test_a_full_run_is_fast_enough_to_serve_in_a_request():
    """Spec §5.3: the one number nobody could predict from the armchair."""
    import time

    started = time.perf_counter()
    simulate(snapshot(), VARIED, 90, trials=2000, seed=1)
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0, f"2000 x 90 took {elapsed:.2f}s — see spec §5.3 fallbacks"
