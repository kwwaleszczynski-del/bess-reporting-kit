from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from bess_report import data, schema
from bess_report.strategies import build_days

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def site():
    return schema.load_site(ROOT / "config" / "site.example.yaml")


@pytest.fixture(scope="session")
def days():
    prices, capacity = data.load_slice(ROOT / "data" / "example")
    return build_days(prices, capacity)


@pytest.fixture(scope="session")
def short_site(site):
    """The example site over one week, for fast runs of the optimiser."""
    from dataclasses import replace
    return replace(site, first_day=date(2025, 10, 8), last_day=date(2025, 10, 14))
