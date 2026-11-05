"""The three reports as HTML pages and Excel workbooks, built from the results of ``technical``, ``scenario`` and
``financial``. Every number on a page comes from those tables.

Usage:
    paths = technical_report(rep, guarantees, Path("docs/report"), "nem")
    paths = financial_report(sim, site, Path("docs/report"))
    paths = strategy_report(table, monthly, site, Path("docs/report"))
Each saves its charts as PNG files in ``img/`` next to the page and returns
{"html": ..., "xlsx": ..., "images": {name: Path}}.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from bess_report import figures as F
from bess_report.financial import revenue_mix, variance
from bess_report.render import fmt, img, note, page, section, table_html, write_excel
from bess_report.schema import LINES, REVENUE_LINES
from bess_report.technical import TechnicalReport

def save_figures(figs: dict, out_dir: Path, prefix: str) -> dict:
    """Write every chart to ``out_dir/img/<prefix>_<name>.png``; returns name -> path."""
    return {n: F.save(f, out_dir / "img" / f"{prefix}_{n}.png") for n, f in figs.items()}


def ref(images: dict, name: str) -> str:
    return f"img/{images[name].name}"


FOOTER = "bess-reporting-kit. Working material, not an official statement; illustrative terms are marked."
TECH_COLUMNS = {"availability": "Availability", "availability_offered": "Offered availability", "rte": "RTE",
                "rte_excl_aux": "RTE excl. aux", "e_in_mwh": "Charged, MWh", "e_out_mwh": "Discharged, MWh",
                "aux_mwh": "Auxiliary, MWh", "efc": "Cycles (EFC)", "mean_soc": "Mean SoC",
                "usable_energy_mwh": "Usable energy, MWh", "technical_outage_hours": "Outage, h", "violations": "Violations"}
TECH_KINDS = {"availability": "pct", "availability_offered": "pct", "rte": "pct", "rte_excl_aux": "pct",
              "e_in_mwh": "int", "e_out_mwh": "int", "aux_mwh": "int", "efc": "num1", "mean_soc": "pct",
              "usable_energy_mwh": "num1", "technical_outage_hours": "num1", "violations": "int"}


def kpi_table(rep: TechnicalReport, guarantees: dict) -> pd.DataFrame:
    """Period KPIs against what they are assessed against; ``ok`` is empty when there is nothing to compare."""
    s = rep.summary
    rows = []

    def add(label, value, kind, ref=None, ok=None):
        rows.append({"KPI": label, "value": value, "kind": kind, "reference": ref, "ok": ok})

    g = guarantees
    if "availability" in s:
        add("Availability, time-weighted" + (" (declared, PASA)" if rep.source == "nem" else ""), s["availability"],
            "pct", g.get("availability"), None if g.get("availability") is None else s["availability"] >= g["availability"])
    if "availability_offered" in s:
        add("Offered availability (bids, includes energy limits)", s["availability_offered"], "pct")
    add("RTE, mean of months, SoC-corrected", s["rte"], "pct", g.get("rte"),
        None if g.get("rte") is None else s["rte"] >= g["rte"])
    add("Cycles per year (EFC)", s["efc_per_year"], "num1", g.get("efc_per_year"),
        None if g.get("efc_per_year") is None else s["efc_per_year"] <= g["efc_per_year"])
    add("Mean state of charge", s["mean_soc"], "pct")
    if "technical_outage_hours_per_year" in s:
        add("Technical outage, hours per year", s["technical_outage_hours_per_year"], "num1")
    for k, label in (("availability_ok", "Months meeting the availability guarantee"),
                     ("rte_ok", "Months meeting the RTE guarantee"), ("cycles_ok", "Months within the cycle limit")):
        if f"{k}_assessed" in s:
            add(label, f"{s[f'{k}_months']} of {s[f'{k}_assessed']}", "text")
    if "usable_energy_trend_pct_per_year" in s:
        add("Trend of usable energy window, % per year (market data)", s["usable_energy_trend_pct_per_year"], "num2")
    if "soh_year1" in s:
        add("Modelled state of health after 1 year", s["soh_year1"], "pct")
        add("Modelled state of health after 10 years", s["soh_year10"], "pct")
    if "violations" in s:
        add("Warranty violations in the period", s["violations"], "int", 0, s["violations"] == 0)
    return pd.DataFrame(rows)


def _kpi_html(k: pd.DataFrame) -> str:
    rows = []
    for r in k.itertuples():
        ref = "" if r.reference is None or pd.isna(r.reference) else fmt(r.reference, r.kind if r.kind != "text" else "num1")
        status = "" if r.ok is None or pd.isna(r.ok) else f"<td class=\"{'ok' if r.ok else 'bad'}\">{'ok' if r.ok else 'not met'}</td>"
        rows.append(f"<tr><td>{r.KPI}</td><td>{fmt(r.value, r.kind)}</td><td>{ref}</td>{status or '<td></td>'}</tr>")
    return ("<div class=\"scroll\"><table><thead><tr><th>KPI</th><th>Value</th><th>Guarantee or limit</th><th>Status</th>"
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>")


def technical_report(rep: TechnicalReport, guarantees: dict | None, out_dir: Path, tag: str) -> dict:
    guarantees = guarantees or rep.guarantees
    figs = {"availability": F.availability_chart(rep.monthly, guarantees.get("availability")),
            "rte": F.rte_chart(rep.monthly, guarantees.get("rte"))}
    if rep.soh is not None and "calendar_loss" in rep.soh:
        figs["soh"] = F.soh_chart(rep.soh)
    res = rep.extras.get("result")
    aux_bins = None if res is None else (res.get("aux") or {}).get("bins")
    if aux_bins is not None and len(aux_bins):
        figs["aux"] = F.aux_chart(aux_bins.iloc[:, [0]] if isinstance(aux_bins, pd.DataFrame) else aux_bins)
    kpis = kpi_table(rep, guarantees)
    images = save_figures(figs, out_dir, f"technical-{tag}")
    monthly = rep.monthly[[c for c in TECH_COLUMNS if rep.monthly[c].notna().any()]].rename_axis("Month")
    sections = [section("Key figures", _kpi_html(kpis))]
    sections += [section("Availability", img(ref(images, "availability"), "availability by month")),
                 section("Round-trip efficiency", img(ref(images, "rte"), "round-trip efficiency by month")),
                 section("Monthly table", table_html(monthly, {c: TECH_KINDS[c] for c in monthly},
                                                     headers=TECH_COLUMNS))]
    comp = rep.compliance.copy().rename_axis("Month")
    if len(comp.columns):
        sections.append(section("Compliance by month", table_html(comp, status_cols=tuple(comp.columns))))
    if "soh" in figs:
        sections.append(section("State of health", img(ref(images, "soh"), "modelled capacity loss") + table_html(
            rep.soh, {"calendar_loss": "pct2", "cycle_loss": "pct2", "soh": "pct"}, headers={
                "calendar_loss": "Calendar loss", "cycle_loss": "Cycle loss", "soh": "State of health"})))
    if "aux" in figs:
        sections.append(section("Auxiliary load and thermal behaviour", img(ref(images, "aux"), "auxiliary load")))
    sheets = {"KPIs": kpis.drop(columns=["kind"]), "Monthly": rep.monthly, "Compliance": comp}
    if rep.soh is not None:
        sheets["State of health"] = rep.soh
    if res is not None:
        from bess_ops.report import ld_table, violation_table
        month = rep.monthly.index[-1]
        sections.append(section("Warranty violations (all)", table_html(
            violation_table(res, month) if len(res["violations"]) else pd.DataFrame({"none": []}), index=False)))
        sheets["Violations"] = res["violations"].astype(str)
        sheets["LTSA damages"] = res["ld"].drop(columns=[], errors="ignore")
    for n in rep.notes:
        sections.append(note(n))
    title = f"Technical report: {rep.name}"
    sub = "Source: AEMO public data (NEM)" if rep.source == "nem" else "Source: EMS or SCADA long table"
    html = page(title, sub, sections, footer=FOOTER)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"technical-{tag}.html").write_text(html, encoding="utf-8")
    xlsx = write_excel(out_dir / f"technical-{tag}.xlsx", sheets,
                       {"Monthly": {"availability": "0.0%", "availability_offered": "0.0%", "rte": "0.0%",
                                    "rte_excl_aux": "0.0%", "mean_soc": "0.0%"}},
                       notes=rep.notes, status={"Compliance": tuple(comp.columns)})
    return {"html": out_dir / f"technical-{tag}.html", "xlsx": xlsx, "images": images, "kpis": kpis}


def financial_report(sim: dict, site, out_dir: Path, tag: str = "example") -> dict:
    sa, sb = sim["statement"], sim["budget_statement"]
    var = variance(sa, sb)
    var.index = pd.Index([LINES.get(i, i.replace("_", " ").capitalize()) for i in var.index], name="Line")
    mix = revenue_mix(sa)
    mix.index = pd.Index([LINES[i] for i in mix.index], name="Revenue line")
    bridge = sim["bridge"].frame()
    figs = {"revenue_mix": F.revenue_mix_chart(sa, REVENUE_LINES), "bridge": F.bridge_chart(bridge)}
    images = save_figures(figs, out_dir, f"financial-{tag}")
    a = sim["assumptions"]
    sections = [
        note("Simulated statement: the revenue stack planned as-of on published PSE prices, scaled by the monthly "
             "availability and run at the monthly efficiency of the technical report. No settlement data of a real plant."),
        section("Budget to actual margin", img(ref(images, "bridge"), "budget to actual margin") + table_html(
            bridge.set_index("label").rename_axis("Step"), {"value_pln": "pln"}, headers={"value_pln": "PLN", "kind": "Type"})),
        section("Revenue by source", img(ref(images, "revenue_mix"), "revenue by source and month") + table_html(
            mix, {"revenue_pln": "pln", "share": "pct"}, headers={"revenue_pln": "PLN", "share": "Share"})),
        section("Budget variance by line", table_html(
            var, {"actual": "pln", "budget": "pln", "difference": "pln", "difference_pct": "pct"},
            headers={"difference_pct": "Difference, %"})),
        section("Monthly statement, PLN", table_html(
            sa[[c for c in sa.columns if c in ("revenue", "variable_costs", "gross_margin", "fixed_costs", "margin")]].rename_axis("Month"),
            {c: "pln" for c in sa.columns})),
        note(f"Budget rule: {a['budget_rule']}. Budgeted availability {fmt(a['budget_availability'], 'pct')}, nameplate "
             f"RTE {fmt(a['nameplate_rte'], 'pct')}; measured RTE (mean) {fmt(a['measured_rte_mean'], 'pct')}, measured "
             f"availability (mean) {fmt(a['measured_availability_mean'], 'pct')}. Fixed costs are placeholders of the site file."),
    ]
    html = page(f"Financial report: {site.name}", f"{site.first_day} to {site.last_day}", sections, footer=FOOTER)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"financial-{tag}.html").write_text(html, encoding="utf-8")
    xlsx = write_excel(out_dir / f"financial-{tag}.xlsx",
                       {"Variance": var, "Statement": sa, "Budget": sb, "Bridge": bridge, "Revenue mix": mix,
                        "Settlement": sim["settlement"], "Budget table": sim["budget"]},
                       {"Variance": {"actual": "#,##0", "budget": "#,##0", "difference": "#,##0",
                                     "difference_pct": "0.0%"}, "Bridge": {"value_pln": "#,##0"},
                        "Revenue mix": {"revenue_pln": "#,##0", "share": "0.0%"}},
                       notes=["Simulated; see the budget rule on the HTML page."])
    return {"html": out_dir / f"financial-{tag}.html", "xlsx": xlsx, "images": images, "variance": var, "mix": mix,
            "bridge": bridge}


def strategy_report(table: pd.DataFrame, monthly: pd.DataFrame, site, out_dir: Path, tag: str = "example") -> dict:
    figs = {"strategies": F.strategy_chart(table), "monthly": F.strategy_monthly_chart(
        monthly.rename(columns=table["short"].to_dict()))}
    images = save_figures(figs, out_dir, f"strategies-{tag}")
    show = table[["short", "information", "market_risk", "pln_per_mw_year", "share_of_ceiling", "month_mean_pln_per_mw",
                  "month_std_pln_per_mw", "month_worst_pln_per_mw", "months_below_half_of_mean", "cycles_per_day"]]
    cm = table.attrs.get("capacity_market", [])
    cm_text = "; ".join(f"delivery {t['auction']}: {t['closing_price_pln_kw_year']:.2f} PLN/kW/year x KWD "
                        f"{t['kwd']:.4f}" for t in cm)
    sections = [
        note(f"Evaluation at an assumed availability of {fmt(table.attrs['availability'], 'pct')} for every strategy, "
             f"{table.attrs['days']} delivery days, gross margin = revenue - purchases - degradation allowance, before fixed costs."),
        section("Gross margin per MW and year", img(ref(images, "strategies"), "strategies on one evaluation")),
        section("Table", table_html(show.set_index("short").rename_axis("Strategy"), {
            "pln_per_mw_year": "pln", "share_of_ceiling": "pct", "month_mean_pln_per_mw": "pln",
            "month_std_pln_per_mw": "pln", "month_worst_pln_per_mw": "pln", "months_below_half_of_mean": "int",
            "cycles_per_day": "num2"}, headers={
                "information": "Information set", "market_risk": "Market risk", "pln_per_mw_year": "PLN/MW/year",
                "share_of_ceiling": "Share of ceiling", "month_mean_pln_per_mw": "Month mean",
                "month_std_pln_per_mw": "Month st. dev.", "month_worst_pln_per_mw": "Worst month",
                "months_below_half_of_mean": "Months < half mean", "cycles_per_day": "Cycles/day"})),
        section("Month by month", img(ref(images, "monthly"), "monthly margin by strategy")),
        note("Capacity market terms (to verify against the current regulations): " + cm_text if cm else "No capacity market terms."),
        note("Balancing capacity is assumed accepted in full at the clearing price (price taker): true for one MW, not for "
             "a fleet. Activation energy and the stress-period obligation of the capacity market are not modelled. "
             "The toll is a placeholder input of the site file."),
    ]
    html = page(f"Strategy comparison: {site.name}", f"{table.attrs['first_day']} to {table.attrs['last_day']}",
                sections, footer=FOOTER)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"strategies-{tag}.html").write_text(html, encoding="utf-8")
    xlsx = write_excel(out_dir / f"strategies-{tag}.xlsx", {"Comparison": show, "Monthly": monthly},
                       {"Comparison": {"pln_per_mw_year": "#,##0", "share_of_ceiling": "0.0%",
                                       "month_mean_pln_per_mw": "#,##0", "month_std_pln_per_mw": "#,##0",
                                       "month_worst_pln_per_mw": "#,##0"}},
                       notes=["Gross margin per MW; see the HTML page for the information sets."])
    return {"html": out_dir / f"strategies-{tag}.html", "xlsx": xlsx, "images": images}
