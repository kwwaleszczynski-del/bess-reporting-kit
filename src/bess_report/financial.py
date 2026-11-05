"""Financial report: revenues by source, costs, margin, budget variance and a budget-to-actual bridge.

The input is the monthly money tables of ``bess_report.schema``. ``statement`` pivots them into one row per month
(revenue lines, revenue, variable costs, gross margin, fixed costs, margin); ``variance`` compares two statements
line by line; ``Bridge`` is a waterfall whose steps must add up exactly from the budget to the actual margin, the
same discipline as the budget bridge of pv-budget-bridge.

Gross margin = revenue - day-ahead purchases - auxiliary energy - degradation allowance. Margin = gross margin -
fixed costs (an operating margin before depreciation and tax, not an accounting figure).

Usage:
    stmt = statement(settlement)
    var = variance(stmt, statement(budget))
    bridge = Bridge("Budget margin", budget_margin, [("Market", x), ("RTE", y)], "Actual margin", actual_margin)
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from bess_report.schema import FIXED_COST_LINES, LINES, REVENUE_LINES, VARIABLE_COST_LINES, validate_money

TOTALS = ["revenue", "variable_costs", "gross_margin", "fixed_costs", "margin"]


def statement(money: pd.DataFrame, months: list[str] | None = None) -> pd.DataFrame:
    """One row per month: every line (zero when absent), then ``TOTALS``."""
    money = validate_money(money)
    wide = money.pivot_table(index="month", columns="line", values="value_pln", aggfunc="sum").fillna(0.0)
    wide = wide.reindex(columns=list(LINES), fill_value=0.0)
    if months is not None:
        wide = wide.reindex(months, fill_value=0.0)
    wide["revenue"] = wide[list(REVENUE_LINES)].sum(axis=1)
    wide["variable_costs"] = wide[list(VARIABLE_COST_LINES)].sum(axis=1)
    wide["gross_margin"] = wide["revenue"] - wide["variable_costs"]
    wide["fixed_costs"] = wide[list(FIXED_COST_LINES)].sum(axis=1)
    wide["margin"] = wide["gross_margin"] - wide["fixed_costs"]
    wide.index.name = "month"
    return wide


def period_table(stmt: pd.DataFrame) -> pd.Series:
    return stmt.sum(axis=0)


def variance(actual: pd.DataFrame, budget: pd.DataFrame) -> pd.DataFrame:
    """Period totals per line and total: actual, budget, difference and difference in percent of the budget."""
    months = sorted(set(actual.index) & set(budget.index))
    if not months:
        raise ValueError("actual and budget share no month")
    a, b = actual.loc[months].sum(), budget.loc[months].sum()
    out = pd.DataFrame({"actual": a, "budget": b})
    out["difference"] = out["actual"] - out["budget"]
    out["difference_pct"] = out["difference"] / out["budget"].where(out["budget"].abs() > 0)
    keep = [c for c in out.index if c in TOTALS or out.loc[c, ["actual", "budget"]].abs().sum() > 0]
    return out.loc[keep]


def revenue_mix(stmt: pd.DataFrame) -> pd.DataFrame:
    """Share of each revenue line in the period's revenue."""
    tot = stmt[list(REVENUE_LINES)].sum()
    out = pd.DataFrame({"revenue_pln": tot, "share": tot / tot.sum() if tot.sum() else tot})
    return out[out["revenue_pln"].abs() > 0]


@dataclass
class Bridge:
    """Waterfall from a start value to an end value through named steps; ``check`` fails if they do not add up."""

    start_label: str
    start: float
    steps: list[tuple[str, float]]
    end_label: str
    end: float

    def check(self, tol: float = 1e-6) -> None:
        total = self.start + sum(v for _, v in self.steps)
        if abs(total - self.end) > tol * max(1.0, abs(self.end)):
            raise ValueError(f"bridge does not add up: {total:.2f} vs {self.end:.2f}")

    def frame(self) -> pd.DataFrame:
        self.check()
        rows = [(self.start_label, self.start, "total")] + [(k, v, "step") for k, v in self.steps]
        rows.append((self.end_label, self.end, "total"))
        return pd.DataFrame(rows, columns=["label", "value_pln", "kind"])
