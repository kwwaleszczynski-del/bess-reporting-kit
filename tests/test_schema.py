import pandas as pd
import pytest

from bess_report import schema


def test_site_loads(site):
    assert site.battery.power_mw == 1.0 and site.first_day < site.last_day
    assert set(site.opex_pln_per_mw_year) <= set(schema.FIXED_COST_LINES)


@pytest.mark.parametrize("raw,msg", [
    ({"period": {"start": "2025-01-01", "end": "2025-12-31"}, "bogus": 1}, "unknown keys"),
    ({"period": {"start": "2025-01-01"}}, "period.start and period.end"),
    ({"period": {"start": "2025-12-31", "end": "2025-01-01"}}, "after"),
    ({"period": {"start": "2025-01-01", "end": "2025-12-31"}, "opex_pln_per_mw_year": {"rent": 1}}, "opex lines"),
])
def test_site_errors(raw, msg):
    with pytest.raises(ValueError, match=msg):
        schema.site_from_dict(raw)


def test_money_validation():
    ok = pd.DataFrame({"month": ["2026-01", "2026-01"], "line": ["da_sales", "da_sales"], "value_pln": [1.0, 2.0]})
    out = schema.validate_money(ok)
    assert len(out) == 1 and out["value_pln"].iloc[0] == 3.0          # duplicates are summed
    for bad, msg in ((ok.assign(line="nonsense"), "unknown lines"), (ok.assign(month="2026/01"), "YYYY-MM"),
                     (ok.drop(columns="value_pln"), "missing columns"), (ok.assign(value_pln=None), "empty value_pln")):
        with pytest.raises(ValueError, match=msg):
            schema.validate_money(bad)


def test_read_money_roundtrip(tmp_path):
    df = pd.DataFrame({"month": ["2026-01"], "line": ["om"], "value_pln": [5.0]})
    df.to_csv(tmp_path / "s.csv", index=False)
    assert schema.read_money(tmp_path / "s.csv")["value_pln"].iloc[0] == 5.0
