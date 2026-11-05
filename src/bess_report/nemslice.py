"""Cut one battery out of the NEM caches into a small committed slice, and read the slice back.

The NEM data are AEMO's public MMS tables (5-minute SCADA and dispatch, registration, bids). The full caches are
large, so the repository keeps only the rows of one example battery; the slice has the same layout as the cache of
``bess_ops.nem`` and is read with the same code.

Usage:
    python -m bess_report prepare-nem --nem-data-dir ../nem-battery-behaviour/data \
        --nem-extra-dir ../bess-ops-warranty/data/nem_extra --duid RANGEB1 --out data/example/nem
    cache = load_slice(Path("data/example/nem"))
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)
FILES = ("registry", "stations", "scada", "dispatch", "extra_dispatchload", "extra_bids")


def cut(nem_dir: Path, extra_dir: Path, duid: str, out: Path) -> dict:
    """Write the rows of ``duid`` from the cache (``nem_dir``) and from the fetch-nem tables (``extra_dir``)."""
    from bess_ops.nem import load_cache, load_extra

    cache = load_cache(nem_dir)
    extra = load_extra(extra_dir)
    out.mkdir(parents=True, exist_ok=True)
    frames = {
        "registry": cache.registry[cache.registry["DUID"] == duid],
        "scada": cache.scada[cache.scada["DUID"] == duid],
        "dispatch": cache.dispatch[cache.dispatch["DUID"] == duid],
        "extra_dispatchload": extra["dispatchload"][extra["dispatchload"]["DUID"] == duid],
        "extra_bids": extra["bids"][extra["bids"]["DUID"] == duid],
    }
    station = frames["registry"]["STATIONID"].iloc[-1]
    if cache.stations is not None:
        frames["stations"] = cache.stations[cache.stations["STATIONID"] == station]
    else:
        frames["stations"] = pd.DataFrame({"STATIONID": [station], "STATIONNAME": [duid]})
    sizes = {}
    for name, df in frames.items():
        path = out / f"{name}.parquet"
        df.reset_index(drop=True).to_parquet(path, compression="zstd", index=False)
        sizes[name] = (len(df), path.stat().st_size)
        log.info("%s: %d rows, %.0f kB", name, *(sizes[name][0], sizes[name][1] / 1e3))
    return sizes


def load_slice(path: Path):
    """The slice as a ``bess_ops.nem.Cache``."""
    from bess_ops.nem import Cache

    path = Path(path)
    missing = [f for f in FILES if not (path / f"{f}.parquet").exists()]
    if missing:
        raise FileNotFoundError(f"NEM slice incomplete in {path}: missing {missing}")
    rd = {f: pd.read_parquet(path / f"{f}.parquet") for f in FILES}
    return Cache(rd["registry"], rd["stations"], rd["scada"], rd["dispatch"],
                 extra={"dispatchload": rd["extra_dispatchload"], "bids": rd["extra_bids"]})
