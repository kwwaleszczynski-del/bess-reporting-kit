"""Trading report of a battery on open market data: what it earned on the energy market against what a battery of the
same size could have earned on the same prices.

For one NEM battery the actual energy margin is the metered power times the regional reference price (RRP) of every
5-minute interval: exports earn, imports cost. Two benchmarks are run on the same intervals and days with the same
optimiser (``bess_stack.optimizer``, arbitrage only, the registered power and energy, the measured round-trip
efficiency, no degradation cost, since the actual margin has none either):

- perfect foresight: the prices of the day are known (a ceiling no one can trade);
- as-of: the forecast of every interval is the mean of the same time over the previous 7 days, the plan is settled on
  the actual prices.

``bridge`` walks from the perfect-foresight margin to the actual one: forecast (as-of against perfect) and the rest
(actual against as-of). The rest is everything the energy benchmark does not know: frequency control services
(the energy-only view leaves out their revenue, usually the larger part for a grid battery), availability, state
of charge limits, the operator's own forecast. It is not a verdict on the operator.

Usage:
    res = run(site_frame, prices, rte=0.83, power_mw=200, energy_mwh=400, workers=4)
    res["monthly"], res["bridge"]
"""
from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from bess_report.financial import Bridge

log = logging.getLogger(__name__)
DT_H = 5 / 60
SLOTS = 288
LOOKBACK = 7


def _solve(task):
    from bess_stack.optimizer import STRATEGIES, BatteryParams, optimize_day

    plan_prices, actual, params = task
    res = optimize_day(plan_prices, np.zeros(len(plan_prices), int), np.full((1, 7), np.nan), params,
                       STRATEGIES["arbitrage"], dt_hours=DT_H)
    net = res.schedule["discharge_mw"].to_numpy() - res.schedule["charge_mw"].to_numpy()
    return float(np.sum(net * actual * DT_H))


def run(site: pd.DataFrame, prices: pd.Series, rte: float, power_mw: float, energy_mwh: float,
        workers: int = 1, tz: str = "Australia/Brisbane") -> dict:
    """Monthly energy margin of the metered battery and of the two benchmarks; ``site`` is the ``unit_site`` frame
    of bess_ops.nem (column ``p_meter``, MW, positive when exporting)."""
    from bess_stack.optimizer import BatteryParams

    local = site.index.tz_convert(tz).tz_localize(None)
    p = pd.Series(site["p_meter"].to_numpy(float), index=local)
    px = prices.reindex(p.index)
    frame = pd.DataFrame({"p": p, "rrp": px})
    frame["day"] = frame.index.normalize()
    complete = frame.groupby("day").apply(lambda g: len(g) == SLOTS and g.notna().all().all(), include_groups=False)
    days = list(complete[complete].index)
    by_day = {d: frame[frame["day"] == d] for d in days}
    params = BatteryParams(power_mw=power_mw, energy_mwh=energy_mwh, round_trip_efficiency=rte,
                           max_cycles_per_day=1.5, degradation_cost=0.0)

    rows, tasks = [], []
    for i, d in enumerate(days):
        g = by_day[d]
        actual = g["rrp"].to_numpy()
        prev = [days[j] for j in range(max(0, i - 2 * LOOKBACK), i) if 1 <= (d - days[j]).days <= LOOKBACK]
        if len(prev) < LOOKBACK:
            continue
        forecast = np.mean([by_day[x]["rrp"].to_numpy() for x in prev], axis=0)
        mw = g["p"].to_numpy()
        rows.append({"day": d, "export": float(np.sum(np.clip(mw, 0, None) * actual * DT_H)),
                     "import": float(-np.sum(np.clip(mw, None, 0) * actual * DT_H)),
                     "export_mwh": float(np.sum(np.clip(mw, 0, None)) * DT_H),
                     "import_mwh": float(-np.sum(np.clip(mw, None, 0)) * DT_H)})
        tasks.append((forecast, actual, params))
        tasks.append((actual, actual, params))
    if workers > 1:
        with ProcessPoolExecutor(workers) as pool:
            res = list(pool.map(_solve, tasks, chunksize=4))
    else:
        res = [_solve(t) for t in tasks]
    daily = pd.DataFrame(rows).set_index("day")
    daily["asof"], daily["perfect"] = res[0::2], res[1::2]
    daily["actual"] = daily["export"] - daily["import"]
    month = daily.index.to_period("M").astype(str)
    monthly = daily.groupby(month).sum()
    monthly.index.name = "month"
    monthly["days"] = daily.groupby(month).size()
    monthly["capture_vs_asof"] = monthly["actual"] / monthly["asof"].where(monthly["asof"] != 0)
    monthly["capture_vs_perfect"] = monthly["actual"] / monthly["perfect"].where(monthly["perfect"] != 0)
    tot = daily[["actual", "asof", "perfect"]].sum()
    bridge = Bridge("Perfect foresight (ceiling)", float(tot["perfect"]),
                    [("Forecast: as-of vs perfect", float(tot["asof"] - tot["perfect"])),
                     ("Operation vs as-of benchmark", float(tot["actual"] - tot["asof"]))],
                    "Actual energy margin", float(tot["actual"]))
    bridge.check()
    return {"daily": daily, "monthly": monthly, "bridge": bridge,
            "summary": {"days": int(len(daily)), "first_day": str(daily.index.min().date()),
                        "last_day": str(daily.index.max().date()), "rte": rte, "power_mw": power_mw,
                        "energy_mwh": energy_mwh, "actual": float(tot["actual"]), "asof": float(tot["asof"]),
                        "perfect": float(tot["perfect"]), "export": float(daily["export"].sum()),
                        "import": float(daily["import"].sum()),
                        "capture_vs_asof": float(tot["actual"] / tot["asof"]),
                        "capture_vs_perfect": float(tot["actual"] / tot["perfect"]),
                        "actual_per_mw_year": float(tot["actual"] * 365.0 / len(daily) / power_mw),
                        "asof_per_mw_year": float(tot["asof"] * 365.0 / len(daily) / power_mw),
                        "perfect_per_mw_year": float(tot["perfect"] * 365.0 / len(daily) / power_mw)}}
