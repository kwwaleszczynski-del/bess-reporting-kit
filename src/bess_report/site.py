"""The GitHub Pages landing page: ``docs/index.html`` with the example reports, their Excel files and the headline
figures of ``results/summary.json`` (every number comes from there).

Usage:
    python -m bess_report site
"""
from __future__ import annotations

import json
from pathlib import Path

from bess_report import readme
from bess_report.render import CSS, esc, fmt


def build(root: Path) -> Path:
    s = json.loads((root / "results" / "summary.json").read_text(encoding="utf-8"))
    d = readme.derive(s)
    st, tn, fin = s["strategies"], s["technical_nem"], s["financial"]
    cards = [
        ("Technical report", "technical-nem",
         f"{tn['name']}, {tn['months']} months of AEMO open data: availability {fmt(tn['availability'], 'pct')}, RTE "
         f"{fmt(tn['rte'], 'pct')}, {fmt(tn['efc_per_year'], 'num1')} cycles per year."),
        ("Technical report, EMS table", "technical-ems",
         f"The same layout on an EMS export (synthetic battery with known truth): "
         f"{s['technical_ems']['violations']} warranty violations found, availability {fmt(s['technical_ems']['availability'], 'pct')}."),
        ("Financial report", "financial-example",
         f"Simulated year, margin {fmt(fin['bridge']['end'], 'pln')} PLN against a budget of {fmt(fin['bridge']['start'], 'pln')} PLN, "
         "with a bridge whose steps add up."),
        ("Strategy comparison", "strategies-example",
         f"Revenue stack {fmt(st['stack_asof']['pln_per_mw_year'], 'pln')} PLN/MW/year, day-ahead arbitrage "
         f"{fmt(st['da_asof']['pln_per_mw_year'], 'pln')}, all as-of, over {s['strategy_meta']['days']} days."),
    ]
    items = "".join(
        f"<div class=\"card\"><h3>{esc(t)}</h3><p>{esc(text)}</p><p><a href=\"report/{slug}.html\">Open the report</a> · "
        f"<a href=\"report/{slug}.xlsx\">Excel</a></p></div>" for t, slug, text in cards)
    extra = ".card{border:1px solid var(--line);border-radius:8px;padding:.2em 1em;margin:.8em 0}.card h3{margin:.6em 0 .2em}"
    body = (f"<main><h1>bess-reporting-kit</h1><p class=\"sub\">Technical and financial reports for grid batteries and a "
            "common evaluation of energy sales strategies, built on open data. Working material: contract terms are "
            "illustrative, capacity market terms are to be verified, money figures are a simulation.</p>"
            f"{items}<h2>Strategies on one evaluation</h2><img alt=\"strategies\" src=\"report/img/strategies-example_strategies.png\">"
            "<h2>Budget to actual margin</h2><img alt=\"bridge\" src=\"report/img/financial-example_bridge.png\">"
            "<footer><a href=\"https://github.com/kwwaleszczynski-del/bess-reporting-kit\">Source and README</a></footer></main>")
    html = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" "
            "content=\"width=device-width,initial-scale=1\"><title>bess-reporting-kit</title>"
            f"<style>{CSS}{extra}</style></head><body>{body}</body></html>")
    out = root / "docs" / "index.html"
    out.write_text(html, encoding="utf-8")
    return out
