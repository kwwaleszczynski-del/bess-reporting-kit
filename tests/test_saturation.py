import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bess_report import saturation as SA

ROOT = Path(__file__).resolve().parents[1]


def strategies():
    return pd.DataFrame({"pln_per_mw_year": [300.0, 3000.0]}, index=["da_asof", "stack_asof"])


def test_fleet_table_scales_the_stack_by_what_is_kept():
    summary = pd.DataFrame({"total": [1000.0, 500.0, 250.0], "reserves": [900.0, 400.0, 100.0]}, index=[0, 100, 200])
    t = SA.fleet_table(summary, strategies())
    assert t["retention"].tolist() == [1.0, 0.5, 0.25]
    assert t["stack_asof_scaled_pln_per_mw_year"].tolist() == [3000.0, 1500.0, 750.0]
    assert (t["da_asof_pln_per_mw_year"] == 300.0).all() and t.loc[100, "reserve_share"] == pytest.approx(0.8)


def test_breakeven_interpolates_or_is_none():
    t = pd.DataFrame({"stack_asof_scaled_pln_per_mw_year": [400.0, 300.0, 200.0], "da_asof_pln_per_mw_year": 250.0},
                     index=[0, 100, 200])
    assert SA.breakeven_fleet_mw(t) == pytest.approx(150.0)
    t["stack_asof_scaled_pln_per_mw_year"] = [900.0, 800.0, 700.0]
    assert SA.breakeven_fleet_mw(t) is None


def test_committed_fleet_results_are_consistent():
    sat = pd.read_csv(ROOT / "results/saturation_fleet.csv", index_col="fleet_mw")
    s = json.loads((ROOT / "results/summary.json").read_text(encoding="utf-8"))
    st, meta = s["strategies"], s["strategy_meta"]
    # the fleet model at zero MW is the lone battery of the strategy comparison: two optimiser paths agree
    assert sat.loc[0, "perfect_pln_per_mw_year"] * meta["availability"] == pytest.approx(
        st["stack_perfect"]["pln_per_mw_year"], rel=1e-6)
    assert sat.loc[0, "retention"] == 1.0 and sat["retention"].is_monotonic_decreasing
    assert sat.loc[0, "stack_asof_scaled_pln_per_mw_year"] == pytest.approx(st["stack_asof"]["pln_per_mw_year"])
    assert set(map(str, sat.index)) == set(s["saturation"]["rows"])
    # claim of the README: the scaled stack stays above day-ahead arbitrage at every fleet size run
    assert (sat["stack_asof_scaled_pln_per_mw_year"] > sat["da_asof_pln_per_mw_year"]).all()
    assert s["saturation"]["breakeven_fleet_mw"] is None
