"""The bundled example: technical, financial and strategy reports from open data, and every number of the README.

Inputs (committed in ``data/example``): the AEMO rows of one NEM battery (5-minute SCADA, dispatch, registration,
bids with declared availability) and the PSE day-ahead and balancing capacity prices of two years. The EMS path
uses the synthetic battery of bess-ops-warranty, whose truth is known.

Outputs: ``results/`` (tables and ``summary.json``, the only source of the README numbers), ``docs/report`` (HTML and
Excel reports, charts in ``docs/report/img``).

Usage:
    python -m bess_report example --workers 4
"""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from bess_report import data as pse_data
from bess_report import reports, scenario
from bess_report.financial import revenue_mix, variance
from bess_report.nemslice import load_slice
from bess_report.schema import LINES, load_site
from bess_report.strategies import LOOKBACK_DAYS, build_days, margin
from bess_report.technical import analyse_ems, from_ems, from_nem

log = logging.getLogger(__name__)
NEM_DUID = "RANGEB1"


def _clean(o):
    """JSON-safe copy: numpy scalars to Python, NaN to None, Periods and dates to text."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, pd.Period)) or hasattr(o, "isoformat"):
        return str(o)
    return o


def ems_demo(work: Path):
    """The synthetic EMS battery: simulated, written like a real export, analysed by bess-ops-warranty."""
    from bess_ops.study import analyse_demo

    _, _, res = analyse_demo(work, 1)
    return res


def run(root: Path, site_path: Path, workers: int = 1, nem_duid: str = NEM_DUID) -> dict:
    site = load_site(site_path)
    results, docs = root / "results", root / "docs"
    results.mkdir(exist_ok=True)
    out = {"site": site.name}

    # technical, open data (NEM) and the EMS path (synthetic battery with known truth)
    nem = from_nem(load_slice(root / "data/example/nem"), nem_duid, site.guarantees)
    with tempfile.TemporaryDirectory() as tmp:
        ems = from_ems(ems_demo(Path(tmp)))
    paths = {}
    for tag, rep, g in (("nem", nem, site.guarantees), ("ems", ems, {})):
        paths[tag] = reports.technical_report(rep, g, docs / "report", tag)
        rep.monthly.to_csv(results / f"technical_{tag}_monthly.csv")
        rep.compliance.to_csv(results / f"technical_{tag}_compliance.csv")
        if rep.soh is not None:
            rep.soh.to_csv(results / f"technical_{tag}_soh.csv")
    out["technical_nem"], out["technical_ems"] = nem.summary, ems.summary
    out["technical_nem"]["soh_table"] = nem.soh.reset_index().to_dict("records")

    # trading report of the same battery: metered energy margin against benchmarks on the same prices
    from bess_ops.nem import unit_site

    from bess_report import nem_trading
    from bess_report.nemslice import load_prices
    cache = load_slice(root / "data/example/nem")
    tr = nem_trading.run(unit_site(cache, nem_duid), load_prices(root / "data/example/nem"), nem.summary["rte"],
                         nem.summary["mw"], nem.summary["mwh"], workers)
    tr["monthly"].to_csv(results / "nem_trading_monthly.csv")
    tr["bridge"].frame().to_csv(results / "nem_trading_bridge.csv", index=False)
    reports.nem_trading_report(tr, nem.summary["name"], docs / "report")
    out["nem_trading"] = {**tr["summary"], "bridge": {f"step{i}": {"label": k, "value": v}
                                                      for i, (k, v) in enumerate(tr["bridge"].steps)},
                          "start": tr["bridge"].start, "end": tr["bridge"].end}

    # strategies on one evaluation
    prices, capacity = pse_data.load_slice(root / "data/example")
    days = build_days(prices, capacity)
    runs = scenario.run_all(site, days, workers)
    runs = scenario.with_activation(site, runs, prices, pse_data.load_activation(root / "data/example"))
    table = scenario.compare(site, runs)
    a = table.attrs["availability"]
    monthly = pd.DataFrame({k: scenario.margin_by_month(runs[k]) * a / site.battery.power_mw for k in runs})
    monthly["toll"] = site.toll["pln_per_mw_year"] / 12.0 * a if site.toll else np.nan
    for t in table.attrs["capacity_market"]:
        monthly[f"cm_{t['auction']}"] = monthly["da_asof"] + t["pln_per_mw_year"] / 12.0 * a
    table.to_csv(results / "strategy_comparison.csv")
    sens = scenario.forecast_sensitivity(site, days, runs, workers=workers)
    sens.to_csv(results / "forecast_sensitivity.csv", index=False)
    monthly.to_csv(results / "strategy_monthly_margin_per_mw.csv")
    pd.DataFrame({k: margin(v) for k, v in runs.items()}).to_csv(results / "strategy_daily_margin.csv")
    sat = None
    if (results / "saturation_fleet.csv").exists():                 # written by the separate `saturation` command
        sat = pd.read_csv(results / "saturation_fleet.csv", index_col="fleet_mw")
    paths["strategies"] = reports.strategy_report(table, monthly.dropna(axis=1, how="all"), site, docs / "report",
                                                  saturation=sat, sensitivity=sens)

    # financial: simulated settlement, budget and bridge, with the technical report's availability and RTE
    sim = scenario.simulate_year(site, days, runs, nem.monthly, workers)
    sim["settlement"].to_csv(results / "settlement.csv", index=False)
    sim["budget"].to_csv(results / "budget.csv", index=False)
    sim["statement"].to_csv(results / "financial_statement.csv")
    sim["bridge"].frame().to_csv(results / "financial_bridge.csv", index=False)
    paths["financial"] = reports.financial_report(sim, site, docs / "report")
    var = variance(sim["statement"], sim["budget_statement"])
    var.to_csv(results / "financial_variance.csv")
    mix = revenue_mix(sim["statement"])
    mix.to_csv(results / "financial_revenue_mix.csv")

    out["strategies"] = {i: {k: v for k, v in r.items() if k != "label"} for i, r in table.to_dict("index").items()}
    out["forecast_sensitivity"] = {f"{r.strategy}_{r.lookback_days}": {"pln_per_mw_year": r.pln_per_mw_year,
                                                                       "share_of_ceiling": r.share_of_ceiling}
                                   for r in sens.itertuples()}
    out["strategy_meta"] = {"availability": a, "days": table.attrs["days"], "first_day": table.attrs["first_day"],
                            "last_day": table.attrs["last_day"], "capacity_market": table.attrs["capacity_market"]}
    if sat is not None:
        from bess_report.saturation import breakeven_fleet_mw
        rows = {str(int(k)): v for k, v in sat.to_dict("index").items()}
        conv = pd.read_csv(results / "saturation_convergence.csv")
        last = conv.groupby("fleet_mw").last()
        for k in rows:
            if int(k) in last.index:
                rows[k]["last_schedule_change_mw"] = float(last.loc[int(k), "mean_abs_change_mw"])
        out["saturation"] = {"rows": rows, "breakeven_fleet_mw": breakeven_fleet_mw(sat),
                             "iterations": int(conv["iteration"].max())}
    out["financial"] = {
        "bridge": {"start": sim["bridge"].start, "end": sim["bridge"].end,
                   "steps": {f"step{i}": {"label": k, "value": v} for i, (k, v) in enumerate(sim["bridge"].steps)}},
        "variance": var.rename(index=LINES).to_dict("index"), "mix": mix.rename(index=LINES).to_dict("index"), "assumptions": sim["assumptions"],
        "totals": sim["statement"].sum().to_dict(), "budget_totals": sim["budget_statement"].sum().to_dict()}
    out["assumptions"] = {"lookback_days": LOOKBACK_DAYS, "battery": site.battery.__dict__,
                          "guarantees": site.guarantees, "opex": site.opex_pln_per_mw_year, "toll": site.toll,
                          "budget": site.budget, "period": {"start": str(site.first_day), "end": str(site.last_day)}}
    (results / "summary.json").write_text(json.dumps(_clean(out), indent=2, ensure_ascii=False), encoding="utf-8")

    log.info("example written to %s", root)
    return out
