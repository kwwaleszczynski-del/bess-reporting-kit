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
from bess_report.render import fmt, img, note, page, section, table_html, tiles, write_excel
from bess_report.schema import LINES, REVENUE_LINES
from bess_report.technical import TechnicalReport

def save_figures(figs: dict, out_dir: Path, prefix: str) -> dict:
    """Draw every chart (``figs``: name -> function returning a figure) in the light and the dark theme into
    ``out_dir/img/<prefix>_<name>.png`` and ``..._dark.png``; returns name -> path of the light one."""
    return {n: F.save_themed(b, out_dir / "img" / f"{prefix}_{n}.png") for n, b in figs.items()}


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
    figs = {"availability": lambda: F.availability_chart(rep.monthly, guarantees.get("availability")),
            "rte": lambda: F.rte_chart(rep.monthly, guarantees.get("rte"))}
    if rep.soh is not None and "calendar_loss" in rep.soh:
        figs["soh"] = lambda: F.soh_chart(rep.soh)
    res = rep.extras.get("result")
    aux_bins = None if res is None else (res.get("aux") or {}).get("bins")
    if aux_bins is not None and len(aux_bins):
        figs["aux"] = lambda: F.aux_chart(aux_bins.iloc[:, [0]] if isinstance(aux_bins, pd.DataFrame) else aux_bins)
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
    s = rep.summary
    head = tiles([("Availability", fmt(s["availability"], "pct"), "time-weighted" + (", declared (PASA)" if rep.source == "nem" else ", LTSA formula")),
                  ("Round-trip efficiency", fmt(s["rte"], "pct"), "SoC-corrected, mean of months"),
                  ("Cycles per year", fmt(s["efc_per_year"], "num1"), "equivalent full cycles"),
                  ("State of health, 10 years", fmt(s.get("soh_year10"), "pct"), "ageing model, not a measurement")])
    html = page(title, sub, sections, footer=FOOTER, current=f"technical-{tag}.html", head_tiles=head)
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
    figs = {"revenue_mix": lambda: F.revenue_mix_chart(sa, REVENUE_LINES), "bridge": lambda: F.bridge_chart(bridge)}
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
    b = sim["bridge"]
    head = tiles([("Budget margin", fmt(b.start, "pln") + " PLN", "rule-based budget"),
                  ("Actual margin", fmt(b.end, "pln") + " PLN", "simulated year"),
                  ("Against budget", f"{(b.end / b.start - 1) * 100:+.1f} %", "market, efficiency, availability"),
                  ("Balancing capacity", fmt(mix.loc[[i for i in mix.index if "capacity" in i.lower() and "market" not in i.lower()], "share"].sum(), "pct"),
                   "of revenue; price taker of 1 MW")])
    html = page(f"Financial report: {site.name}", f"{site.first_day} to {site.last_day}", sections, footer=FOOTER,
                current=f"financial-{tag}.html", head_tiles=head)
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


def nem_trading_report(res: dict, name: str, out_dir: Path, tag: str = "nem") -> dict:
    """HTML and Excel report of ``nem_trading.run``: monthly energy margin against the two benchmarks and the bridge
    from the perfect-foresight margin to the actual one. Amounts in AUD."""
    s, monthly, bridge = res["summary"], res["monthly"], res["bridge"].frame()
    figs = {"bridge": lambda: F.bridge_chart(bridge, unit_label="thousand AUD", title="Perfect foresight to actual energy margin"),
            "monthly": lambda: F.trading_chart(monthly)}
    images = save_figures(figs, out_dir, f"trading-{tag}")
    head = tiles([("Actual energy margin", fmt(s["actual_per_mw_year"], "pln") + " AUD", "per MW and year, metered power x price"),
                  ("Against as-of benchmark", fmt(s["capture_vs_asof"], "pct"), "same battery, 7-day average forecast"),
                  ("Against perfect foresight", fmt(s["capture_vs_perfect"], "pct"), "ceiling no one can trade"),
                  ("Days compared", fmt(s["days"], "int"), f"{s['first_day']} to {s['last_day']}")])
    show = monthly[["days", "export", "import", "actual", "asof", "perfect", "capture_vs_asof", "capture_vs_perfect"]]
    sections = [
        note("Energy market only: the metered power times the regional reference price of every 5-minute interval. Frequency "
             "control (FCAS) revenue, which is usually the larger part for a grid battery, is not in this view, and neither "
             "are contracts. The gap to the as-of benchmark is everything the energy benchmark does not know, not a verdict on "
             "the operator."),
        section("Perfect foresight to actual", img(f"img/{images['bridge'].name}", "bridge") + table_html(
            bridge.set_index("label").rename_axis("Step").rename(columns={"value_pln": "value"}), {"value": "pln"},
            headers={"value": "AUD", "kind": "Type"})),
        section("By month", img(f"img/{images['monthly'].name}", "monthly energy margin") + table_html(
            show.rename_axis("Month"), {"days": "int", "export": "pln", "import": "pln", "actual": "pln", "asof": "pln",
                                        "perfect": "pln", "capture_vs_asof": "pct", "capture_vs_perfect": "pct"},
            headers={"export": "Export revenue, AUD", "import": "Import cost, AUD", "actual": "Actual margin, AUD",
                     "asof": "As-of, AUD", "perfect": "Perfect, AUD", "capture_vs_asof": "vs as-of",
                     "capture_vs_perfect": "vs perfect"})),
        note(f"Benchmark battery: {fmt(s['power_mw'], 'int')} MW / {fmt(s['energy_mwh'], 'int')} MWh, round-trip efficiency "
             f"{fmt(s['rte'], 'pct')} (measured, from the technical report), arbitrage only, no degradation cost, at most "
             "one and a half cycles a day. Only complete days with seven earlier days are compared."),
    ]
    html = page(f"Trading report: {name}", "Open AEMO data: SCADA and regional reference prices", sections, footer=FOOTER,
                current=f"trading-{tag}.html", head_tiles=head)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"trading-{tag}.html").write_text(html, encoding="utf-8", newline=chr(10))
    xlsx = write_excel(out_dir / f"trading-{tag}.xlsx", {"Monthly": monthly, "Bridge": bridge, "Daily": res["daily"]},
                       {"Monthly": {c: "#,##0" for c in ("export", "import", "actual", "asof", "perfect")}},
                       notes=["Energy only (no FCAS), AUD."])
    return {"html": out_dir / f"trading-{tag}.html", "xlsx": xlsx, "images": images}


def strategy_report(table: pd.DataFrame, monthly: pd.DataFrame, site, out_dir: Path, tag: str = "example",
                    saturation: pd.DataFrame | None = None, sensitivity: pd.DataFrame | None = None) -> dict:
    figs = {"strategies": lambda: F.strategy_chart(table), "monthly": lambda: F.strategy_monthly_chart(
        monthly.rename(columns=table["short"].to_dict()))}
    if saturation is not None:
        figs["saturation"] = lambda: F.saturation_chart(saturation)
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
        *([section("How much the forecast matters", table_html(
            sensitivity.pivot(index="lookback_days", columns="strategy", values=["pln_per_mw_year", "share_of_ceiling"])
            .set_axis([f"{k} {v}" for k, v in sensitivity.pivot(index="lookback_days", columns="strategy",
                                                                 values=["pln_per_mw_year", "share_of_ceiling"]).columns], axis=1)
            .rename_axis("Average over previous days"), {
                "pln_per_mw_year da": "pln", "pln_per_mw_year stack": "pln", "share_of_ceiling da": "pct",
                "share_of_ceiling stack": "pct"}, headers={
                "pln_per_mw_year da": "Day-ahead, PLN/MW/year", "share_of_ceiling da": "Day-ahead, share of ceiling",
                "pln_per_mw_year stack": "Stack, PLN/MW/year", "share_of_ceiling stack": "Stack, share of ceiling"}))]
           if sensitivity is not None else []),
        *([section("When the market fills up", img(ref(images, "saturation"), "stack against fleet size") + table_html(
            saturation.rename_axis("Fleet, MW"), {"perfect_pln_per_mw_year": "pln", "retention": "pct",
                                                  "stack_asof_scaled_pln_per_mw_year": "pln",
                                                  "da_asof_pln_per_mw_year": "pln", "reserve_share": "pct"},
            headers={"perfect_pln_per_mw_year": "Perfect foresight, PLN/MW/year", "retention": "Kept of lone battery",
                     "stack_asof_scaled_pln_per_mw_year": "Stack as-of, scaled", "da_asof_pln_per_mw_year": "Day-ahead as-of",
                     "reserve_share": "From reserves"})),
           note("Fleet model of pl-bess-revenue-stack (offer stacks, pro-rata acceptance, perfect foresight); the as-of "
                "stack is scaled by the share kept, which assumes the as-of plan loses the same share. Day-ahead prices "
                "are not moved by the fleet in this model.")] if saturation is not None else []),
        note("Capacity market terms (to verify against the current regulations): " + cm_text if cm else "No capacity market terms."),
        note("Balancing capacity is assumed accepted in full at the clearing price (price taker): true for one MW, not for "
             "a fleet. Activation energy and the stress-period obligation of the capacity market are not modelled. "
             "The toll is a placeholder input of the site file."),
    ]
    sc = table["share_of_ceiling"]
    head = tiles([("Stack, as-of", fmt(sc["stack_asof"], "pct"), "of its perfect-foresight ceiling"),
                  ("Day-ahead, as-of", fmt(sc["da_asof"], "pct"), "of its perfect-foresight ceiling"),
                  ("Availability assumed", fmt(table.attrs["availability"], "pct"), "same for every strategy"),
                  ("Delivery days", fmt(table.attrs["days"], "int"), "one battery, one evaluation")])
    html = page(f"Strategy comparison: {site.name}", f"{table.attrs['first_day']} to {table.attrs['last_day']}",
                sections, footer=FOOTER, current=f"strategies-{tag}.html", head_tiles=head)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"strategies-{tag}.html").write_text(html, encoding="utf-8")
    sheets = {"Comparison": show, "Monthly": monthly}
    if saturation is not None:
        sheets["Fleet size"] = saturation
    if sensitivity is not None:
        sheets["Forecast sensitivity"] = sensitivity
    xlsx = write_excel(out_dir / f"strategies-{tag}.xlsx", sheets,
                       {"Comparison": {"pln_per_mw_year": "#,##0", "share_of_ceiling": "0.0%",
                                       "month_mean_pln_per_mw": "#,##0", "month_std_pln_per_mw": "#,##0",
                                       "month_worst_pln_per_mw": "#,##0"}},
                       notes=["Gross margin per MW; see the HTML page for the information sets."])
    return {"html": out_dir / f"strategies-{tag}.html", "xlsx": xlsx, "images": images}
