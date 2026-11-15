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


def test_run_strategy_end_to_end_does_not_see_the_delivery_day(days):
    """The whole path (forecast, optimiser, settlement): scaling the prices of day D, and every later price, by a factor
    changes what the plan earns by exactly that factor and nothing about the plan itself."""
    i = 200
    day = days[i]
    b = S.Battery()
    base = S.run_strategy(days, "stack", "asof", b, day.business_date, day.business_date)
    k = 3.0
    scaled = [replace(d, prices=d.prices * k, reserve_prices=d.reserve_prices * k) if j >= i else d
              for j, d in enumerate(days)]
    alt = S.run_strategy(scaled, "stack", "asof", b, day.business_date, day.business_date)
    for col in ("discharged_mwh", "charged_mwh", "reserved_mw_hours"):         # the plan: unchanged
        assert alt[col].iloc[0] == pytest.approx(base[col].iloc[0], rel=1e-9), col
    for col in ("da_sales", "da_purchases", "fcr_capacity", "afrr_capacity", "mfrrd_capacity", "rr_capacity"):
        assert alt[col].iloc[0] == pytest.approx(k * base[col].iloc[0], rel=1e-9), col      # the settlement: scaled


def test_recomputation_reproduces_the_committed_daily_margins(days, site):
    from pathlib import Path

    import pandas as pd
    ref = pd.read_csv(Path(__file__).resolve().parents[1] / "results/strategy_daily_margin.csv", index_col=0)
    ref.index = pd.to_datetime(ref.index).date
    d0 = date(2026, 3, 1)
    got = S.run_strategy(days, "stack", "asof", site.battery, d0, date(2026, 3, 3))
    for d, m in S.margin(got).items():
        assert m == pytest.approx(ref.loc[d, "stack_asof"], rel=1e-6)
    assert len(got) == 3
