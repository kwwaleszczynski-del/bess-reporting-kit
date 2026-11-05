"""Technical report: availability (including the physical availability declared to AEMO's PASA), round-trip
efficiency, cycles, state of charge, state of health and warranty or LTSA compliance.

Two inputs, one report layout:

- ``from_nem``: a battery of Australia's National Electricity Market from public AEMO tables (SCADA, dispatch,
  registration, bids), analysed with ``bess_ops.nem.unit_benchmark`` of the bess-ops-warranty project. Market data
  have no auxiliary meter, temperatures or warranty terms: the RTE is at the SCADA point and the availability is
  what the operator declared, not what was measured.
- ``from_ems``: a long EMS or SCADA table (timestamp, device_id, signal, value) with the YAML files of
  bess-ops-warranty (mapping, site, warranty, LTSA, event log): LTSA availability, RTE with and without auxiliaries,
  auxiliary load against temperature, warranty violations, capacity tests and illustrative damages.

State of health: ``soh_projection`` adds the capacity the semi-empirical ageing model of bess-capacity-augmentation
(calendar plus rainflow cycle ageing, fitted on open LFP cell data) predicts for the observed duty. Market data
cannot measure SoH, so the model is shown next to what the data do show (the trend of the usable energy window).

Usage:
    rep = from_nem(load_slice(Path("data/example/nem")), "RANGEB1", site.guarantees)
    rep.monthly, rep.summary, rep.soh
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)
PROJECTION_YEARS = (1, 5, 10, 15)


@dataclass
class TechnicalReport:
    name: str
    source: str                       # "nem" or "ems"
    monthly: pd.DataFrame             # one row per month, standard columns (see STANDARD)
    summary: dict
    compliance: pd.DataFrame          # month x checks, True/False/NaN
    soh: pd.DataFrame | None = None
    notes: list[str] = field(default_factory=list)
    extras: dict = field(default_factory=dict)
    guarantees: dict = field(default_factory=dict)


STANDARD = ["availability", "availability_offered", "rte", "rte_excl_aux", "aux_mwh", "e_in_mwh", "e_out_mwh", "efc",
            "mean_soc", "usable_energy_mwh", "technical_outage_hours", "violations"]


def soh_projection(soc: np.ndarray, dt_hours: float, temp_c: float, years=PROJECTION_YEARS, model=None) -> pd.DataFrame:
    """Capacity after ``years`` of the observed duty by the ageing model: calendar loss at the mean SoC plus cycle
    loss from the rainflow equivalent cycles, both at the cell temperature ``temp_c`` (an assumption)."""
    from bess_augment.aging import AgingModel, profile_stress

    model = model or AgingModel()
    stress = profile_stress(soc, dt_hours)
    rows = []
    for y in years:
        cal = float(model.calendar_loss(365.25 * y, stress.mean_soc, temp_c))
        cyc = float(model.cycle_loss(stress.n_eq_per_year(model.beta) * y, temp_c))
        rows.append({"years": y, "calendar_loss": cal, "cycle_loss": cyc, "soh": 1.0 - cal - cyc})
    out = pd.DataFrame(rows).set_index("years")
    out.attrs.update(mean_soc=stress.mean_soc, fec_per_year=stress.fec_per_year, temp_c=temp_c)
    return out


def _flag(ok: pd.Series, valid: pd.Series) -> pd.Series:
    """Nullable boolean: the check result where the KPI exists, missing elsewhere."""
    return ok.where(valid).astype("boolean")


def _compliance(monthly: pd.DataFrame, guarantees: dict) -> pd.DataFrame:
    c = pd.DataFrame(index=monthly.index)
    if guarantees.get("availability") is not None and monthly["availability"].notna().any():
        c["availability_ok"] = _flag(monthly["availability"] >= guarantees["availability"],
                                     monthly["availability"].notna())
    if guarantees.get("rte") is not None and monthly["rte"].notna().any():
        c["rte_ok"] = _flag(monthly["rte"] >= guarantees["rte"], monthly["rte"].notna())
    if guarantees.get("efc_per_year") is not None:
        days = pd.Series(pd.PeriodIndex(monthly.index, freq="M").days_in_month, index=monthly.index)
        c["cycles_ok"] = _flag(monthly["efc"] * 365.0 / days <= guarantees["efc_per_year"], monthly["efc"].notna())
    return c


def _summary(monthly: pd.DataFrame, compliance: pd.DataFrame) -> dict:
    days = pd.PeriodIndex(monthly.index, freq="M").days_in_month.to_numpy()
    w = pd.Series(days, index=monthly.index)
    out = {"months": int(len(monthly))}
    for col in ("availability", "availability_offered"):
        if col in monthly and monthly[col].notna().any():
            ok = monthly[col].notna()
            out[col] = float((monthly[col][ok] * w[ok]).sum() / w[ok].sum())
            out[f"{col}_min_month"] = float(monthly[col][ok].min())
    if monthly["e_in_mwh"].notna().any():
        out["e_in_mwh"] = float(monthly["e_in_mwh"].sum())
        out["e_out_mwh"] = float(monthly["e_out_mwh"].sum())
    out["rte"] = float(monthly["rte"].mean()) if monthly["rte"].notna().any() else float("nan")
    out["rte_min_month"] = float(monthly["rte"].min())
    out["rte_max_month"] = float(monthly["rte"].max())
    out["efc_per_year"] = float(monthly["efc"].sum() * 365.0 / w.sum())
    out["mean_soc"] = float(monthly["mean_soc"].mean())
    if "technical_outage_hours" in monthly and monthly["technical_outage_hours"].notna().any():
        out["technical_outage_hours_per_year"] = float(monthly["technical_outage_hours"].sum() * 365.0 / w.sum())
    for col in compliance:
        ok = compliance[col].dropna()
        out[f"{col}_months"] = int(ok.sum())
        out[f"{col}_assessed"] = int(len(ok))
    return out


def from_nem(cache, duid: str, guarantees: dict | None = None, cell_temp_c: float = 25.0,
             model=None) -> TechnicalReport:
    """Technical report of one NEM battery from a ``bess_ops.nem.Cache`` (see ``nemslice.load_slice``)."""
    from bess_ops.nem import NEM_TZ, battery_table, unit_benchmark, unit_site

    guarantees = guarantees or {}
    m, s, daily = unit_benchmark(cache, duid)
    info = battery_table(cache).loc[duid]
    monthly = pd.DataFrame(index=m.index)
    technical = "availability_technical" in m
    monthly["availability"] = m["availability_technical"] if technical else np.nan
    monthly["availability_offered"] = m["availability_capacity"]
    monthly["rte"], monthly["rte_excl_aux"] = m["rte"], np.nan
    monthly["aux_mwh"] = np.nan
    monthly["e_in_mwh"], monthly["e_out_mwh"], monthly["efc"] = m["e_in_mwh"], m["e_out_mwh"], m["efc"]
    monthly["mean_soc"], monthly["usable_energy_mwh"] = m["mean_soc"], m["e_p995_mwh"]
    monthly["technical_outage_hours"] = m["technical_outage_hours"] if technical else np.nan
    monthly["violations"] = np.nan
    monthly.index.name = "month"
    comp = _compliance(monthly, guarantees)
    summary = _summary(monthly, comp)
    summary.update({"duid": duid, "name": str(info["name"]).strip(), "mw": float(info["mw"]), "mwh": float(info["mwh"]),
                    "usable_energy_trend_pct_per_year": float(s.get("e_max_trend_pct_per_yr", np.nan)),
                    "rte_daily_median": float(s["rte_daily_median"]), "valid_days": int(s["valid_days"]),
                    "withheld_share": float(m["withheld_share"].mean()) if "withheld_share" in m else float("nan"),
                    "stored_jumps_per_month": float(s["jumps_per_month"])})
    soh = None
    notes = ["Market data: RTE is at the SCADA point (auxiliaries behind the meter are invisible), availability is "
             "the physical availability the operator declared with its bids (PASA), not a measurement.",
             "Usable energy follows the BMS window, so a falling capacity does not show in it directly; the ageing "
             "model projection is a model, not a measurement."]
    try:
        site = unit_site(cache, duid)
        usable = float(monthly["usable_energy_mwh"].max())
        soc = (site["e_stored"] / usable).to_numpy()
        soh = soh_projection(soc, 5 / 60, cell_temp_c, model=model)
        soh.attrs["usable_energy_mwh"] = usable
        summary["soh_temp_c"] = float(cell_temp_c)
        summary["soh_year1"] = float(soh.loc[1, "soh"])
        summary["soh_year10"] = float(soh.loc[10, "soh"])
        summary["model_fec_per_year"] = float(soh.attrs["fec_per_year"])
    except ImportError:
        notes.append("State of health projection skipped: install the 'degradation' extra (bess-capacity-augmentation).")
    return TechnicalReport(summary["name"], "nem", monthly, summary, comp, soh, notes,
                           {"daily_rte": daily, "nem_tz": NEM_TZ, "registered_mw": float(info["mw"]),
                            "registered_mwh": float(info["mwh"]), "full_monthly": m}, guarantees)


def analyse_ems(input_path: Path, mapping: Path, site: Path, warranty: Path | None, ltsa: Path | None,
                events: Path | None) -> dict:
    """The bess-ops-warranty analysis of a long EMS table with its YAML files; returns its result dictionary."""
    from bess_ops.availability import read_events
    from bess_ops.config import load_ltsa, load_site, load_warranty
    from bess_ops.pipeline import analyse
    from bess_ops.schema import load_mapping, read_table, to_site_frame

    m = load_mapping(mapping)
    sc = load_site(site)
    frame = to_site_frame(read_table(input_path), m)
    ev = read_events(events, sc["timezone"])
    return analyse(frame, sc, load_warranty(warranty, sc), load_ltsa(ltsa, sc), ev)


def from_ems(res: dict, guarantees: dict | None = None, cell_temp_c: float | None = None, model=None) -> TechnicalReport:
    """Technical report from the result dictionary of ``bess_ops.pipeline.analyse``; the guarantees default to the
    LTSA of the analysis."""
    k = res["monthly"]
    lt = res["ltsa"]
    guarantees = {"availability": lt["availability"]["guaranteed"], "rte": lt["rte"]["guaranteed"],
                  "efc_per_year": res["warranty"]["throughput"]["efc_per_year"], **(guarantees or {})}
    monthly = pd.DataFrame(index=k.index)
    monthly["availability"] = k["availability"] if "availability" in k else np.nan
    monthly["availability_offered"] = np.nan
    monthly["rte"] = k["rte"] if lt["rte"]["definition"] == "incl_aux" else k["rte_excl_aux"]
    monthly["rte_excl_aux"] = k["rte_excl_aux"]
    monthly["aux_mwh"], monthly["e_in_mwh"], monthly["e_out_mwh"] = k["e_aux_mwh"], k["e_in_mwh"], k["e_out_mwh"]
    monthly["efc"], monthly["mean_soc"] = k["efc"], k["mean_soc"] if "mean_soc" in k else np.nan
    monthly["usable_energy_mwh"] = np.nan
    monthly["technical_outage_hours"] = np.nan
    monthly["violations"] = k["violations"]
    monthly.index.name = "month"
    comp = _compliance(monthly, guarantees)
    summary = _summary(monthly, comp)
    summary["violations"] = int(monthly["violations"].sum())
    summary["aux_share_of_import"] = float(monthly["aux_mwh"].sum() / monthly["e_in_mwh"].sum())
    ld = res["ld"]
    summary["ld_total_illustrative"] = float(ld["capped_total"].sum()) if len(ld) else 0.0
    summary["ld_currency"] = str(ld["currency"].iloc[0]) if len(ld) else ""
    notes = ["All contract terms are illustrative placeholders of the example files, not a reading of any contract."]
    soh = None
    fc = res.get("forecast")
    if fc is not None:
        soh = fc if isinstance(fc, pd.DataFrame) else None
    if "soc" in res["site"] or "e_stored" in res["site"]:
        try:
            from bess_ops.pipeline import soc_series
            soc = soc_series(res["site"], res["site_cfg"]).to_numpy()
            temp = cell_temp_c if cell_temp_c is not None else float(
                res["site"]["t_cell_avg"].mean()) if "t_cell_avg" in res["site"] else 25.0
            proj = soh_projection(soc, res["site"].attrs["dt_h"], temp, model=model)
            summary["soh_year1"], summary["soh_year10"] = float(proj.loc[1, "soh"]), float(proj.loc[10, "soh"])
            soh = proj
        except ImportError:
            notes.append("State of health projection skipped: install the 'degradation' extra.")
    return TechnicalReport(str(res["site_cfg"].get("name", "EMS battery")), "ems", monthly, summary, comp, soh, notes,
                           {"result": res}, guarantees)
