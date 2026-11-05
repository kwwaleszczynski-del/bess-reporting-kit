"""Charts of the reports (matplotlib), drawn so that no two texts overlap; ``text_overlaps`` checks that on the
rendered figure and the tests run it on every chart.

Every function returns a ``Figure``; ``save`` writes a PNG. Legends sit below the axes, never on the data, and the
font sizes are large enough to stay readable when a page scales the picture down to a phone.

Usage:
    fig = bridge_chart(bridge.frame())
    assert not text_overlaps(fig)
    save(fig, Path("docs/report/img/bridge.png"))
"""
from __future__ import annotations

from itertools import combinations
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

plt.rcParams.update({"font.size": 12, "axes.titlesize": 13.5, "axes.labelsize": 12, "axes.spines.top": False,
                     "axes.spines.right": False, "figure.dpi": 100, "savefig.dpi": 130})
C = {"blue": "#2a6fb0", "orange": "#d9822b", "green": "#3a9a5b", "red": "#c24a3d", "grey": "#7b8794",
     "purple": "#7a5aa6", "teal": "#2a9d9d", "brown": "#8c6d46"}
LINE_COLORS = {"da_sales": C["blue"], "fcr_capacity": C["orange"], "afrr_capacity": C["green"],
               "mfrrd_capacity": C["purple"], "rr_capacity": C["teal"], "capacity_market": C["grey"],
               "toll": C["red"]}
WIDTH = 6.4


def save(fig: Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def text_overlaps(fig: Figure, gap: float = 4.0) -> list[tuple[str, str]]:
    """Pairs of visible texts (tick labels, titles, legend entries, annotations) closer than ``gap`` pixels."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    items = []
    for ax in fig.axes:
        ticks = [(t, "rot" if t.get_rotation() % 90 else "tick") for t in (*ax.get_xticklabels(), *ax.get_yticklabels())]
        other = [(t, "other") for t in (ax.title, ax.xaxis.label, ax.yaxis.label, *ax.texts)]
        leg = ax.get_legend()
        if leg is not None:
            other += [(t, "other") for t in leg.get_texts()]
        for t, kind in ticks + other:
            if t.get_visible() and t.get_text().strip():
                items.append((t.get_text(), kind, t.get_window_extent(renderer).padded(gap / 2)))
    # the boxes of tilted tick labels overlap their neighbours' boxes although the glyphs do not: not compared
    # with other tick labels
    return [(a, b) for (a, ka, ba), (b, kb, bb) in combinations(items, 2)
            if ba.overlaps(bb) and not ("rot" in (ka, kb) and {ka, kb} <= {"rot", "tick"})]


def _months(index) -> list[str]:
    return [pd.Period(m, freq="M").strftime("%b %y") for m in index]


def _legend_below(ax, ncol: int = 2, offset: float = -0.28):
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, offset), ncol=ncol, frameon=False)


def availability_chart(monthly: pd.DataFrame, guarantee: float | None) -> Figure:
    fig, ax = plt.subplots(figsize=(WIDTH, 4.2))
    x = np.arange(len(monthly))
    ax.plot(x, monthly["availability"] * 100, marker="o", color=C["blue"], label="Technical availability")
    if monthly["availability_offered"].notna().any():
        ax.plot(x, monthly["availability_offered"] * 100, marker="s", color=C["orange"], label="Offered availability")
    if guarantee is not None:
        ax.axhline(guarantee * 100, color=C["red"], ls="--", label=f"Guarantee {guarantee * 100:.0f} %")
    ax.set_xticks(x, _months(monthly.index), rotation=45, ha="right")
    ax.set_ylabel("Share of rated power, %")
    ax.set_ylim(0, 105)
    ax.set_title("Availability by month")
    _legend_below(ax, 3, -0.38)
    return fig


def rte_chart(monthly: pd.DataFrame, guarantee: float | None) -> Figure:
    fig, ax = plt.subplots(figsize=(WIDTH, 4.2))
    x = np.arange(len(monthly))
    ax.plot(x, monthly["rte"] * 100, marker="o", color=C["blue"], label="RTE, SoC-corrected")
    if monthly["rte_excl_aux"].notna().any():
        ax.plot(x, monthly["rte_excl_aux"] * 100, marker="s", color=C["green"], label="RTE excl. auxiliaries")
    if guarantee is not None:
        ax.axhline(guarantee * 100, color=C["red"], ls="--", label=f"Guarantee {guarantee * 100:.0f} %")
    lo = np.nanmin([monthly["rte"].min() * 100, (guarantee or 1) * 100]) - 3
    ax.set_ylim(lo, np.nanmax(monthly["rte"].max() * 100) + 3)
    ax.set_xticks(x, _months(monthly.index), rotation=45, ha="right")
    ax.set_ylabel("Round-trip efficiency, %")
    ax.set_title("Round-trip efficiency by month")
    _legend_below(ax, 3, -0.38)
    return fig


def soh_chart(soh: pd.DataFrame) -> Figure:
    years = np.array(soh.index, dtype=float)
    fig, ax = plt.subplots(figsize=(WIDTH, 4.2))
    ax.stackplot(years, soh["calendar_loss"] * 100, soh["cycle_loss"] * 100, colors=[C["orange"], C["blue"]],
                 labels=["Calendar ageing", "Cycle ageing"], alpha=0.85)
    ax.set_xlabel("Years of operation at the observed duty")
    ax.set_ylabel("Capacity lost, % of initial")
    ax.set_xticks(years)
    ax.set_title("Modelled capacity loss")
    _legend_below(ax, 2, -0.26)
    return fig


def aux_chart(bins: pd.DataFrame) -> Figure:
    fig, ax = plt.subplots(figsize=(WIDTH, 4.2))
    ax.plot(bins.index, bins.iloc[:, 0], marker="o", color=C["blue"], label="Mean auxiliary power")
    ax.set_xlabel("Ambient temperature, degC")
    ax.set_ylabel("Auxiliary power, MW")
    ax.set_title("Auxiliary load against temperature")
    _legend_below(ax, 1, -0.26)
    return fig


def revenue_mix_chart(stmt: pd.DataFrame, lines: dict[str, str]) -> Figure:
    fig, ax = plt.subplots(figsize=(WIDTH, 4.6))
    x = np.arange(len(stmt))
    bottom = np.zeros(len(stmt))
    for k, label in lines.items():
        if k in stmt and stmt[k].abs().sum() > 0:
            v = stmt[k].to_numpy() / 1e3
            ax.bar(x, v, bottom=bottom, color=LINE_COLORS.get(k, C["grey"]), label=label)
            bottom += v
    ax.set_xticks(x, _months(stmt.index), rotation=45, ha="right")
    ax.set_ylabel("Revenue, thousand PLN")
    ax.set_title("Revenue by source and month")
    _legend_below(ax, 2, -0.30)
    return fig


def bridge_chart(frame: pd.DataFrame, unit: float = 1e3, unit_label: str = "thousand PLN") -> Figure:
    """Waterfall; labels at the ends of the bars, step names wrapped on the axis."""
    import textwrap

    fig, ax = plt.subplots(figsize=(WIDTH, 5.6))
    vals = frame["value_pln"].to_numpy() / unit
    level, levels, bottoms, heights, colors = 0.0, [], [], [], []
    for kind, v in zip(frame["kind"], vals):
        if kind == "total":
            level = v
            bottoms.append(None)
            heights.append(v)
            colors.append(C["grey"])
        else:
            bottoms.append(level if v >= 0 else level + v)
            heights.append(abs(v))
            colors.append(C["green"] if v >= 0 else C["red"])
            level += v
        levels.append(level)
    lo, hi = min(levels), max(levels)
    cut = lo > 0.5 * hi                                    # totals far above the steps: do not start at zero
    floor = lo - 1.2 * (hi - lo) if cut else min(0.0, lo)
    bottoms = [floor if b is None else b for b in bottoms]
    heights = [h - floor if b == floor and k == "total" else h for b, h, k in zip(bottoms, heights, frame["kind"])]
    x = np.arange(len(frame))
    ax.bar(x, heights, bottom=bottoms, color=colors, width=0.62)
    top = max(b + h for b, h in zip(bottoms, heights))
    span = top - floor
    for xi, v, b, h, kind in zip(x, vals, bottoms, heights, frame["kind"]):
        text = f"{v:,.0f}" if kind == "total" else f"{v:+,.0f}"
        ax.text(xi, b + h + 0.015 * span, text, ha="center", va="bottom", fontsize=10.5)
    ax.set_xticks(x, [chr(10).join(textwrap.wrap(s, 12, break_long_words=False)) for s in frame["label"]], fontsize=8.5)
    ax.set_ylim(floor, top + 0.09 * span)
    ax.set_ylabel(f"Margin, {unit_label}" + (" (axis cut)" if cut else ""))
    ax.set_title("Budget to actual margin")
    return fig


def strategy_chart(table: pd.DataFrame) -> Figure:
    """Gross margin per MW and year by strategy, with the best and worst month annualised as whiskers."""
    import textwrap

    t = table.sort_values("pln_per_mw_year")
    fig, ax = plt.subplots(figsize=(WIDTH, 0.62 * len(t) + 2.4))
    y = np.arange(len(t))
    v = t["pln_per_mw_year"].to_numpy() / 1e3
    colors = [C["grey"] if "perfect" in i else C["blue"] for i in t.index]
    ax.barh(y, v, color=colors, height=0.6)
    lo, hi = t["month_worst_pln_per_mw"].to_numpy() * 12 / 1e3, t["month_best_pln_per_mw"].to_numpy() * 12 / 1e3
    ax.hlines(y, lo, hi, color="black", lw=1.2)
    ax.plot(lo, y, "|", color="black", ms=9)
    ax.plot(hi, y, "|", color="black", ms=9)
    xmax = max(hi.max(), v.max())
    ax.set_xlim(min(0, lo.min() * 1.05), xmax * 1.18)
    for yi, vi in zip(y, v):
        ax.text(max(hi[yi], vi) + 0.02 * xmax, yi, f"{vi:,.0f}", va="center", fontsize=10)
    ax.set_yticks(y, [chr(10).join(textwrap.wrap(s, 24)) for s in t["short"]], fontsize=10.5)
    ax.set_xlabel("Gross margin, thousand PLN per MW and year" + chr(10) + "(whiskers: worst and best month x 12)")
    ax.set_title("Strategies on one evaluation")
    return fig


def strategy_monthly_chart(monthly: pd.DataFrame) -> Figure:
    fig, ax = plt.subplots(figsize=(WIDTH, 4.6))
    x = np.arange(len(monthly))
    palette = [C["blue"], C["orange"], C["green"], C["red"], C["purple"], C["teal"], C["brown"]]
    for i, col in enumerate(monthly.columns):
        ax.plot(x, monthly[col] / 1e3, marker="o", ms=4, color=palette[i % len(palette)], label=col,
                ls="--" if "perfect" in col else "-")
    ax.set_xticks(x, _months(monthly.index), rotation=45, ha="right")
    ax.set_ylabel("Gross margin, thousand PLN per MW and month")
    ax.set_title("Monthly margin by strategy")
    _legend_below(ax, 2, -0.42)
    return fig
