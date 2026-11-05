from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bess_report import technical as T
from bess_report.nemslice import load_slice

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def nem(site):
    return T.from_nem(load_slice(ROOT / "data/example/nem"), "RANGEB1", site.guarantees)


def test_nem_report_layout(nem):
    m = nem.monthly
    assert len(m) == 12 and m.index[0] == "2025-10" and m.index[-1] == "2026-09"
    assert set(T.STANDARD) <= set(m.columns)
    assert m["availability"].between(0, 1).all() and m["rte"].between(0.5, 1).all()
    assert (m["availability"] >= m["availability_offered"]).all()        # declared physical >= offered
    assert nem.summary["mw"] == 200 and nem.summary["mwh"] == 400
    assert nem.compliance.dtypes.map(str).eq("boolean").all()


def test_compliance_follows_the_guarantees(site):
    m = pd.DataFrame({"availability": [0.99, 0.90, np.nan], "rte": [0.9, 0.8, 0.9], "efc": [20.0, 40.0, 20.0]},
                     index=["2026-01", "2026-02", "2026-03"])
    c = T._compliance(m, {"availability": 0.97, "rte": 0.85, "efc_per_year": 365})
    assert c["availability_ok"].tolist()[:2] == [True, False] and pd.isna(c["availability_ok"].iloc[2])
    assert c["rte_ok"].tolist() == [True, False, True]
    assert c["cycles_ok"].tolist() == [True, False, True]         # 40 EFC in 28 days = 521 a year


def test_soh_projection_is_monotonic(nem):
    soh = nem.soh
    assert soh["soh"].is_monotonic_decreasing and (soh[["calendar_loss", "cycle_loss"]] > 0).all().all()
    assert soh["soh"].iloc[0] == pytest.approx(1 - soh["calendar_loss"].iloc[0] - soh["cycle_loss"].iloc[0])
    assert 0.9 < nem.summary["soh_year1"] < 1.0


def test_incomplete_slice_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError, match="incomplete"):
        load_slice(tmp_path)


@pytest.fixture(scope="module")
def ems():
    import tempfile
    from bess_report.example import ems_demo
    with tempfile.TemporaryDirectory() as tmp:
        return T.from_ems(ems_demo(Path(tmp)))


def test_ems_report_finds_the_known_faults(ems):
    s = ems.summary
    assert s["violations"] > 0                                    # the synthetic battery has injected violations
    assert 0.9 < s["availability"] <= 1 and 0.8 < s["rte"] < 0.95
    assert s["aux_share_of_import"] > 0
    assert ems.compliance["availability_ok"].notna().any()
    assert ems.extras["result"]["aux"] is not None
