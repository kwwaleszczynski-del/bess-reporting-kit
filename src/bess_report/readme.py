"""README.md from ``README.template.md`` and ``results/summary.json``: every number of the README is written by code.

Placeholders in the template:

    {{path.to.value|kind}}      a value of summary.json (or of the derived figures), kind: pct, spct, pct0, pln, kpln, mpln,
                                num1, num2, int, text
    {{table:name}}              a Markdown table built from the summary (strategies, bridge, mix, nem, ems)

``lint`` rejects a template that contains a number written by hand outside code, links and placeholders, so a figure
cannot drift away from the results. The test suite checks that README.md equals the rendering of the template.

Usage:
    python -m bess_report readme            # write README.md
    python -m bess_report readme --check    # exit 1 if README.md is not what the template renders to
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PLACEHOLDER = re.compile(r"\{\{\s*([^{}|]+?)\s*(?:\|\s*(\w+)\s*)?\}\}")
DIGIT = re.compile(r"\d")


def fmt(v, kind: str) -> str:
    if v is None:
        return "n/a"
    if kind == "pct":
        return f"{v * 100:.1f} %"
    if kind == "spct":
        return f"{v * 100:+.1f} %"
    if kind == "pct0":
        return f"{v * 100:.0f} %"
    if kind == "pln":
        return f"{v:,.0f}".replace(",", " ")
    if kind == "kpln":
        return f"{v / 1e3:,.0f}k".replace(",", " ")
    if kind == "mpln":
        return f"{v / 1e6:.2f} M"
    if kind == "num1":
        return f"{v:,.1f}".replace(",", " ")
    if kind == "num2":
        return f"{v:,.2f}"
    if kind == "int":
        return f"{v:,.0f}".replace(",", " ")
    return str(v)


def derive(s: dict) -> dict:
    """Figures that are ratios or differences of results; computed here so the template carries no numbers."""
    st, fin = s["strategies"], s["financial"]
    d = {"stack_over_da": st["stack_asof"]["pln_per_mw_year"] / st["da_asof"]["pln_per_mw_year"],
         "da_loss_to_perfect": 1 - st["da_asof"]["share_of_ceiling"],
         "stack_loss_to_perfect": 1 - st["stack_asof"]["share_of_ceiling"]}
    mix = fin["mix"]
    total = sum(v["revenue_pln"] for v in mix.values())
    cap = sum(v["revenue_pln"] for k, v in mix.items() if "capacity" in k.lower() and "market" not in k.lower())
    d["capacity_lines_share"] = cap / total
    d["bridge_change"] = fin["bridge"]["end"] - fin["bridge"]["start"]
    d["bridge_change_pct"] = d["bridge_change"] / fin["bridge"]["start"]
    d["rte_gap_pp"] = (s["assumptions"]["guarantees"]["rte"] - s["technical_nem"]["rte"]) * 100
    d["nem_outage_share"] = 1 - s["technical_nem"]["availability"]
    d["toll_vs_da"] = s["assumptions"]["toll"]["pln_per_mw_year"] / st["da_asof"]["pln_per_mw_year"]
    d["cm_best_extra"] = max(v["pln_per_mw_year"] - st["da_asof"]["pln_per_mw_year"]
                             for k, v in st.items() if k.startswith("cm_"))
    d["strategy_days"] = s["strategy_meta"]["days"]
    if "stack_act_asof" in st:
        d["act_uplift"] = st["stack_act_asof"]["pln_per_mw_year"] / st["stack_asof"]["pln_per_mw_year"] - 1
    sat = s.get("saturation")
    if sat:
        sizes = sorted(int(k) for k in sat["rows"] if int(k) > 0)
        mid, large = sizes[1], sizes[-1]
        d.update({"sat_mid_mw": mid, "sat_mid_retention": sat["rows"][str(mid)]["retention"],
                  "sat_large_mw": large, "sat_large_retention": sat["rows"][str(large)]["retention"],
                  "sat_large_stack": sat["rows"][str(large)]["stack_asof_scaled_pln_per_mw_year"],
                  "sat_large_change": sat["rows"][str(large)]["last_schedule_change_mw"]})
    return d


def lookup(s: dict, path: str):
    cur = s
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(f"{path}: no '{part}' in the summary")
        cur = cur[part]
    return cur


def _md(header: list[str], rows: list[list[str]], align: str | None = None) -> str:
    align = align or "|".join(["---"] + ["---:"] * (len(header) - 1))
    return "\n".join(["| " + " | ".join(header) + " |", "|" + align + "|"] + ["| " + " | ".join(r) + " |" for r in rows])


def table(name: str, s: dict) -> str:
    st = s["strategies"]
    if name == "strategies":
        order = ["da_perfect", "da_asof", "stack_perfect", "stack_asof", "stack_act_perfect", "stack_act_asof", "toll"] + sorted(k for k in st if k.startswith("cm_"))
        rows = [[st[k]["short"], st[k]["information"], fmt(st[k]["pln_per_mw_year"], "pln"),
                 fmt(st[k]["share_of_ceiling"], "pct0") if st[k].get("share_of_ceiling") is not None else "",
                 fmt(st[k]["month_worst_pln_per_mw"], "pln"), fmt(st[k]["month_best_pln_per_mw"], "pln")]
                for k in order if k in st]
        return _md(["Strategy", "Plan for day D may use", "PLN/MW/year", "Share of own ceiling", "Worst month, PLN/MW",
                    "Best month, PLN/MW"], rows, "---|---|---:|---:|---:|---:")
    if name == "saturation":
        rows = [[fmt(float(k), "int"), fmt(v["perfect_pln_per_mw_year"], "pln"), fmt(v["retention"], "pct0"),
                 fmt(v["stack_asof_scaled_pln_per_mw_year"], "pln"), fmt(v["da_asof_pln_per_mw_year"], "pln")]
                for k, v in s["saturation"]["rows"].items()]
        return _md(["Fleet, MW", "Perfect foresight, PLN/MW/year", "Kept of the lone battery", "Stack as-of, scaled",
                    "Day-ahead as-of"], rows, "---:|---:|---:|---:|---:")
    if name == "sensitivity":
        fs = s["forecast_sensitivity"]
        lbs = sorted({int(k.split("_")[1]) for k in fs})
        rows = [[fmt(lb, "int"), fmt(fs[f"da_{lb}"]["pln_per_mw_year"], "pln"), fmt(fs[f"da_{lb}"]["share_of_ceiling"], "pct0"),
                 fmt(fs[f"stack_{lb}"]["pln_per_mw_year"], "pln"), fmt(fs[f"stack_{lb}"]["share_of_ceiling"], "pct0")]
                for lb in lbs]
        return _md(["Average over the previous days", "Day-ahead, PLN/MW/year", "Share of ceiling", "Stack, PLN/MW/year",
                    "Share of ceiling"], rows, "---:|---:|---:|---:|---:")
    if name == "trading":
        n = s["nem_trading"]
        rows = [["Perfect foresight (ceiling)", fmt(n["start"], "pln")]]
        rows += [[v["label"], f"{v['value']:+,.0f}".replace(",", " ")] for v in n["bridge"].values()]
        rows.append(["Actual energy margin", fmt(n["end"], "pln")])
        return _md(["Step", "AUD"], rows)
    if name == "bridge":
        b = s["financial"]["bridge"]
        rows = [["Budget margin", fmt(b["start"], "pln")]]
        rows += [[v["label"], f"{v['value']:+,.0f}".replace(",", " ")] for v in b["steps"].values()]
        rows.append(["Actual margin (simulated)", fmt(b["end"], "pln")])
        return _md(["Step", "PLN"], rows)
    if name == "mix":
        rows = [[k, fmt(v["revenue_pln"], "pln"), fmt(v["share"], "pct")] for k, v in s["financial"]["mix"].items()]
        return _md(["Revenue line", "PLN", "Share"], rows)
    if name == "nem":
        t, g = s["technical_nem"], s["assumptions"]["guarantees"]
        rows = [["Availability, time-weighted (declared)", fmt(t["availability"], "pct"), fmt(g["availability"], "pct0"),
                 f"{t['availability_ok_months']} of {t['availability_ok_assessed']} months"],
                ["Offered availability (bids)", fmt(t["availability_offered"], "pct"), "", ""],
                ["RTE, mean of months, SoC-corrected", fmt(t["rte"], "pct"), fmt(g["rte"], "pct0"),
                 f"{t['rte_ok_months']} of {t['rte_ok_assessed']} months"],
                ["Cycles per year (EFC)", fmt(t["efc_per_year"], "num1"), fmt(g["efc_per_year"], "int"),
                 f"{t['cycles_ok_months']} of {t['cycles_ok_assessed']} months"],
                ["Technical outage, hours per year", fmt(t["technical_outage_hours_per_year"], "num1"), "", ""],
                ["Usable energy window trend, % per year", fmt(t["usable_energy_trend_pct_per_year"], "num2"), "", ""],
                ["Modelled state of health after one year", fmt(t["soh_year1"], "pct"), "", ""],
                ["Modelled state of health after ten years", fmt(t["soh_year10"], "pct"), "", ""]]
        return _md(["KPI", "Value", "Guarantee or limit (illustrative)", "Months meeting it"], rows, "---|---:|---:|---:")
    if name == "ems":
        t = s["technical_ems"]
        rows = [["Availability, LTSA formula", fmt(t["availability"], "pct")], ["RTE incl. auxiliaries", fmt(t["rte"], "pct")],
                ["Auxiliary energy, share of import", fmt(t["aux_share_of_import"], "pct")],
                ["Cycles per year (EFC)", fmt(t["efc_per_year"], "num1")],
                ["Warranty violations found", fmt(t["violations"], "int")],
                ["Illustrative damages", f"{fmt(t['ld_total_illustrative'], 'pln')} {t['ld_currency']}"]]
        return _md(["Synthetic EMS battery", "Value"], rows, "---|---:")
    raise KeyError(f"unknown table {name}")


def render(template: str, summary: dict) -> str:
    s = {**summary, "derived": derive(summary)}

    def sub(m: re.Match) -> str:
        key, kind = m.group(1), m.group(2)
        if key.startswith("table:"):
            return table(key[6:], s)
        return fmt(lookup(s, key), kind or "text")

    return PLACEHOLDER.sub(sub, template)


def lint(template: str) -> list[str]:
    """Numbers written by hand in the prose of the template (outside code, links, comments and placeholders)."""
    t = re.sub(r"```.*?```", "", template, flags=re.S)
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    t = PLACEHOLDER.sub("", t)
    t = re.sub(r"`[^`]*`", "", t)
    t = re.sub(r"\]\([^)]*\)", "]", t)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"<[^>]*>", "", t)
    return [line.strip() for line in t.splitlines() if DIGIT.search(line)]


def write(root: Path, check: bool = False) -> int:
    template = (root / "README.template.md").read_text(encoding="utf-8")
    bad = lint(template)
    if bad:
        raise SystemExit("numbers written by hand in README.template.md:\n" + "\n".join(bad))
    summary = json.loads((root / "results" / "summary.json").read_text(encoding="utf-8"))
    text = render(template, summary)
    target = root / "README.md"
    if check:
        return 0 if target.exists() and target.read_text(encoding="utf-8") == text else 1
    target.write_text(text, encoding="utf-8")
    return 0
