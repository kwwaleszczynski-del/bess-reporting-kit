"""The GitHub Pages landing page: ``docs/index.html`` with key figures, the example reports (thumbnails, HTML and
Excel links) and the main charts. Every number comes from ``results/summary.json``.

Usage:
    python -m bess_report site
"""
from __future__ import annotations

import json
from pathlib import Path

from bess_report import readme
from bess_report.render import GITHUB, esc, fmt, note, page, section, tiles

IMG = "report/img/"


def _picture(name: str, alt: str) -> str:
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="{IMG}{name}_dark.png">'
            f'<img alt="{esc(alt)}" src="{IMG}{name}.png"></picture>')


def card(title: str, text: str, slug: str, thumb: str) -> str:
    return (f'<div class="card"><a class="thumb" href="report/{slug}.html">{_picture(thumb, title)}</a>'
            f'<div class="body"><h3>{esc(title)}</h3><p>{esc(text)}</p><div class="btns">'
            f'<a class="btn p" href="report/{slug}.html">Open report</a>'
            f'<a class="btn" href="report/{slug}.xlsx">Excel</a></div></div></div>')


def build(root: Path) -> Path:
    s = json.loads((root / "results" / "summary.json").read_text(encoding="utf-8"))
    d = readme.derive(s)
    st, tn, te, meta = s["strategies"], s["technical_nem"], s["technical_ems"], s["strategy_meta"]
    cap = f"{d['capacity_lines_share'] * 100:.0f} %"
    head = tiles([
        ("Revenue stack, as-of", fmt(st["stack_asof"]["share_of_ceiling"], "pct"),
         f"of its perfect-foresight ceiling; simulation, price taker of 1 MW, {cap} of revenue from balancing capacity"),
        ("Day-ahead arbitrage, as-of", fmt(st["da_asof"]["share_of_ceiling"], "pct"),
         "of its ceiling, with a plain seven-day average forecast"),
        ("Declared availability", fmt(tn["availability"], "pct"),
         f"NEM battery on open AEMO data; RTE {fmt(tn['rte'], 'pct')}, {fmt(tn['efc_per_year'], 'num1')} cycles per year"),
        ("Margin against budget", f"{d['bridge_change_pct'] * 100:+.1f} %",
         "simulated year, rule-based budget, bridge adds up exactly"),
    ])
    cards = "".join([
        card("Technical report, NEM battery",
             f"{tn['name']}: {tn['months']} months of AEMO open data, availability, RTE, cycles, state of health.",
             "technical-nem", "technical-nem_availability"),
        card("Technical report, EMS table",
             f"The same layout on an EMS export (synthetic battery with known truth): {te['violations']} warranty "
             "violations found, auxiliary load, LTSA availability.", "technical-ems", "technical-ems_rte"),
        card("Financial report",
             "Revenue by source, costs, margin, budget variance and a budget-to-actual bridge. A simulation on public "
             "prices, not a real plant.", "financial-example", "financial-example_bridge"),
        card("Strategy comparison",
             f"Day-ahead arbitrage, revenue stack, tolling and capacity market on one evaluation, {meta['days']} days, "
             "every plan made with an explicit as-of information set.", "strategies-example",
             "strategies-example_strategies"),
    ])
    fig = lambda name, alt: f'<div class="fig">{_picture(name, alt)}</div>'   # noqa: E731
    sat = ""
    if "sat_large_mw" in d:
        sat = (f" In a fleet model, at {d['sat_large_mw']:,} MW of identical batteries a battery keeps "
               f"{d['sat_large_retention'] * 100:.0f} % of the lone battery's margin.").replace(",", " ")
    body = [
        note("Working material, not an official statement and not investment advice. The money figures are a simulation "
             "on public prices for a price taker of 1 MW; balancing markets are small, so they do not scale to a fleet. "
             "Toll, guarantees and fixed costs are illustrative placeholders; capacity market terms are to be verified." + sat),
        section("Example reports", f'<div class="cards">{cards}</div>'),
        section("Strategies on one evaluation", fig("strategies-example_strategies", "strategies")),
        section("Budget to actual margin", fig("financial-example_bridge", "budget bridge")),
        section("Source", f'<p>Code, README with the method and the limits, and the tests: '
                          f'<a href="{GITHUB}">{esc(GITHUB)}</a>.</p>'),
    ]
    html = page("bess-reporting-kit",
                "Technical and financial reports for grid batteries and a common evaluation of energy sales strategies, "
                "built on open data (PSE, AEMO).", body, footer="Working material. Illustrative terms are marked.",
                prefix="report/", head_tiles=head)
    out = root / "docs" / "index.html"
    out.write_text(html, encoding="utf-8", newline="\n")
    return out
