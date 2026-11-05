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
:root{--bg:#f6f8fa;--card:#ffffff;--fg:#1b2430;--mut:#5a6775;--line:#d8dee5;--head:#eaf0f6;--ok:#1d7a3f;--bad:#b3362b;
--acc:#1f6fb2;--acc2:#e08a2e;--hero1:#e6f0fa;--hero2:#f6f8fa;--shadow:0 1px 3px rgba(20,35,55,.08)}
@media (prefers-color-scheme:dark){:root{--bg:#12171d;--card:#181f27;--fg:#e4e9ee;--mut:#9aa6b2;--line:#2b3541;--head:#1f2833;
--ok:#5cc184;--bad:#ef7b6e;--acc:#6fb0ee;--acc2:#f0a24d;--hero1:#16283a;--hero2:#12171d;--shadow:none}}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
.top{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line)}
.top>div{max-width:1040px;margin:0 auto;padding:.55em 16px;display:flex;gap:.3em 1.2em;flex-wrap:wrap;align-items:center;font-size:.92rem}
.top b{margin-right:auto;color:var(--fg)}.top a{color:var(--mut)}.top a.on,.top a:hover{color:var(--acc)}
.hero{background:linear-gradient(180deg,var(--hero1),var(--hero2));border-bottom:1px solid var(--line)}
.hero>div,main{max-width:1040px;margin:0 auto;padding:0 16px}.hero>div{padding:28px 16px 22px}
h1{font-size:clamp(1.6rem,4.5vw,2.3rem);line-height:1.2;margin:0 0 .3em}
h2{font-size:1.3rem;margin:2em 0 .6em}h3{margin:.2em 0 .3em;font-size:1.05rem}
p.sub{color:var(--mut);margin:.2em 0;max-width:46em}main{padding-bottom:56px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin:18px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;box-shadow:var(--shadow);border-top:3px solid var(--acc)}
.tile:nth-child(even){border-top-color:var(--acc2)}
.tile .v{font-size:1.9rem;font-weight:700;line-height:1.15}.tile .l{color:var(--mut);font-size:.85rem;text-transform:uppercase;letter-spacing:.04em}
.tile .c{color:var(--mut);font-size:.85rem;margin-top:.3em}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;margin:12px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;box-shadow:var(--shadow);display:flex;flex-direction:column}
.card .thumb{display:block;background:var(--card);border-bottom:1px solid var(--line)}.card img{margin:0;width:100%;height:190px;object-fit:contain;object-position:center}
.card .body{padding:12px 16px 14px;display:flex;flex-direction:column;gap:.5em;flex:1}.card p{margin:0;color:var(--mut);font-size:.92rem}
.btns{margin-top:auto;display:flex;gap:.6em;flex-wrap:wrap}
.btn{display:inline-block;padding:.35em .9em;border-radius:6px;border:1px solid var(--acc);color:var(--acc);font-weight:600;font-size:.9rem}
.btn.p{background:var(--acc);color:var(--bg)}.btn:hover{text-decoration:none;opacity:.88}
.note{border-left:4px solid var(--acc2);background:var(--card);border-top:1px solid var(--line);border-right:1px solid var(--line);border-bottom:1px solid var(--line);
padding:.7em 1em;margin:1em 0;border-radius:6px;font-size:.93rem}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;background:var(--card);border:1px solid var(--line);border-radius:8px;margin:.6em 0}
table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{padding:.45em .7em;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
tbody tr:nth-child(even){background:var(--bg)}tbody tr:last-child td{border-bottom:0}
th{background:var(--head);position:sticky;top:0;font-weight:600}th:first-child,td:first-child{text-align:left;white-space:normal;min-width:9em}
td.ok{color:var(--ok);font-weight:600}td.bad{color:var(--bad);font-weight:600}
picture,img{max-width:100%}img{height:auto;display:block;margin:.6em auto;border-radius:6px}
.fig{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px;margin:.6em 0}
footer{color:var(--mut);font-size:.85rem;margin-top:2.5em;border-top:1px solid var(--line);padding-top:1em}
@media (max-width:560px){.tile .v{font-size:1.6rem}.card img{height:160px}}
"""

SITE_NAME = "bess-reporting-kit"
GITHUB = "https://github.com/kwwaleszczynski-del/bess-reporting-kit"
NAV_ITEMS = [("Technical, NEM", "technical-nem.html"), ("Technical, EMS", "technical-ems.html"),
             ("Financial", "financial-example.html"), ("Strategies", "strategies-example.html")]


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
    """A chart PNG saved next to the page (relative path); ``<name>_dark.png`` is shown in dark mode."""
    dark = src[:-4] + "_dark.png"
    return (f"<div class=\"fig\"><picture><source media=\"(prefers-color-scheme: dark)\" srcset=\"{esc(dark)}\">"
            f"<img alt=\"{esc(alt)}\" src=\"{esc(src)}\"></picture></div>")


def section(title: str, body: str) -> str:
    return f"<h2>{esc(title)}</h2>\n{body}"


def note(text: str) -> str:
    return f"<div class=\"note\">{esc(text)}</div>"


def tiles(items: list[tuple[str, str, str]]) -> str:
    """Key-figure tiles: (label, value, caption)."""
    return "<div class=\"tiles\">" + "".join(
        f"<div class=\"tile\"><div class=\"l\">{esc(label)}</div><div class=\"v\">{esc(value)}</div>"
        f"<div class=\"c\">{esc(cap)}</div></div>" for label, value, cap in items) + "</div>"


def _link(prefix: str, href: str, text: str, current: str) -> str:
    cls = ' class="on"' if href == current else ""
    return f'<a{cls} href="{prefix}{href}">{esc(text)}</a>'


def topbar(prefix: str = "", current: str = "") -> str:
    home = "index.html" if prefix else "../index.html"
    links = "".join(_link(prefix, href, t, current) for t, href in NAV_ITEMS)
    return (f'<div class="top"><div><b><a href="{home}">{SITE_NAME}</a></b>{links}'
            f'<a href="{GITHUB}">GitHub</a></div></div>')


def page(title: str, subtitle: str, sections: list[str], nav: list[tuple[str, str]] | None = None,
         footer: str = "", current: str = "", prefix: str = "", head_tiles: str = "") -> str:
    """A report page: top bar, hero with the title and key tiles, then the sections. ``prefix`` is the path from
    the page to the report folder ("" inside it, "report/" from the landing page)."""
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<meta name=\"color-scheme\" content=\"light dark\">"
            f"<title>{esc(title)}</title><style>{CSS}</style></head><body>{topbar(prefix, current)}"
            f"<div class=\"hero\"><div><h1>{esc(title)}</h1><p class=\"sub\">{esc(subtitle)}</p>{head_tiles}</div></div>"
            f"<main>{''.join(sections)}<footer>{esc(footer)}</footer></main></body></html>")


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
