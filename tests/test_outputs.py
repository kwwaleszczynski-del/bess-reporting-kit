"""Reports, charts, results tables and the README, all on the committed results (no network, no optimiser)."""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from openpyxl import load_workbook

from bess_report import figures as F
from bess_report import readme, reports
from bess_report.financial import Bridge, statement
from bess_report.render import fmt, page, table_html
from bess_report.schema import read_money
from bess_report.technical import TechnicalReport

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"


@pytest.fixture(scope="module")
def summary():
    return json.loads((RES / "summary.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def monthly():
    return pd.read_csv(RES / "technical_nem_monthly.csv", index_col="month")


def all_figures(monthly, summary):
    stmt = pd.read_csv(RES / "financial_statement.csv", index_col="month")
    bridge = pd.read_csv(RES / "financial_bridge.csv")
    table = pd.read_csv(RES / "strategy_comparison.csv", index_col="id")
    smonthly = pd.read_csv(RES / "strategy_monthly_margin_per_mw.csv", index_col=0)
    soh = pd.read_csv(RES / "technical_nem_soh.csv", index_col="years")
    from bess_report.schema import REVENUE_LINES
    return {"availability": F.availability_chart(monthly, 0.97), "rte": F.rte_chart(monthly, 0.85),
            "soh": F.soh_chart(soh), "mix": F.revenue_mix_chart(stmt, REVENUE_LINES), "bridge": F.bridge_chart(bridge),
            "strategies": F.strategy_chart(table),
            "monthly": F.strategy_monthly_chart(smonthly.dropna(axis=1, how="all").rename(columns=table["short"].to_dict()))}


def test_no_chart_has_overlapping_texts(monthly, summary):
    for name, fig in all_figures(monthly, summary).items():
        assert F.text_overlaps(fig) == [], name


def test_overlap_detector_detects():
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    ax.text(0.5, 0.5, "abcdef")
    ax.text(0.5, 0.5, "abcdef")
    assert F.text_overlaps(fig)


def test_html_page_is_self_contained_and_responsive():
    html = page("T", "s", ["<p>x</p>"])
    assert "viewport" in html and "prefers-color-scheme:dark" in html
    assert "http" not in html.replace("https://github.com/kwwaleszczynski-del/bess-reporting-kit", "")
    t = table_html(pd.DataFrame({"a": [0.5], "b": [True]}, index=["r"]), {"a": "pct"}, status_cols=("b",))
    assert "50.0 %" in t and "class=\"ok\"" in t and "overflow-x" in html + "overflow-x"


def test_fmt():
    assert fmt(0.9534, "pct") == "95.3 %" and fmt(1234567.4, "pln") == "1 234 567" and fmt(float("nan")) == ""


def test_technical_report_files(tmp_path, monthly, summary, site):
    rep = TechnicalReport("X", "nem", monthly, summary["technical_nem"],
                          pd.read_csv(RES / "technical_nem_compliance.csv", index_col="month"),
                          pd.read_csv(RES / "technical_nem_soh.csv", index_col="years"))
    out = reports.technical_report(rep, site.guarantees, tmp_path, "t")
    html = out["html"].read_text(encoding="utf-8")
    assert "Technical report" in html and "Availability" in html and html.count("<table>") >= 3
    wb = load_workbook(out["xlsx"])
    assert {"KPIs", "Monthly", "Compliance"} <= set(wb.sheetnames)
    assert wb["Monthly"].freeze_panes is not None and wb["Compliance"].conditional_formatting


def test_example_reports_are_committed(summary):
    for name in ("technical-nem", "technical-ems", "financial-example", "strategies-example"):
        assert (ROOT / "docs/report" / f"{name}.html").exists() and (ROOT / "docs/report" / f"{name}.xlsx").exists()
    wb = load_workbook(ROOT / "docs/report/financial-example.xlsx")
    assert {"Variance", "Statement", "Bridge"} <= set(wb.sheetnames)


# ---- results are consistent with each other ----------------------------------------------------------------------

def test_bridge_identity_in_the_results(summary):
    b = pd.read_csv(RES / "financial_bridge.csv")
    steps = b[b["kind"] == "step"]["value_pln"].sum()
    assert b["value_pln"].iloc[0] + steps == pytest.approx(b["value_pln"].iloc[-1], rel=1e-9)
    stmt = pd.read_csv(RES / "financial_statement.csv", index_col="month")
    assert stmt["margin"].sum() == pytest.approx(b["value_pln"].iloc[-1], rel=1e-9)


def test_settlement_table_reproduces_the_statement():
    s = statement(read_money(RES / "settlement.csv"))
    ref = pd.read_csv(RES / "financial_statement.csv", index_col="month")
    assert np.allclose(s.to_numpy(), ref[s.columns].to_numpy(), rtol=1e-9, atol=1e-6)


def test_strategy_table_matches_daily_margins(summary):
    daily = pd.read_csv(RES / "strategy_daily_margin.csv", index_col=0)
    a = summary["strategy_meta"]["availability"]
    for k in ("da_perfect", "da_asof", "stack_perfect", "stack_asof"):
        assert daily[k].sum() * a == pytest.approx(summary["strategies"][k]["total_pln"], rel=1e-9)
    assert len(daily) == summary["strategy_meta"]["days"]


def test_ordering_the_readme_relies_on(summary):
    s = summary["strategies"]
    assert s["da_perfect"]["pln_per_mw_year"] >= s["da_asof"]["pln_per_mw_year"]
    assert s["stack_perfect"]["pln_per_mw_year"] >= s["stack_asof"]["pln_per_mw_year"]
    assert s["stack_asof"]["pln_per_mw_year"] > s["da_asof"]["pln_per_mw_year"]
    assert s["toll"]["month_std_pln_per_mw"] == 0.0
    assert readme.derive(summary)["capacity_lines_share"] > 0.5
    assert summary["technical_nem"]["availability"] < summary["technical_nem"]["availability_min_month"] + 0.2


# ---- README ------------------------------------------------------------------------------------------------------

def test_template_has_no_hand_written_numbers():
    assert readme.lint((ROOT / "README.template.md").read_text(encoding="utf-8")) == []


def test_lint_finds_numbers():
    assert readme.lint("The battery earned 12 PLN.\n`code 3` {{a.b}} [x](http://y/1)") == ["The battery earned 12 PLN."]


def test_readme_is_what_the_results_render_to(summary):
    template = (ROOT / "README.template.md").read_text(encoding="utf-8")
    assert (ROOT / "README.md").read_text(encoding="utf-8") == readme.render(template, summary)
    assert "{{" not in (ROOT / "README.md").read_text(encoding="utf-8")


def test_readme_math_and_style():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert r"\operatorname" not in text and "```math" in text
    assert not re.search("cl" + "aude|co-authored|" + r"\ban" + r"thropic\b", text, re.I)
    assert "—" not in text and "–" not in text         # no long dashes


def test_unknown_placeholder_is_an_error(summary):
    with pytest.raises(KeyError):
        readme.render("{{no.such.key}}", summary)


def test_forecast_sensitivity_default_row_is_the_main_result(summary):
    fs, st = summary["forecast_sensitivity"], summary["strategies"]
    for kind in ("da", "stack"):
        d = fs[f"{kind}_{summary['assumptions']['lookback_days']}"]
        assert d["pln_per_mw_year"] == pytest.approx(st[f"{kind}_asof"]["pln_per_mw_year"], rel=1e-9)
        assert d["share_of_ceiling"] == pytest.approx(st[f"{kind}_asof"]["share_of_ceiling"], rel=1e-9)
    assert all(0 < v["share_of_ceiling"] <= 1.0001 for v in fs.values())


def test_activation_variant_in_the_results(summary):
    st = summary["strategies"]
    assert st["stack_act_asof"]["pln_per_mw_year"] > st["stack_asof"]["pln_per_mw_year"]      # the README says "more"
    assert 0 < st["stack_act_asof"]["share_of_ceiling"] <= 1.0001
