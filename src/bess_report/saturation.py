"""What happens to the revenue stack when many batteries chase the same balancing capacity?

A single battery that is a price taker earns the clearing prices as they were. A fleet lowers them: the offer
stacks PSE publishes for the day-ahead balancing capacity procurement are flooded with a block of F megawatts of
identical batteries (the model of ``bess_stack.saturation`` in pl-bess-revenue-stack: demand as bought, existing
offers unchanged, pro-rata acceptance, perfect foresight, prices and schedules iterated with damping).

The iteration is a best response to the prices that follow from a damped average of past schedules, not a fixed
point, so the model gives two numbers per fleet size and neither is the equilibrium:

- ``best response``: the revenue of the last schedule at the prices the damped average implies (what
  ``fleet_equilibrium`` reports); an upper bound, because the fleet does not offer that average, and
- ``settled``: the same last schedule settled on the market that results when every battery actually offers it
  (prices and pro-rata acceptance recomputed from the offers made); the batteries are identical, so all react in
  the same way and this is a lower bound.

``fleet_table`` turns both into the share of the lone battery's revenue that is kept, and into the as-of stack margin
of the strategy comparison at that fleet size (the lone as-of margin times the share kept, which assumes the as-of
plan loses the same share), next to the day-ahead arbitrage, whose prices the model does not move.

The offer stacks are large, so they are read from the cache of pl-bess-revenue-stack (``--stack-data-dir``); the
committed result is ``results/saturation_fleet.csv``.

Usage:
    python -m bess_report saturation --site config/site.example.yaml --stack-data-dir ../pl-bess-revenue-stack/data
"""
from __future__ import annotations

import logging
from contextlib import nullcontext
from concurrent.futures import ProcessPoolExecutor
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


def prices_and_limits(st, rows, fleet: float, reserves: np.ndarray, power_mw: float):
    """Capacity prices and the MW one battery can be accepted for, per hour and product, when ``fleet`` MW of batteries
    each offer ``reserves`` (hours x products), the existing offers staying as they are."""
    from bess_stack.pse_api import PRODUCTS
    from bess_stack.saturation import clear

    pr = np.full((len(rows), len(PRODUCTS)), np.nan)
    lim = np.zeros((len(rows), len(PRODUCTS)))
    for j, k in enumerate(PRODUCTS):
        price, _ = clear(st, k, fleet * reserves[:, j], 0.0, rows)
        pr[:, j] = price
        dem = st.demand[k].to_numpy()[rows]
        q = st.cum[k][rows]
        below = np.where(st.price[k][rows] < 0.0, np.diff(np.concatenate([np.zeros((len(rows), 1)), q], axis=1), axis=1),
                         0.0).sum(axis=1)
        lim[:, j] = np.clip((dem - below) / fleet, 0.0, power_mw)
    return pr, lim


def equilibrium_bounds(days, st, cfg, fleets, iterations: int = 8, damping: float = 0.5,
                       workers: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per fleet size, per MW of battery power and year: the revenue as ``fleet_equilibrium`` reports it (best
    response to the damped prices) and the same last schedule settled on the offers actually made."""
    from bess_stack.backtest import default_workers, run_configs
    from bess_stack.pse_api import PRODUCTS
    from bess_stack.saturation import _day_rows

    rows_of = _day_rows(st, days)
    ref = [d for d in days if d.business_date in rows_of]
    if not ref:
        raise ValueError("no days with offer stacks")
    workers = workers or default_workers()
    power = cfg.params.power_mw
    out, conv = [], []
    pool = nullcontext(None) if workers == 1 else ProcessPoolExecutor(max_workers=workers)
    with pool as ex:
        base = run_configs(ref, [cfg], workers=workers, keep_reserves=True, executor=ex)
        base_r = dict(zip(base["business_date"], base["reserves"]))
        for fleet in fleets:
            r_bar = {k: v.copy() for k, v in base_r.items()}
            result, new_r = base, base_r
            for it in range(iterations if fleet > 0 else 0):
                prices, limits = {}, {}
                for d in ref:
                    prices[d.business_date], limits[d.business_date] = prices_and_limits(
                        st, rows_of[d.business_date], fleet, r_bar[d.business_date], power)
                result = run_configs(ref, [cfg], workers=workers, keep_reserves=True, reserve_prices=prices,
                                     reserve_limits=limits, executor=ex)
                new_r = dict(zip(result["business_date"], result["reserves"]))
                change = float(np.mean([np.abs(new_r[k] - r_bar[k]).mean() for k in r_bar]))
                r_bar = {k: damping * new_r[k] + (1 - damping) * r_bar[k] for k in r_bar}
                conv.append({"fleet_mw": fleet, "iteration": it + 1, "mean_abs_change_mw": change,
                             "best_response_per_year": float(result["total"].mean() * 365)})
                log.info("fleet %s MW, iteration %d: best response %.0f PLN/MW/yr, schedule change %.4f MW", fleet,
                         it + 1, result["total"].mean() * 365, change)
            # the same last schedule on the market its own offers create
            settled = []
            for _, row in result.iterrows():
                d = row["business_date"]
                if fleet > 0:
                    pr, lim = prices_and_limits(st, rows_of[d], fleet, new_r[d], power)
                    accepted = np.minimum(new_r[d], lim)
                    reserve_revenue = float(np.sum(np.nan_to_num(pr) * accepted))
                else:
                    reserve_revenue = float(sum(row[f"rev_{k}"] for k in PRODUCTS))
                settled.append(row["arbitrage"] - row["degradation"] + reserve_revenue)
            rec = {"fleet_mw": fleet, "days": len(result), "best_response": float(result["total"].mean() * 365),
                   "settled": float(np.mean(settled) * 365),
                   "reserves_best_response": float(sum(result[f"rev_{k}"] for k in PRODUCTS).mean() * 365)}
            out.append(rec)
    return pd.DataFrame(out).set_index("fleet_mw"), pd.DataFrame(conv)


def run_fleet(site, days, stack_dir: Path, fleets=FLEETS_MW, iterations: int = 8, workers: int = 1) -> pd.DataFrame:
    """``equilibrium_bounds`` for the stacked strategy of the site's battery on the site's period."""
    from bess_stack.backtest import Day, RunConfig

    st = load_stacks(stack_dir, site.first_day, site.last_day)
    unit = st.hours.dtype
    sel = [Day(d.business_date, pd.DatetimeIndex(d.hours).astype(unit), d.prices, d.hour_of, d.reserve_prices)
           for d in days if site.first_day <= d.business_date <= site.last_day]
    cfg = RunConfig("stacked", site.battery.params(), "stacked")
    summary, conv = equilibrium_bounds(sel, st, cfg, list(fleets), iterations=iterations, workers=workers)
    summary.attrs["convergence"] = conv
    return summary


def fleet_table(raw: pd.DataFrame, strategies: pd.DataFrame, availability: float = 1.0) -> pd.DataFrame:
    """One row per fleet size: the lone battery's revenue kept (settled and best response), the as-of stack margin of
    the strategy comparison scaled by those shares, and the day-ahead as-of margin that the fleet does not move. The
    perfect-foresight columns are at the assumed availability like every other column of the comparison."""
    base = float(raw.loc[0, "best_response"])
    out = pd.DataFrame(index=raw.index)
    out["perfect_settled_pln_per_mw_year"] = raw["settled"] * availability
    out["perfect_best_response_pln_per_mw_year"] = raw["best_response"] * availability
    out["retention_settled"] = raw["settled"] / base
    out["retention_best_response"] = raw["best_response"] / base
    lone = strategies.loc["stack_asof", "pln_per_mw_year"]
    out["stack_asof_settled_pln_per_mw_year"] = lone * out["retention_settled"]
    out["stack_asof_best_response_pln_per_mw_year"] = lone * out["retention_best_response"]
    out["da_asof_pln_per_mw_year"] = strategies.loc["da_asof", "pln_per_mw_year"]
    return out


def breakeven_fleet_mw(table: pd.DataFrame, column: str = "stack_asof_settled_pln_per_mw_year") -> float | None:
    """Fleet size at which the scaled as-of stack falls to the day-ahead as-of margin (linear interpolation between
    the fleet sizes run); None if it does not within the sizes run."""
    d = table[column] - table["da_asof_pln_per_mw_year"]
    x, y = table.index.to_numpy(float), d.to_numpy(float)
    for i in range(1, len(x)):
        if y[i - 1] > 0 >= y[i]:
            return float(x[i - 1] + (x[i] - x[i - 1]) * y[i - 1] / (y[i - 1] - y[i]))
    return None
