from dataclasses import replace
from datetime import date

import numpy as np
import pytest

from bess_report import strategies as S


def test_days_are_complete(days):
    assert len(days) > 700
    d = days[10]
    assert len(d.prices) == len(d.minute) == len(d.hour_of) and d.reserve_prices.shape == (len(d.hours), 7)


def test_first_week_has_no_plan(days):
    assert all(S.plan_inputs(days, i) is None for i in range(S.LOOKBACK_DAYS))
    assert S.plan_inputs(days, S.LOOKBACK_DAYS) is not None


def test_plan_does_not_depend_on_the_delivery_day_or_later(days):
    """As-of: replacing every price from day D onwards (D included) leaves the forecast for D unchanged."""
    i = 200
    before = S.plan_inputs(days, i)
    future = [replace(d, prices=d.prices * 3 + 100, reserve_prices=d.reserve_prices * 7) for d in days[i:]]
    after = S.plan_inputs(days[:i] + future, i)
    assert np.array_equal(before[0], after[0]) and np.array_equal(before[1], after[1], equal_nan=True)


def test_plan_uses_the_last_seven_days(days):
    i = 200
    e, _ = S.plan_inputs(days, i)
    prev = days[i - 7:i]
    manual = np.mean([d.prices[d.minute == d.minute[0]].mean() for d in prev])
    assert e[0] == pytest.approx(manual)


def test_perfect_foresight_is_a_ceiling_and_stack_adds_options(days, short_site):
    b = short_site.battery
    run = lambda kind, mode: S.run_strategy(days, kind, mode, b, short_site.first_day, short_site.last_day)   # noqa: E731
    da_p, da_a, st_p, st_a = run("da", "perfect"), run("da", "asof"), run("stack", "perfect"), run("stack", "asof")
    assert list(da_p.index) == list(st_a.index) and len(da_p) == 7
    tol = 1e-3 * abs(S.margin(da_p).sum())
    assert (S.margin(da_p) >= S.margin(da_a) - tol).all()              # same objective, actual prices
    assert S.margin(st_p).sum() >= S.margin(da_p).sum() - tol
    assert S.margin(st_p).sum() >= S.margin(st_a).sum() - tol


def test_settlement_matches_the_optimiser(days, short_site):
    from bess_stack.optimizer import STRATEGIES, optimize_day
    b = short_site.battery
    day = next(d for d in days if d.business_date == date(2025, 10, 10))
    res = optimize_day(day.prices, day.hour_of, day.reserve_prices, b.params(), STRATEGIES["stacked"])
    row = S.settle(day, res, b)
    total = sum(row[k] for k in S.REVENUE_COLUMNS) - row["degradation"]
    assert total == pytest.approx(res.total, rel=1e-9)


def test_unknown_strategy_and_empty_period(days, site):
    with pytest.raises(ValueError, match="unknown strategy"):
        S.run_strategy(days, "x", "asof", site.battery, date(2025, 10, 8), date(2025, 10, 9))
    with pytest.raises(ValueError, match="no day can be planned"):
        S.run_strategy(days, "da", "asof", site.battery, date(2024, 9, 23), date(2024, 9, 25))


@pytest.mark.parametrize("lookback", [1, 3, 7])
def test_as_of_for_every_lookback(days, lookback):
    i = 200
    before = S.plan_inputs(days, i, lookback)
    future = [replace(d, prices=d.prices * 3 + 100, reserve_prices=d.reserve_prices * 7) for d in days[i:]]
    after = S.plan_inputs(days[:i] + future, i, lookback)
    assert np.array_equal(before[0], after[0]) and np.array_equal(before[1], after[1], equal_nan=True)
    assert S.plan_inputs(days, lookback - 1, lookback) is None and S.plan_inputs(days, lookback, lookback) is not None
