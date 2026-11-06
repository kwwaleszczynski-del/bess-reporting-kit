import numpy as np
import pandas as pd
import pytest

from bess_report import nem_trading as NT


def synthetic(days=12, flat_battery=True):
    idx = pd.date_range("2026-01-01", periods=days * 288, freq="5min", tz="Australia/Brisbane")
    hour = (np.arange(len(idx)) % 288) / 12.0
    rrp = 50 + 60 * np.sin((hour - 6) / 24 * 2 * np.pi) + (np.arange(len(idx)) // 288) % 3 * 5
    site = pd.DataFrame({"p_meter": np.zeros(len(idx))}, index=idx.tz_convert("UTC"))
    return site, pd.Series(rrp, index=idx.tz_localize(None))


def test_idle_battery_earns_nothing_and_the_bridge_adds_up():
    site, prices = synthetic()
    r = NT.run(site, prices, 0.85, 10.0, 20.0)
    s = r["summary"]
    assert s["actual"] == 0.0 and s["perfect"] > s["asof"] > 0
    r["bridge"].check()
    assert r["bridge"].end == pytest.approx(s["actual"]) and r["bridge"].start == pytest.approx(s["perfect"])
    assert s["days"] == 12 - NT.LOOKBACK


def test_metered_power_is_priced_at_the_interval_price():
    site, prices = synthetic()
    site["p_meter"] = np.where(np.arange(len(site)) % 288 < 144, 5.0, -5.0)       # export, then import, every day
    r = NT.run(site, prices, 0.85, 10.0, 20.0)
    d = r["daily"].iloc[0]
    first = list(prices.index.normalize().unique()).index(d.name)            # the first day with a full lookback
    day = prices.iloc[first * 288:(first + 1) * 288].to_numpy()
    assert d["export"] == pytest.approx(5.0 * NT.DT_H * day[:144].sum(), rel=1e-9)
    assert d["import"] == pytest.approx(5.0 * NT.DT_H * day[144:].sum(), rel=1e-9)
    assert d["actual"] == pytest.approx(d["export"] - d["import"])


def test_committed_results_are_consistent():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    s = json.loads((root / "results/summary.json").read_text(encoding="utf-8"))["nem_trading"]
    m = pd.read_csv(root / "results/nem_trading_monthly.csv", index_col="month")
    assert m["actual"].sum() == pytest.approx(s["actual"]) and m["days"].sum() == s["days"]
    assert s["perfect"] >= s["asof"] and s["end"] == pytest.approx(s["actual"])
    assert s["bridge"]["step0"]["value"] + s["bridge"]["step1"]["value"] == pytest.approx(s["end"] - s["start"])
