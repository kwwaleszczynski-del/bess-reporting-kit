"""Common input schema of the kit: one YAML file for the site and three small tables for the money.

Site file (YAML), see ``config/site.example.yaml``: battery, reporting period, guarantees to report against,
fixed cost assumptions and contract terms. Money tables (CSV or Parquet), one row per month and line:

    settlement   month (YYYY-MM), line, value_pln [, volume_mwh]     actual revenues and costs
    budget       month, line, value_pln                              the same lines, planned

Revenue lines are income, cost lines are money paid; ``da_purchases`` is the cost of the energy bought on the
day-ahead market. The technical report reads either a long EMS/SCADA table (``bess_ops``: timestamp, device_id,
signal, value, with its YAML mapping) or the public AEMO tables of the NEM (``bess_ops.nem``).

Usage:
    cfg = load_site("config/site.example.yaml")
    actual = read_money("settlement.csv")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from bess_report.strategies import Battery

REVENUE_LINES = {
    "da_sales": "Day-ahead market sales",
    "fcr_capacity": "FCR capacity",
    "afrr_capacity": "aFRR capacity",
    "mfrrd_capacity": "mFRRd capacity",
    "rr_capacity": "RR capacity",
    "afrr_energy": "aFRR activation energy",
    "imbalance": "Imbalance settlement",
    "capacity_market": "Capacity market",
    "toll": "Tolling payment",
    "other_revenue": "Other revenue",
}
VARIABLE_COST_LINES = {
    "da_purchases": "Day-ahead market purchases",
    "aux_energy": "Auxiliary energy",
    "degradation": "Degradation allowance",
}
FIXED_COST_LINES = {
    "om": "Operation and maintenance",
    "insurance": "Insurance",
    "grid_fees": "Grid fees",
    "land_and_other": "Land and other fixed costs",
    "other_cost": "Other costs",
}
LINES = {**REVENUE_LINES, **VARIABLE_COST_LINES, **FIXED_COST_LINES}


@dataclass
class Site:
    name: str
    battery: Battery
    first_day: date
    last_day: date
    guarantees: dict = field(default_factory=dict)
    opex_pln_per_mw_year: dict = field(default_factory=dict)
    toll: dict = field(default_factory=dict)
    capacity_market: dict = field(default_factory=dict)
    budget: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


def _date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def site_from_dict(raw: dict) -> Site:
    known = {"name", "battery", "period", "guarantees", "opex_pln_per_mw_year", "toll", "capacity_market", "budget"}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"unknown keys in the site file: {sorted(unknown)}")
    bat = Battery(**(raw.get("battery") or {}))
    period = raw.get("period") or {}
    if "start" not in period or "end" not in period:
        raise ValueError("period.start and period.end are required")
    opex = raw.get("opex_pln_per_mw_year") or {}
    bad = set(opex) - set(FIXED_COST_LINES)
    if bad:
        raise ValueError(f"opex lines must be among {sorted(FIXED_COST_LINES)}, got {sorted(bad)}")
    site = Site(raw.get("name", "BESS"), bat, _date(period["start"]), _date(period["end"]),
                raw.get("guarantees") or {}, opex, raw.get("toll") or {}, raw.get("capacity_market") or {},
                raw.get("budget") or {}, raw)
    if site.first_day > site.last_day:
        raise ValueError("period.start is after period.end")
    return site


def load_site(path: str | Path) -> Site:
    return site_from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def validate_money(df: pd.DataFrame, name: str = "table") -> pd.DataFrame:
    """Check columns, month labels, line names and numbers; returns month, line, value_pln [, volume_mwh]."""
    missing = {"month", "line", "value_pln"} - set(df.columns)
    if missing:
        raise ValueError(f"{name}: missing columns {sorted(missing)}")
    out = df.copy()
    out["month"] = out["month"].astype(str)
    if not out["month"].str.fullmatch(r"\d{4}-\d{2}").all():
        raise ValueError(f"{name}: month must be YYYY-MM")
    unknown = sorted(set(out["line"]) - set(LINES))
    if unknown:
        raise ValueError(f"{name}: unknown lines {unknown}; known lines: {sorted(LINES)}")
    out["value_pln"] = pd.to_numeric(out["value_pln"], errors="raise")
    if out["value_pln"].isna().any():
        raise ValueError(f"{name}: empty value_pln")
    if out.duplicated(["month", "line"]).any():
        out = out.groupby(["month", "line"], as_index=False).agg(
            {c: "sum" for c in out.columns if c not in ("month", "line")})
    return out


def read_money(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    return validate_money(df, path.name)
