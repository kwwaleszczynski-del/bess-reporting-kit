"""HTML and Excel output of the three reports.

HTML pages (inline CSS, charts as PNG files in an ``img`` folder next to the page) that read on a phone: tables scroll
sideways inside their own box, pictures scale to the width, colours follow the light or dark setting of the
device. Excel workbooks (openpyxl) have one sheet per table with formatted headers, frozen panes, number formats
and conditional formatting for compliance and variance columns.

Usage:
    html = page("Technical report", "RANGEB1", [section("KPIs", table_html(df, {"rte": "pct"}))])
    write_excel(Path("technical.xlsx"), {"Monthly": df}, formats={"Monthly": {"rte": "0.0%"}})
"""
from __future__ import annotations

import html as _html
from pathlib import Path

import numpy as np
import pandas as pd

CSS = """
:root{--bg:#fff;--fg:#1d2733;--mut:#5b6773;--line:#d5dbe1;--head:#eef2f6;--ok:#1d7a3f;--bad:#b3362b;--acc:#2a6fb0}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#12171d;--fg:#e4e9ee;--mut:#9aa6b2;--line:#2c3540;--head:#1b222a;--ok:#5cc184;--bad:#ef7b6e;--acc:#6fb0ee}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:980px;margin:0 auto;padding:20px 16px 48px}h1{font-size:1.6rem;margin:.2em 0}h2{font-size:1.2rem;margin:1.8em 0 .5em;border-bottom:1px solid var(--line);padding-bottom:.2em}
p.sub{color:var(--mut);margin:.2em 0 1em}.note{border-left:4px solid var(--acc);background:var(--head);padding:.6em .9em;margin:1em 0;border-radius:4px;font-size:.93rem}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{padding:.35em .6em;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{background:var(--head);position:sticky;top:0}th:first-child,td:first-child{text-align:left;white-space:normal;min-width:9em}td.ok{color:var(--ok);font-weight:600}td.bad{color:var(--bad);font-weight:600}
img{max-width:100%;height:auto;display:block;margin:.6em auto}nav a{margin-right:1em;color:var(--acc)}footer{color:var(--mut);font-size:.85rem;margin-top:2.5em}
"""


def esc(s) -> str:
    return _html.escape(str(s))


def fmt(v, kind: str = "num") -> str:
    """Format a value: pct (0.953 -> 95.3 %), pln (thousands separator), num1, num2, int, text."""
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA:
        return ""
    if kind == "pct":
        return f"{v * 100:.1f} %"
    if kind == "pct2":
        return f"{v * 100:.2f} %"
    if kind in ("pln", "int"):
        return f"{v:,.0f}".replace(",", " ")
    if kind == "num1":
        return f"{v:,.1f}".replace(",", " ")
    if kind == "num2":
        return f"{v:,.2f}"
    if kind == "bool":
        return "yes" if bool(v) else "no"
    return str(v)


def table_html(df: pd.DataFrame, kinds: dict[str, str] | None = None, index: bool = True, headers: dict | None = None,
               status_cols: tuple[str, ...] = ()) -> str:
    """HTML table; ``kinds`` maps column -> ``fmt`` kind, ``status_cols`` colour booleans (True good)."""
    kinds = kinds or {}
    headers = headers or {}
    cols = list(df.columns)
    head = "".join(f"<th>{esc(headers.get(c, c))}</th>" for c in ([df.index.name or ""] if index else []) + cols)
    rows = []
    for idx, r in df.iterrows():
        cells = [f"<td>{esc(idx)}</td>"] if index else []
        for c in cols:
            v = r[c]
            if c in status_cols and not pd.isna(v):
                cells.append(f"<td class=\"{'ok' if bool(v) else 'bad'}\">{'yes' if bool(v) else 'NO'}</td>")
            else:
                cells.append(f"<td>{esc(fmt(v, kinds.get(c, 'num2' if isinstance(v, float) else 'text')))}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<div class=\"scroll\"><table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def img(src: str, alt: str) -> str:
    """An ``<img>`` that points at a PNG saved next to the page (relative path)."""
    return f"<img alt=\"{esc(alt)}\" src=\"{esc(src)}\">"


def section(title: str, body: str) -> str:
    return f"<h2>{esc(title)}</h2>\n{body}"


def note(text: str) -> str:
    return f"<div class=\"note\">{esc(text)}</div>"


def page(title: str, subtitle: str, sections: list[str], nav: list[tuple[str, str]] | None = None,
         footer: str = "") -> str:
    links = "<nav>" + "".join(f"<a href=\"{esc(h)}\">{esc(t)}</a>" for t, h in nav) + "</nav>" if nav else ""
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{esc(title)}</title><style>{CSS}</style></head><body><main>{links}<h1>{esc(title)}</h1>"
            f"<p class=\"sub\">{esc(subtitle)}</p>{''.join(sections)}<footer>{esc(footer)}</footer></main></body></html>")


# ---------------------------------------------------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------------------------------------------------

def write_excel(path: Path, sheets: dict[str, pd.DataFrame], formats: dict[str, dict[str, str]] | None = None,
                notes: list[str] | None = None, status: dict[str, tuple[str, ...]] | None = None) -> Path:
    """One sheet per frame. ``formats``: sheet -> column -> Excel number format; ``status``: sheet -> boolean
    columns shaded green/red; negative numbers of columns named ``difference`` are shaded red."""
    from openpyxl import Workbook
    from openpyxl.formatting.rule import CellIsRule, FormulaRule
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    formats, status = formats or {}, status or {}
    wb = Workbook()
    wb.remove(wb.active)
    head_fill, head_font = PatternFill("solid", fgColor="1F4E78"), Font(bold=True, color="FFFFFF")
    green, red = PatternFill("solid", bgColor="C6EFCE"), PatternFill("solid", bgColor="FFC7CE")
    for name, df in sheets.items():
        ws = wb.create_sheet(name[:31])
        frame = df.reset_index() if not isinstance(df.index, pd.RangeIndex) else df
        r0 = 1
        for n in (notes if name == next(iter(sheets)) else []) or []:
            ws.cell(row=r0, column=1, value=n).font = Font(italic=True)
            r0 += 1
        for j, c in enumerate(frame.columns, 1):
            cell = ws.cell(row=r0, column=j, value=str(c))
            cell.fill, cell.font = head_fill, head_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for i, row in enumerate(frame.itertuples(index=False), r0 + 1):
            for j, v in enumerate(row, 1):
                if isinstance(v, (np.floating, float)) and np.isnan(v) or v is pd.NA:
                    v = None
                elif isinstance(v, (np.bool_, bool)):
                    v = bool(v)
                elif isinstance(v, (np.integer,)):
                    v = int(v)
                elif isinstance(v, np.floating):
                    v = float(v)
                elif not isinstance(v, (int, float, str, bool)) and v is not None:
                    v = str(v)
                ws.cell(row=i, column=j, value=v)
        last = r0 + len(frame)
        for j, c in enumerate(frame.columns, 1):
            letter = get_column_letter(j)
            fmt_ = formats.get(name, {}).get(str(c))
            if fmt_:
                for i in range(r0 + 1, last + 1):
                    ws.cell(row=i, column=j).number_format = fmt_
            if str(c) in status.get(name, ()):
                rng = f"{letter}{r0 + 1}:{letter}{last}"
                ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=["TRUE"], fill=green))
                ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=["FALSE"], fill=red))
            if str(c) == "difference" and last > r0:
                ws.conditional_formatting.add(f"{letter}{r0 + 1}:{letter}{last}",
                                              FormulaRule(formula=[f"{letter}{r0 + 1}<0"], fill=red))
            width = max([len(str(c))] + [len(str(x)) for x in frame[c].head(200)]) + 2
            ws.column_dimensions[letter].width = min(max(width, 10), 48)
        ws.freeze_panes = ws.cell(row=r0 + 1, column=2)
        ws.row_dimensions[r0].height = 32
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
