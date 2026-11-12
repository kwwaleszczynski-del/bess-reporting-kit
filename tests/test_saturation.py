import json
from pathlib import Path

import pandas as pd
import pytest

from bess_report import saturation as SA

ROOT = Path(__file__).resolve().parents[1]


def strategies():
    return pd.DataFrame({"pln_per_mw_year": [300.0, 3000.0]}, index=["da_asof", "stack_asof"])


def raw():
    return pd.DataFrame({"best_response": [1000.0, 600.0, 400.0], "settled": [1000.0, 400.0, 100.0],
                         "reserves_best_response": [900.0, 500.0, 300.0]}, index=pd.Index([0, 100, 200], name="fleet_mw"))


def test_fleet_table_gives_both_bounds_and_scales_the_as_of_stack():
    t = SA.fleet_table(raw(), strategies(), availability=0.5)
    assert t["retention_best_response"].tolist() == [1.0, 0.6, 0.4]
    assert t["retention_settled"].tolist() == [1.0, 0.4, 0.1]
    assert t["stack_asof_settled_pln_per_mw_year"].tolist() == pytest.approx([3000.0, 1200.0, 300.0])
    assert t["stack_asof_best_response_pln_per_mw_year"].tolist() == pytest.approx([3000.0, 1800.0, 1200.0])
    assert (t["da_asof_pln_per_mw_year"] == 300.0).all()
    assert t["perfect_settled_pln_per_mw_year"].tolist() == [500.0, 200.0, 50.0]      # at the assumed availability
    assert (t["stack_asof_settled_pln_per_mw_year"] <= t["stack_asof_best_response_pln_per_mw_year"]).all()


def test_breakeven_interpolates_or_is_none():
    t = SA.fleet_table(raw(), strategies())
    assert SA.breakeven_fleet_mw(t, "stack_asof_settled_pln_per_mw_year") == pytest.approx(200.0)
    assert SA.breakeven_fleet_mw(t, "stack_asof_best_response_pln_per_mw_year") is None
    t2 = pd.DataFrame({"stack_asof_settled_pln_per_mw_year": [400.0, 300.0, 200.0], "da_asof_pln_per_mw_year": 250.0},
                      index=[0, 100, 200])
    assert SA.breakeven_fleet_mw(t2) == pytest.approx(150.0)


def test_committed_fleet_results_are_consistent():
    sat = pd.read_csv(ROOT / "results/saturation_fleet.csv", index_col="fleet_mw")
    raw_ = pd.read_csv(ROOT / "results/saturation_raw.csv", index_col="fleet_mw")
    s = json.loads((ROOT / "results/summary.json").read_text(encoding="utf-8"))
    st, meta = s["strategies"], s["strategy_meta"]
    a = meta["availability"]
    # the fleet model at zero MW is the lone battery of the strategy comparison: two optimiser paths agree
    assert raw_.loc[0, "best_response"] * a == pytest.approx(st["stack_perfect"]["pln_per_mw_year"], rel=1e-6)
    assert sat.loc[0, "perfect_settled_pln_per_mw_year"] == pytest.approx(sat.loc[0, "perfect_best_response_pln_per_mw_year"])
    assert sat.loc[0, "retention_settled"] == 1.0 and sat.loc[0, "retention_best_response"] == 1.0
    assert sat["retention_best_response"].is_monotonic_decreasing and sat["retention_settled"].is_monotonic_decreasing
    # the settled bound is the lower one
    assert (sat["retention_settled"] <= sat["retention_best_response"] + 1e-9).all()
    assert sat.loc[0, "stack_asof_settled_pln_per_mw_year"] == pytest.approx(st["stack_asof"]["pln_per_mw_year"])
    assert set(map(str, sat.index)) == set(s["saturation"]["rows"])
    # the break-evens in the summary are what the table implies
    assert s["saturation"]["breakeven_settled_mw"] == SA.breakeven_fleet_mw(sat, "stack_asof_settled_pln_per_mw_year")
    assert s["saturation"]["breakeven_best_response_mw"] == SA.breakeven_fleet_mw(
        sat, "stack_asof_best_response_pln_per_mw_year")
