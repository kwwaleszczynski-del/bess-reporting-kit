import numpy as np
import pandas as pd
import pytest

from bess_report.financial import Bridge, period_table, revenue_mix, statement, variance
from bess_report.schema import FIXED_COST_LINES, REVENUE_LINES, VARIABLE_COST_LINES


def money(values: dict[str, float], month="2026-01"):
    return pd.DataFrame({"month": month, "line": list(values), "value_pln": list(values.values())})


def test_statement_identities():
    s = statement(money({"da_sales": 100.0, "fcr_capacity": 50.0, "da_purchases": 30.0, "degradation": 5.0, "om": 10.0}))
    r = s.iloc[0]
    assert r["revenue"] == 150 and r["variable_costs"] == 35 and r["gross_margin"] == 115
    assert r["fixed_costs"] == 10 and r["margin"] == 105
    assert set(REVENUE_LINES) | set(VARIABLE_COST_LINES) | set(FIXED_COST_LINES) <= set(s.columns)


def test_statement_fills_missing_months():
    s = statement(money({"da_sales": 1.0}), months=["2026-01", "2026-02"])
    assert s.loc["2026-02", "margin"] == 0.0


def test_variance_and_mix():
    a, b = statement(money({"da_sales": 120.0, "om": 10.0})), statement(money({"da_sales": 100.0, "om": 10.0}))
    v = variance(a, b)
    assert v.loc["margin", "difference"] == 20.0 and v.loc["da_sales", "difference_pct"] == pytest.approx(0.2)
    assert revenue_mix(a)["share"].sum() == pytest.approx(1.0)
    with pytest.raises(ValueError, match="share no month"):
        variance(a, statement(money({"da_sales": 1.0}, "2025-01")))
    assert period_table(a)["margin"] == 110.0


def test_bridge_adds_up_or_fails():
    ok = Bridge("a", 100.0, [("x", 10.0), ("y", -4.0)], "b", 106.0)
    assert ok.frame()["value_pln"].tolist() == [100.0, 10.0, -4.0, 106.0]
    with pytest.raises(ValueError, match="does not add up"):
        Bridge("a", 100.0, [("x", 10.0)], "b", 99.0).check()
