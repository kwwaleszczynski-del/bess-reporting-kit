"""Command line interface.

Usage:
    python -m bess_report example --workers 4                       # the bundled reports, results/, docs/
    python -m bess_report readme                                    # README.md from README.template.md and results/
    python -m bess_report site                                      # docs/index.html
    python -m bess_report technical --nem-slice data/example/nem --duid RANGEB1 --site config/site.example.yaml
    python -m bess_report technical --ems ems.parquet --mapping m.yaml --ems-site s.yaml --warranty w.yaml \\
        --ltsa l.yaml --events events.csv --out out/
    python -m bess_report financial --settlement settlement.csv --budget budget.csv --site config/site.example.yaml
    python -m bess_report strategies --site config/site.example.yaml --workers 4
    python -m bess_report fetch-pse --start 2024-09-23 --end 2026-09-30
    python -m bess_report prepare-nem --nem-data-dir D --nem-extra-dir E --duid RANGEB1

Paths come from arguments or the environment variables BESS_NEM_DATA_DIR and BESS_NEM_EXTRA_DIR; nothing is
hard-coded.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

log = logging.getLogger("bess_report")


def _env_path(name: str) -> Path | None:
    v = os.environ.get(name)
    return Path(v) if v else None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="bess_report", description=__doc__.splitlines()[0])
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("example", help="reports from the bundled open data: results/, docs/report")
    e.add_argument("--root", type=Path, default=Path("."))
    e.add_argument("--site", type=Path, default=Path("config/site.example.yaml"))
    e.add_argument("--workers", type=int, default=1)
    e.add_argument("--duid", default="RANGEB1")

    r = sub.add_parser("readme", help="render README.md from README.template.md and results/summary.json")
    r.add_argument("--root", type=Path, default=Path("."))
    r.add_argument("--check", action="store_true", help="fail if README.md differs instead of writing it")

    sub.add_parser("site", help="docs/index.html from results/summary.json").add_argument("--root", type=Path, default=Path("."))

    t = sub.add_parser("technical", help="technical report of a NEM battery or of an EMS table")
    t.add_argument("--site", type=Path, help="site YAML (guarantees to assess against)")
    t.add_argument("--nem-slice", type=Path, help="directory written by prepare-nem")
    t.add_argument("--duid")
    t.add_argument("--ems", type=Path, help="long EMS table (Parquet or CSV)")
    t.add_argument("--mapping", type=Path)
    t.add_argument("--ems-site", type=Path)
    t.add_argument("--warranty", type=Path)
    t.add_argument("--ltsa", type=Path)
    t.add_argument("--events", type=Path)
    t.add_argument("--out", type=Path, default=Path("out"))

    f = sub.add_parser("financial", help="financial report from settlement and budget tables")
    f.add_argument("--settlement", type=Path, required=True)
    f.add_argument("--budget", type=Path, required=True)
    f.add_argument("--site", type=Path, required=True)
    f.add_argument("--out", type=Path, default=Path("out"))

    s = sub.add_parser("strategies", help="compare the sales strategies on one evaluation")
    s.add_argument("--site", type=Path, required=True)
    s.add_argument("--data", type=Path, default=Path("data/example"), help="PSE slice (fetch-pse)")
    s.add_argument("--workers", type=int, default=1)
    s.add_argument("--out", type=Path, default=Path("out"))

    d = sub.add_parser("fetch-pse", help="download PSE prices into the example slice")
    d.add_argument("--start", default="2024-09-23")
    d.add_argument("--end", default="2026-09-30")
    d.add_argument("--cache", type=Path, default=Path("data/cache"))
    d.add_argument("--out", type=Path, default=Path("data/example"))

    n = sub.add_parser("prepare-nem", help="cut one battery out of the NEM caches into a small slice")
    n.add_argument("--nem-data-dir", type=Path, default=_env_path("BESS_NEM_DATA_DIR"))
    n.add_argument("--nem-extra-dir", type=Path, default=_env_path("BESS_NEM_EXTRA_DIR"))
    n.add_argument("--duid", required=True)
    n.add_argument("--out", type=Path, default=Path("data/example/nem"))

    a = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)

    if a.cmd == "example":
        from bess_report.example import run
        run(a.root, a.site, a.workers, a.duid)
    elif a.cmd == "readme":
        from bess_report.readme import write
        return write(a.root, a.check)
    elif a.cmd == "site":
        from bess_report.site import build
        build(a.root)
    elif a.cmd == "technical":
        from bess_report import reports, technical
        from bess_report.schema import load_site
        guarantees = load_site(a.site).guarantees if a.site else {}
        if a.nem_slice:
            if not a.duid:
                p.error("--duid is required with --nem-slice")
            from bess_report.nemslice import load_slice
            rep = technical.from_nem(load_slice(a.nem_slice), a.duid, guarantees)
            reports.technical_report(rep, guarantees, a.out, "nem")
        elif a.ems:
            if not (a.mapping and a.ems_site):
                p.error("--mapping and --ems-site are required with --ems")
            res = technical.analyse_ems(a.ems, a.mapping, a.ems_site, a.warranty, a.ltsa, a.events)
            rep = technical.from_ems(res, guarantees)
            reports.technical_report(rep, guarantees, a.out, "ems")
        else:
            p.error("give --nem-slice or --ems")
    elif a.cmd == "financial":
        from bess_report import reports
        from bess_report.financial import Bridge, statement
        from bess_report.schema import load_site, read_money
        site = load_site(a.site)
        act, bud = statement(read_money(a.settlement)), statement(read_money(a.budget))
        months = sorted(set(act.index) & set(bud.index))
        sim = {"statement": act.loc[months], "budget_statement": bud.loc[months], "settlement": read_money(a.settlement),
               "budget": read_money(a.budget),
               "bridge": Bridge("Budget margin", float(bud.loc[months, "margin"].sum()),
                                [("Variance of the period (no re-runs: supply a model to split it)",
                                  float(act.loc[months, "margin"].sum() - bud.loc[months, "margin"].sum()))],
                                "Actual margin", float(act.loc[months, "margin"].sum())),
               "assumptions": {"budget_availability": float("nan"), "nameplate_rte": float("nan"),
                               "measured_rte_mean": float("nan"), "measured_availability_mean": float("nan"),
                               "budget_rule": "budget table supplied by the user"}}
        paths = reports.financial_report(sim, site, a.out, "user")
        log.info("written %s and %s", paths["html"], paths["xlsx"])
    elif a.cmd == "strategies":
        from bess_report import data, reports, scenario
        from bess_report.schema import load_site
        from bess_report.strategies import build_days
        site = load_site(a.site)
        prices, capacity = data.load_slice(a.data)
        days = build_days(prices, capacity)
        runs = scenario.run_all(site, days, a.workers)
        table = scenario.compare(site, runs)
        mw = site.battery.power_mw
        monthly = {k: scenario.margin_by_month(v) * table.attrs["availability"] / mw for k, v in runs.items()}
        import pandas as pd
        paths = reports.strategy_report(table, pd.DataFrame(monthly), site, a.out, "user")
        log.info("written %s and %s", paths["html"], paths["xlsx"])
    elif a.cmd == "fetch-pse":
        from bess_report import data
        prices, capacity = data.fetch(date.fromisoformat(a.start), date.fromisoformat(a.end), a.cache)
        data.save_slice(prices, capacity, a.out)
    elif a.cmd == "prepare-nem":
        if a.nem_data_dir is None or a.nem_extra_dir is None:
            p.error("--nem-data-dir and --nem-extra-dir (or BESS_NEM_DATA_DIR, BESS_NEM_EXTRA_DIR) are required")
        from bess_report.nemslice import cut
        cut(a.nem_data_dir, a.nem_extra_dir, a.duid, a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
