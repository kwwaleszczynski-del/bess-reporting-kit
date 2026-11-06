"""Energy sales strategies of a grid battery, planned with an explicit information set and settled the same way.

Every strategy trades the same battery and is settled on the same published prices (SDAC clearing prices and the
prices of balancing capacity actually paid). They differ in what the plan for delivery day D may know:

- ``perfect``: the prices of D itself. Nobody can trade this; it is the ceiling a strategy is measured against.
- ``asof``: only data published before D. The forecast of every quarter-hour energy price is the mean of the same
  local time over the previous 7 days, the forecast of every capacity price the mean of the same local hour and
  product over the previous 7 days. A day is planned only when 7 earlier days exist. ``plan_inputs`` makes the
  information set explicit and a test checks that nothing from day D onwards can change a plan.

Strategies (the optimiser is ``bess_stack.optimizer.optimize_day`` of the pl-bess-revenue-stack project, a
mixed-integer program that co-optimises day-ahead arbitrage and balancing capacity under state-of-charge and
power-headroom rules):

- ``da``: day-ahead arbitrage only;
- ``stack``: arbitrage and balancing capacity (FCR, aFRR, mFRRd, RR) in the same hours; price taker, every MW
  offered is accepted at the clearing price of the day, activation energy is not modelled;
- ``toll``: a fixed payment per MW and year for the capacity, scaled by availability; the counterparty carries
  the market risk (contract terms are inputs, not market data);
- ``cm``: day-ahead arbitrage plus a capacity market (rynek mocy) payment, price times the de-rating factor of
  batteries (a contract term to verify against the current regulations; the delivery obligation in stress periods
  is not modelled).

Usage:
    days = build_days(prices, capacity)
    daily = run_strategy(days, "stack", "asof", battery, date(2025, 10, 1), date(2026, 9, 30), workers=4)
"""
from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from datetime import date

import numpy as np
import pandas as pd

from bess_report.data import PRODUCTS

log = logging.getLogger(__name__)
TZ = "Europe/Warsaw"
LOOKBACK_DAYS = 7
LINE_OF_PRODUCT = {"fcr_up": "fcr_capacity", "fcr_down": "fcr_capacity", "afrr_up": "afrr_capacity",
                   "afrr_down": "afrr_capacity", "mfrr_up": "mfrrd_capacity", "mfrr_down": "mfrrd_capacity",
                   "rr_up": "rr_capacity"}
REVENUE_COLUMNS = ["da_sales", "da_purchases", "fcr_capacity", "afrr_capacity", "mfrrd_capacity", "rr_capacity"]


@dataclass(frozen=True)
class Battery:
    """Battery and operating rules; the field names follow ``bess_stack.optimizer.BatteryParams``."""

    power_mw: float = 1.0
    energy_mwh: float = 2.0
    round_trip_efficiency: float = 0.87
    soc_min: float = 0.05
    soc_max: float = 0.95
    soc_start: float = 0.5
    max_cycles_per_day: float = 1.5
    degradation_cost: float = 30.0          # PLN per MWh discharged

    def params(self, rte: float | None = None):
        from bess_stack.optimizer import BatteryParams
        return BatteryParams(power_mw=self.power_mw, energy_mwh=self.energy_mwh,
                             round_trip_efficiency=self.round_trip_efficiency if rte is None else rte,
                             soc_min=self.soc_min, soc_max=self.soc_max, soc_start=self.soc_start,
                             max_cycles_per_day=self.max_cycles_per_day, degradation_cost=self.degradation_cost)


@dataclass(frozen=True)
class DayData:
    business_date: date
    minute: np.ndarray             # local minute of day of every quarter-hour
    prices: np.ndarray             # PLN/MWh per quarter-hour
    hours: pd.DatetimeIndex        # UTC start of each capacity hour
    local_hour: np.ndarray         # local hour of day of each capacity hour
    hour_of: np.ndarray            # capacity hour index of each quarter-hour
    reserve_prices: np.ndarray     # hours x PRODUCTS, PLN/MW per hour (NaN: not bought)


def build_days(prices: pd.DataFrame, capacity: pd.DataFrame) -> list[DayData]:
    """Pair quarter-hour prices with hourly capacity prices per business date; incomplete days are skipped."""
    out = []
    cap_by_day = dict(tuple(capacity[PRODUCTS].groupby(capacity["business_date"].to_numpy())))
    for d, e in prices.groupby(prices["business_date"].to_numpy()):
        n = len(e)
        if n not in (92, 96, 100) or e["price"].isna().any() or d not in cap_by_day:
            continue
        c = cap_by_day[d]
        hours = pd.DatetimeIndex(e.index.floor("h").unique())
        if len(c) != len(hours) or not c.index.equals(hours) or n != 4 * len(hours):
            continue
        local = e.index.tz_convert(TZ)
        out.append(DayData(d, (local.hour * 60 + local.minute).to_numpy(), e["price"].to_numpy(float), hours,
                           hours.tz_convert(TZ).hour.to_numpy(), hours.get_indexer(e.index.floor("h")),
                           c.to_numpy(float)))
    return out


def plan_inputs(days: list[DayData], i: int, lookback: int = LOOKBACK_DAYS) -> tuple[np.ndarray, np.ndarray] | None:
    """Forecast of the energy prices (per quarter-hour) and capacity prices (hours x products) of day ``i`` from
    the previous ``lookback`` (default ``LOOKBACK_DAYS``) calendar days only; None when fewer are available."""
    d = days[i]
    prev = [x for x in days[max(0, i - 2 * lookback):i]
            if 1 <= (d.business_date - x.business_date).days <= lookback]
    if len(prev) < lookback:
        return None
    e = pd.concat([pd.Series(x.prices).groupby(x.minute).mean() for x in prev], axis=1).mean(axis=1)
    # a short lookback can miss the local times that a daylight saving change removed from the previous day:
    # fill them from the neighbouring quarter-hours of the same average (still only past information)
    e = e.reindex(range(0, 1440, 15)).interpolate(limit_direction="both")
    energy = e.reindex(d.minute).to_numpy()
    by_hour = []
    for x in prev:
        m = pd.DataFrame(x.reserve_prices, columns=PRODUCTS).groupby(x.local_hour).mean()
        by_hour.append(m.reindex(range(24)).to_numpy())
    stack = np.stack(by_hour)
    count = (~np.isnan(stack)).sum(axis=0)
    mean = np.where(count > 0, np.nansum(stack, axis=0) / np.maximum(count, 1), np.nan)
    return energy, mean[d.local_hour]


def settle(day: DayData, res, battery: Battery) -> dict:
    """Result of a plan on the prices actually paid on the day."""
    dt = 0.25
    charge, discharge = res.schedule["charge_mw"].to_numpy(), res.schedule["discharge_mw"].to_numpy()
    out = {"business_date": day.business_date,
           "da_sales": float(np.sum(day.prices * dt * discharge)),
           "da_purchases": -float(np.sum(day.prices * dt * charge)),
           "discharged_mwh": float(discharge.sum() * dt), "charged_mwh": float(charge.sum() * dt)}
    out["degradation"] = battery.degradation_cost * out["discharged_mwh"]
    cap = {"fcr_capacity": 0.0, "afrr_capacity": 0.0, "mfrrd_capacity": 0.0, "rr_capacity": 0.0}
    r = res.reserves[PRODUCTS].to_numpy()
    paid = np.where(np.isnan(day.reserve_prices), 0.0, day.reserve_prices)
    for j, p in enumerate(PRODUCTS):
        cap[LINE_OF_PRODUCT[p]] += float(np.sum(paid[:, j] * r[:, j]))
    out.update(cap)
    out["reserved_mw_hours"] = float(r.sum())
    out["_reserves"] = r.copy()                     # hours x PRODUCTS, kept for the activation variant
    return out


def _solve(task):
    day, kind, mode, battery, rte, forecast = task
    from bess_stack.optimizer import STRATEGIES, optimize_day
    params = battery.params(rte)
    prices, cap = (day.prices, day.reserve_prices) if mode == "perfect" else forecast
    res = optimize_day(prices, day.hour_of, cap, params, STRATEGIES["arbitrage" if kind == "da" else "stacked"])
    return settle(day, res, battery)


def run_strategy(days: list[DayData], kind: str, mode: str, battery: Battery, first_day: date, last_day: date,
                 rte_by_month: dict[str, float] | None = None, workers: int = 1,
                 lookback: int = LOOKBACK_DAYS) -> pd.DataFrame:
    """Plan and settle ``kind`` (``da`` or ``stack``) for every day of the period; one row per business date.

    ``mode`` is ``perfect`` or ``asof``; ``rte_by_month`` (YYYY-MM -> round-trip efficiency) replaces the
    battery's efficiency in those months. Days without a full lookback are skipped in every mode, so all
    strategies are evaluated on the same days."""
    if kind not in ("da", "stack") or mode not in ("perfect", "asof"):
        raise ValueError(f"unknown strategy {kind}/{mode}")
    tasks = []
    for i, day in enumerate(days):
        if not first_day <= day.business_date <= last_day:
            continue
        fc = plan_inputs(days, i, lookback)
        if fc is None:
            continue
        rte = None if not rte_by_month else rte_by_month.get(f"{day.business_date:%Y-%m}")
        tasks.append((day, kind, mode, battery, rte, fc))
    if not tasks:
        raise ValueError("no day can be planned in the requested period")
    if workers > 1:
        with ProcessPoolExecutor(workers) as pool:
            rows = list(pool.map(_solve, tasks, chunksize=8))
    else:
        rows = [_solve(t) for t in tasks]
    reserves = {r["business_date"]: r.pop("_reserves") for r in rows}
    daily = pd.DataFrame(rows).set_index("business_date").sort_index()
    daily.attrs["reserves"] = reserves
    log.info("%s/%s: %d days, margin %.0f PLN", kind, mode, len(daily), margin(daily).sum())
    return daily


def margin(daily: pd.DataFrame) -> pd.Series:
    """Gross margin per day: revenues net of energy purchases and the degradation cost (the net margin of aFRR
    activation, when a run has it, counts as revenue)."""
    cols = [c for c in (*REVENUE_COLUMNS, "afrr_energy") if c in daily]
    return daily[cols].sum(axis=1) - daily["degradation"]
