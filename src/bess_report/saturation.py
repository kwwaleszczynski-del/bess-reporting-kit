"""What happens to the revenue stack when many batteries chase the same balancing capacity?

A single battery that is a price taker earns the clearing prices as they were. A fleet lowers them: the offer
stacks PSE publishes for the day-ahead balancing capacity procurement are flooded with a block of F megawatts of
identical batteries (``bess_stack.saturation.fleet_equilibrium`` of pl-bess-revenue-stack: demand as bought, existing
offers unchanged, pro-rata acceptance, prices and schedules iterated to a fixed point). That model has perfect
foresight; ``fleet_table`` turns its result into the share of the lone-battery revenue that is kept at each fleet size
and, under the stated assumption that the as-of plan loses the same share, the as-of stack margin of the strategy
comparison at that fleet size, next to the day-ahead arbitrage (whose prices the model does not move).

The offer stacks are large, so they are read from the cache of pl-bess-revenue-stack (``--stack-data-dir``); the
committed result is ``results/saturation_fleet.csv``.

Usage:
    python -m bess_report saturation --site config/site.example.yaml --stack-data-dir ../pl-bess-revenue-stack/data
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)
FLEETS_MW = (0, 250, 500, 1000, 2000)


def load_stacks(stack_dir: Path, first_day, last_day):
    """Offer stacks, bought volumes and prices of the period from the monthly Parquet files of the cache."""
    from bess_stack.saturation import build_stacks

    months = [f"{p}" for p in pd.period_range(first_day, last_day, freq="M")]

    def read(name):
        frames = [pd.read_parquet(stack_dir / f"{name}_{m}.parquet") for m in months]
        out = pd.concat(frames).sort_index(kind="stable")
        return out[(out["business_date"] >= first_day) & (out["business_date"] <= last_day)]

    offers, volume, price = read("offers"), read("cap_volume"), read("cap_price")
    return build_stacks(offers, volume, price)


def run_fleet(site, days, stack_dir: Path, fleets=FLEETS_MW, iterations: int = 6, workers: int = 1) -> pd.DataFrame:
    """Perfect-foresight stack revenue per MW and year at each fleet size (``fleet_equilibrium``)."""
    from bess_stack.backtest import Day, RunConfig
    from bess_stack.saturation import fleet_equilibrium

    st = load_stacks(stack_dir, site.first_day, site.last_day)
    unit = st.hours.dtype
    sel = [Day(d.business_date, pd.DatetimeIndex(d.hours).astype(unit), d.prices, d.hour_of, d.reserve_prices)
           for d in days if site.first_day <= d.business_date <= site.last_day]
    cfg = RunConfig("stacked", site.battery.params(), "stacked")
    summary, conv = fleet_equilibrium(sel, st, cfg, list(fleets), iterations=iterations, workers=workers)
    summary.attrs["convergence"] = conv
    return summary


def fleet_table(summary: pd.DataFrame, strategies: pd.DataFrame) -> pd.DataFrame:
    """One row per fleet size: perfect-foresight stack margin, share of the lone battery's, the as-of stack margin
    scaled by that share, the unchanged day-ahead as-of margin, and the stack's share of revenue from reserves."""
    base = float(summary.loc[0, "total"])
    out = pd.DataFrame(index=summary.index)
    out["perfect_pln_per_mw_year"] = summary["total"]
    out["retention"] = summary["total"] / base
    out["stack_asof_scaled_pln_per_mw_year"] = strategies.loc["stack_asof", "pln_per_mw_year"] * out["retention"]
    out["da_asof_pln_per_mw_year"] = strategies.loc["da_asof", "pln_per_mw_year"]
    out["reserve_share"] = summary["reserves"] / summary["total"].where(summary["total"] != 0)
    return out


def breakeven_fleet_mw(table: pd.DataFrame) -> float | None:
    """Fleet size at which the scaled as-of stack falls to the day-ahead as-of margin (linear interpolation between
    the fleet sizes run); None if it does not within the sizes run."""
    d = table["stack_asof_scaled_pln_per_mw_year"] - table["da_asof_pln_per_mw_year"]
    x, y = table.index.to_numpy(float), d.to_numpy(float)
    for i in range(1, len(x)):
        if y[i - 1] > 0 >= y[i]:
            return float(x[i - 1] + (x[i] - x[i - 1]) * y[i - 1] / (y[i - 1] - y[i]))
    return None
