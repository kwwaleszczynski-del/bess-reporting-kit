"""PSE inputs of the strategy comparison: day-ahead prices and balancing capacity prices, read with pse-opendata.

Series (business dates in Europe/Warsaw; units from the PSE report pages and the API field map):

    csdac-pln    SDAC day-ahead clearing price of the Polish zone, PLN/MWh, 15 min
    cmbp-tp      prices of balancing capacity bought in the basic (day-ahead) procurement, PLN/MW per hour, hourly
                 (fcr_g/fcr_d FCR up/down, afrr_g/afrr_d aFRR, mfrrd_g/mfrrd_d mFRRd, rr_g RR up)

A small slice of both series is committed in ``data/example``; ``fetch`` rebuilds it from the PSE reports API
(no key needed) or from the pse-opendata cache.

Usage:
    prices, capacity = fetch(date(2024, 9, 23), date(2026, 9, 30), Path("data/cache"))
    prices, capacity = load_slice(Path("data/example"))
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd
import pse_opendata as pse

log = logging.getLogger(__name__)
PRODUCTS = ["fcr_up", "fcr_down", "afrr_up", "afrr_down", "mfrr_up", "mfrr_down", "rr_up"]
UP = [p for p in PRODUCTS if p.endswith("_up")]
DOWN = [p for p in PRODUCTS if p.endswith("_down")]
FIELDS = {"fcr_g": "fcr_up", "fcr_d": "fcr_down", "afrr_g": "afrr_up", "afrr_d": "afrr_down",
          "mfrrd_g": "mfrr_up", "mfrrd_d": "mfrr_down", "rr_g": "rr_up"}
PRICE_FILE, CAPACITY_FILE = "pse_prices.parquet", "pse_capacity.parquet"


def fetch(start: date, end: date, cache_dir: Path, offline: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Quarter-hour day-ahead prices (column ``price``) and hourly capacity prices (``PRODUCTS``), indexed by the
    interval start in UTC, both with the ``business_date``."""
    client = pse.Client(cache_dir=cache_dir, offline=offline)
    raw = client.get("csdac-pln", start, end, fields=["csdac_pln"])
    prices = raw.set_index("start_utc")[["csdac_pln", "business_date"]].rename(columns={"csdac_pln": "price"})
    prices = prices.dropna(subset=["price"])
    raw = client.get("cmbp-tp", start, end, fields=list(FIELDS))
    cap = raw.set_index("start_utc")[[*FIELDS, "business_date"]].rename(columns=FIELDS)
    cap = cap.dropna(subset=PRODUCTS, how="all")
    for name, df in (("prices", prices), ("capacity", cap)):
        df.index.name = "ts_utc"
        log.info("%s: %d rows, %s .. %s", name, len(df), df["business_date"].min(), df["business_date"].max())
    return prices[~prices.index.duplicated(keep="last")], cap[~cap.index.duplicated(keep="last")]


def save_slice(prices: pd.DataFrame, capacity: pd.DataFrame, path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    prices.to_parquet(path / PRICE_FILE, compression="zstd")
    capacity.to_parquet(path / CAPACITY_FILE, compression="zstd")


def load_slice(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    path = Path(path)
    for f in (PRICE_FILE, CAPACITY_FILE):
        if not (path / f).exists():
            raise FileNotFoundError(f"{path / f} missing; build it with: python -m bess_report fetch-pse")
    return pd.read_parquet(path / PRICE_FILE), pd.read_parquet(path / CAPACITY_FILE)
