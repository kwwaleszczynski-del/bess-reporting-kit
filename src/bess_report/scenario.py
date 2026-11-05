"""The runs behind the reports: a common evaluation of the sales strategies and the settlement tables that a
simulated operating year produces for the financial report.

Strategy comparison (``compare``): all strategies trade the same battery on the same days and are settled on the same
prices, at the same assumed availability. Market strategies are run by ``strategies.run_strategy``; the toll and the
capacity market payment are contract terms of the site file.

Simulated settlement (``simulate_year``): the day-ahead plus balancing capacity strategy planned as-of, settled on
published prices, then scaled by the technical report's monthly availability and run with its monthly round-trip
efficiency. The budget is a rule, not a forecast: the same strategy over the same calendar months one year earlier,
at nameplate efficiency and the budgeted availability. The bridge from budget to actual margin is made of
re-runs: market (prices and procurement of one year against the year before), efficiency (nameplate against
measured), availability (budgeted against measured), fixed costs. Every step is computed, none is a residual.

Usage:
    runs = run_all(site, days, workers=4)
    table = compare(site, runs)
    sim = simulate_year(site, days, runs, tech_monthly, workers=4)
"""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd

from bess_report.financial import Bridge, statement
from bess_report.schema import FIXED_COST_LINES, Site
from bess_report.strategies import REVENUE_COLUMNS, DayData, margin, run_strategy

log = logging.getLogger(__name__)
STEP_MARKET, STEP_RTE = "Market vs prior year", "RTE vs nameplate"
STEP_AVAILABILITY, STEP_FIXED = "Availability vs budget", "Fixed costs vs budget"
INFORMATION = {
    "da_perfect": "prices of the delivery day (ceiling, not tradeable)",
    "da_asof": "day-ahead prices of the previous 7 days",
    "stack_perfect": "prices of the delivery day, all products (ceiling, not tradeable)",
    "stack_asof": "day-ahead and capacity prices of the previous 7 days",
    "toll": "contract terms",
    "cm": "day-ahead prices of the previous 7 days, contract terms",
}
SHORT = {"da_perfect": "DA arbitrage, perfect foresight", "da_asof": "DA arbitrage, as-of",
         "stack_perfect": "Stack, perfect foresight", "stack_asof": "Stack, as-of", "toll": "Tolling"}
LABELS = {
    "da_perfect": "Day-ahead arbitrage, perfect foresight",
    "da_asof": "Day-ahead arbitrage, as-of forecast",
    "stack_perfect": "Revenue stack, perfect foresight",
    "stack_asof": "Revenue stack (day-ahead + balancing capacity), as-of forecast",
    "toll": "Tolling",
    "cm": "Day-ahead arbitrage + capacity market",
}


def margin_by_month(daily: pd.DataFrame) -> pd.Series:
    """Gross margin of a run summed per month (index YYYY-MM)."""
    s = margin(daily)
    return s.groupby(pd.PeriodIndex(pd.to_datetime(s.index), freq="M").astype(str)).sum()


def month_labels(first: date, last: date) -> list[str]:
    return [f"{p}" for p in pd.period_range(first, last, freq="M")]


def run_all(site: Site, days: list[DayData], workers: int = 1) -> dict[str, pd.DataFrame]:
    """The four market strategies over the site's period at nameplate efficiency."""
    out = {}
    for kind in ("da", "stack"):
        for mode in ("perfect", "asof"):
            out[f"{kind}_{mode}"] = run_strategy(days, kind, mode, site.battery, site.first_day, site.last_day,
                                                 workers=workers)
    return out


def capacity_market_terms(auction: int) -> dict:
    from bess_stack.capacity_market import capacity_layer

    layer = capacity_layer()
    if auction not in layer.index:
        raise ValueError(f"no capacity market terms for delivery year {auction}; known: {list(layer.index)}")
    r = layer.loc[auction]
    return {"auction": int(auction), "closing_price_pln_kw_year": float(r["closing_price_pln_kw_year"]),
            "kwd": float(r["kwd_battery"]), "pln_per_mw_year": float(r["revenue_pln_mw_year"]),
            "price_source": str(r["price_source"]), "kwd_source": str(r["kwd_source"])}


def _stats(monthly_pln: pd.Series, mw: float, days: int, discharged: float, label: str) -> dict:
    per_mw = monthly_pln / mw
    return {"total_pln": float(monthly_pln.sum()), "pln_per_mw_year": float(monthly_pln.sum() * 365.0 / days / mw),
            "month_mean_pln_per_mw": float(per_mw.mean()), "month_std_pln_per_mw": float(per_mw.std(ddof=0)),
            "month_worst_pln_per_mw": float(per_mw.min()), "month_best_pln_per_mw": float(per_mw.max()),
            "months_below_half_of_mean": int((per_mw < 0.5 * per_mw.mean()).sum()),
            "discharged_mwh_per_year": float(discharged * 365.0 / days), "label": label}


def compare(site: Site, runs: dict[str, pd.DataFrame], availability: float | None = None) -> pd.DataFrame:
    """One row per strategy on the common evaluation: gross margin per MW and year at the assumed availability,
    share of the perfect-foresight ceiling, spread over the months, cycles. Margin is net of purchases and the
    degradation allowance, before fixed costs."""
    a = availability if availability is not None else site.guarantees.get("availability", 1.0)
    mw, e = site.battery.power_mw, site.battery.energy_mwh
    usable = e * (site.battery.soc_max - site.battery.soc_min)
    days = len(runs["da_asof"])
    rows, margins = [], {}
    for name, d in runs.items():
        margins[name] = margin_by_month(d) * a
        r = _stats(margins[name], mw, days, d["discharged_mwh"].sum(), LABELS[name])
        r.update(id=name, information=INFORMATION[name], market_risk="owner")
        r["cycles_per_day"] = float(d["discharged_mwh"].sum() / days / usable)
        rows.append(r)
    ceilings = {"da_asof": "da_perfect", "stack_asof": "stack_perfect"}
    index = pd.Index(margins["da_asof"].index)
    if site.toll:
        toll = pd.Series([site.toll["pln_per_mw_year"] * mw / 12.0 * a] * len(index), index=index)
        r = _stats(toll, mw, days, 0.0, LABELS["toll"])
        r.update(id="toll", information=INFORMATION["toll"], market_risk="offtaker", cycles_per_day=0.0)
        rows.append(r)
    terms = []
    for auction in (site.capacity_market or {}).get("auctions", []):
        t = capacity_market_terms(int(auction))
        cm = pd.Series(t["pln_per_mw_year"] * mw / 12.0 * a, index=index)
        r = _stats(margins["da_asof"] + cm, mw, days, runs["da_asof"]["discharged_mwh"].sum(),
                   f"{LABELS['cm']} (auction for delivery in {auction})")
        r.update(id=f"cm_{auction}", information=INFORMATION["cm"], market_risk="owner",
                 cycles_per_day=float(runs["da_asof"]["discharged_mwh"].sum() / days / usable))
        rows.append(r)
        terms.append(t)
    out = pd.DataFrame(rows).set_index("id")
    out["short"] = [SHORT.get(i, f"DA + capacity market, {i[3:]} terms") for i in out.index]
    out["share_of_ceiling"] = np.nan
    for k, c in ceilings.items():
        out.loc[k, "share_of_ceiling"] = out.loc[k, "total_pln"] / out.loc[c, "total_pln"]
    out.attrs.update(availability=a, days=days, capacity_market=terms, first_day=str(runs["da_asof"].index.min()),
                     last_day=str(runs["da_asof"].index.max()))
    return out


def _lines(daily: pd.DataFrame) -> pd.DataFrame:
    """Monthly sums of the settlement lines of a run (cost lines positive)."""
    m = daily.groupby(pd.PeriodIndex(pd.to_datetime(daily.index), freq="M").astype(str)).sum()
    out = m[["da_sales", "fcr_capacity", "afrr_capacity", "mfrrd_capacity", "rr_capacity"]].copy()
    out["da_purchases"] = -m["da_purchases"]
    out["degradation"] = m["degradation"]
    return out


def _to_money(lines: pd.DataFrame, factor: pd.Series, extra: pd.DataFrame | None = None) -> pd.DataFrame:
    """Wide monthly lines -> the long money table of the schema, scaled by ``factor`` per month."""
    wide = lines.mul(factor, axis=0)
    if extra is not None:
        wide = wide.join(extra)
    long = wide.stack().rename("value_pln").reset_index()
    long.columns = ["month", "line", "value_pln"]
    return long


def fixed_costs(site: Site, months: list[str]) -> pd.DataFrame:
    rows = [(m, k, v * site.battery.power_mw / 12.0) for m in months for k, v in site.opex_pln_per_mw_year.items()
            if k in FIXED_COST_LINES]
    return pd.DataFrame(rows, columns=["month", "line", "value_pln"])


def simulate_year(site: Site, days: list[DayData], runs: dict[str, pd.DataFrame], tech: pd.DataFrame,
                  workers: int = 1) -> dict:
    """Settlement and budget tables, their statements and the bridge, for the revenue stack as-of."""
    months = month_labels(site.first_day, site.last_day)
    budget_a = site.budget.get("availability", site.guarantees.get("availability", 1.0))
    nameplate = site.battery.round_trip_efficiency
    rte = tech["rte"].reindex(months)
    rte_by_month = {m: float(v) for m, v in rte.items() if pd.notna(v)}
    avail = tech["availability"].reindex(months)
    if avail.isna().any():
        raise ValueError(f"technical report has no availability for {list(avail.index[avail.isna()])}")

    nominal = _lines(runs["stack_asof"])
    measured = _lines(run_strategy(days, "stack", "asof", site.battery, site.first_day, site.last_day,
                                   rte_by_month=rte_by_month, workers=workers))
    prev_first, prev_last = (site.first_day.replace(year=site.first_day.year - 1),
                             site.last_day.replace(year=site.last_day.year - 1))
    prior = _lines(run_strategy(days, "stack", "asof", site.battery, prev_first, prev_last, workers=workers))
    prior.index = months

    cm_extra = None
    if (site.capacity_market or {}).get("auctions"):
        t = capacity_market_terms(int(site.capacity_market["auctions"][0]))
        cm_extra = pd.DataFrame({"capacity_market": t["pln_per_mw_year"] * site.battery.power_mw / 12.0}, index=months)
    actual = _to_money(measured, avail, None if cm_extra is None else cm_extra.mul(avail, axis=0))
    budget = _to_money(prior, pd.Series(budget_a, index=months), None if cm_extra is None else cm_extra * budget_a)
    fixed = fixed_costs(site, months)
    actual, budget = pd.concat([actual, fixed], ignore_index=True), pd.concat([budget, fixed], ignore_index=True)
    sa, sb = statement(actual, months), statement(budget, months)

    gm = lambda lines, f, extra=None: float((statement(_to_money(lines, f, extra), months)["gross_margin"]).sum())   # noqa: E731
    flat = pd.Series(budget_a, index=months)
    cm_b = None if cm_extra is None else cm_extra * budget_a
    g_budget = gm(prior, flat, cm_b)
    g_market = gm(nominal, flat, cm_b)
    g_rte = gm(measured, flat, cm_b)
    g_actual = gm(measured, avail, None if cm_extra is None else cm_extra.mul(avail, axis=0))
    opex_delta = 0.0 - (float(sa["fixed_costs"].sum()) - float(sb["fixed_costs"].sum()))
    bridge = Bridge("Budget margin", float(sb["margin"].sum()),
                    [(STEP_MARKET, g_market - g_budget),
                     (STEP_RTE, g_rte - g_market),
                     (STEP_AVAILABILITY, g_actual - g_rte),
                     (STEP_FIXED, opex_delta)],
                    "Actual margin (simulated)", float(sa["margin"].sum()))
    bridge.check()
    return {"settlement": actual, "budget": budget, "statement": sa, "budget_statement": sb, "bridge": bridge,
            "assumptions": {"budget_availability": budget_a, "nameplate_rte": nameplate,
                            "measured_rte_mean": float(rte.mean()), "measured_availability_mean": float(avail.mean()),
                            "budget_rule": "same strategy, same calendar months one year earlier, nameplate "
                                           "efficiency, budgeted availability"},
            "measured_lines": measured, "nominal_lines": nominal, "prior_lines": prior}
