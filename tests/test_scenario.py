import numpy as np
import pandas as pd
import pytest

from bess_report import scenario as SC


@pytest.fixture(scope="module")
def runs(days, short_site):
    return SC.run_all(short_site, days)


def test_compare_rows_and_shares(short_site, runs):
    t = SC.compare(short_site, runs)
    assert {"da_perfect", "da_asof", "stack_perfect", "stack_asof", "toll", "cm_2029", "cm_2030"} <= set(t.index)
    assert 0 < t.loc["da_asof", "share_of_ceiling"] <= 1.0001
    assert t.loc["toll", "month_std_pln_per_mw"] == 0.0 and t.loc["toll", "market_risk"] == "offtaker"
    a = short_site.guarantees["availability"]
    assert t.loc["toll", "total_pln"] == pytest.approx(short_site.toll["pln_per_mw_year"] / 12.0 * a * 1)   # one month
    assert t.loc["cm_2030", "total_pln"] > t.loc["da_asof", "total_pln"]
    assert t.attrs["days"] == 7 and t.attrs["availability"] == a


def test_availability_scales_every_row(short_site, runs):
    full = SC.compare(short_site, runs, availability=1.0)
    half = SC.compare(short_site, runs, availability=0.5)
    assert (half["total_pln"] / full["total_pln"]).round(9).eq(0.5).all()


def test_capacity_market_terms_are_documented():
    t = SC.capacity_market_terms(2030)
    assert t["pln_per_mw_year"] == pytest.approx(t["closing_price_pln_kw_year"] * 1000 * t["kwd"])
    assert "URE" in t["price_source"] and "Dz.U." in t["kwd_source"]
    with pytest.raises(ValueError, match="no capacity market terms"):
        SC.capacity_market_terms(1999)


def test_simulated_year_bridge_and_tables(days, short_site, runs):
    months = SC.month_labels(short_site.first_day, short_site.last_day)
    tech = pd.DataFrame({"rte": [0.80] * len(months), "availability": [0.90] * len(months)}, index=months)
    sim = SC.simulate_year(short_site, days, runs, tech)
    b = sim["bridge"]
    b.check()
    assert b.end == pytest.approx(float(sim["statement"]["margin"].sum()))
    assert b.start == pytest.approx(float(sim["budget_statement"]["margin"].sum()))
    assert [k for k, _ in b.steps] == [SC.STEP_MARKET, SC.STEP_RTE, SC.STEP_AVAILABILITY, SC.STEP_FIXED]
    # worse efficiency and lower availability than budgeted can only cost money
    steps = dict(b.steps)
    assert steps[SC.STEP_RTE] <= 1e-6
    assert steps[SC.STEP_AVAILABILITY] < 0
    assert set(sim["settlement"]["line"]) <= set(__import__("bess_report.schema", fromlist=["LINES"]).LINES)


def test_missing_technical_availability_is_an_error(days, short_site, runs):
    tech = pd.DataFrame({"rte": [0.8], "availability": [np.nan]}, index=SC.month_labels(short_site.first_day, short_site.last_day))
    with pytest.raises(ValueError, match="no availability"):
        SC.simulate_year(short_site, days, runs, tech)
