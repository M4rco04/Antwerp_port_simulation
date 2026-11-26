"""Calibrate and check the sea-going ships' fuel (src/sim/emissions.py) on the EU MRV reports (MODEL.md §17.1).

The sea-going ships of the AIS record (container, bulk / general cargo, tanker, with an IMO number, seen east of
Vlissingen) are matched by IMO number to the MRV reports of a year (ecology/*EU MRV Publication of information.xlsx,
full reports, at least 500 h at sea). For each, the model's fuel an hour at sea at the ship's mean speed at sea
(distance over hours at sea, from MRV's fuel, fuel per mile and hours at sea; draught and dimensions from the AIS)
is set against MRV's: all fuel less what was burnt in EU ports, over the hours at sea (fuel in ports outside the EU
stays in it).

    ratio = model fuel an hour at sea / MRV fuel an hour at sea

emissions.ME_POWER_FACTOR, a factor on the main engine's power, is set so that the median ratio of the calibration
year is 1, and the other years are checked with it (held out). The factor is printed, not written: put it into
emissions.py by hand with the numbers of the check.

Usage:
    py src/data/fit_mrv_calibration.py --fit 2024 --check 2025
"""
from __future__ import annotations

import argparse
import logging
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
for d in ("sim", "agents", "environment", "data"):
    if str(ROOT / "src" / d) not in sys.path:
        sys.path.insert(0, str(ROOT / "src" / d))
import ais_pipeline as AP  # noqa: E402
import emissions as E  # noqa: E402
from ship import Ship  # noqa: E402

log = logging.getLogger("mrv")
ECOLOGY = ROOT / "ecology"
CACHE = ROOT / "cache"
SEA = ("container", "bulk_general", "tanker")
VLISSINGEN_LON = 3.57
MIN_SEA_H = 500.0
COLS = {"IMO Number": "imo", "Ship type": "mrv_type", "Total fuel consumption [m tonnes]": "fuel_t",
        "Total CO₂ emissions [m tonnes]": "co2_t", "Total CO₂eq emissions [m tonnes]": "co2eq_t",
        "CO₂ emissions which occurred within ports under a MS jurisdiction [m tonnes]": "co2_port_t",
        "Time spent at sea [hours]": "sea_h", "Fuel consumption per distance [kg / n mile]": "kg_nm"}


def mrv(year):
    """One year's reports (full ones first), one row per IMO number."""
    cache = CACHE / f"mrv_{year}.pkl"
    if cache.is_file():
        return pd.read_pickle(cache)
    path = next(ECOLOGY.glob(f"{year}-*EU MRV*.xlsx"))
    parts = []
    for sheet in (f"{year} Full ERs", f"{year} Partial ERs"):
        d = pd.read_excel(path, sheet_name=sheet, header=2, engine="openpyxl")
        d = d.loc[:, ~d.columns.duplicated()].rename(columns=COLS)
        d = d[[c for c in COLS.values() if c in d]].copy()
        d["report"] = sheet.split()[1]
        parts.append(d)
    m = pd.concat(parts, ignore_index=True)
    for c in m.columns:
        if c not in ("mrv_type", "report"):
            m[c] = pd.to_numeric(m[c], errors="coerce")
    m = m.dropna(subset=["imo"]).sort_values("report").drop_duplicates("imo")
    m["imo"] = m.imo.astype(int)
    m.to_pickle(cache)
    return m


def ais_ships():
    """The sea-going ships of the AIS record with an IMO number that came into the Scheldt."""
    cache = CACHE / "ais_sea_going_static.pkl"
    if cache.is_file():
        return pd.read_pickle(cache)
    df, _, _ = AP.load_snapshots(AP.AIS_DIR)
    st = AP.static_per_ship(df)
    st["lon_max"] = df.groupby("mmsi").lon.max()
    names = set(pd.read_csv(AP.SCHEDULE, sep=";").Vessel.map(AP.normalise_name))
    st["cls"] = [AP.classify(r, names) for r in st.itertuples()]
    st = st[st.imo.map(AP.valid_imo) & (st.lon_max > VLISSINGEN_LON) & st.cls.isin(SEA)].copy()
    st["imo"] = st.imo.astype(float).astype(int)
    st = st.reset_index()
    st.to_pickle(cache)
    return st


def matched(year, ships):
    j = ships.merge(mrv(year), on="imo", how="inner")
    j = j[(j.report == "Full") & (j.fuel_t > 0) & (j.sea_h > MIN_SEA_H) & (j.length > 0) & (j.width > 0)].copy()
    j["T"] = j.draught_median.fillna(j.draught)
    j["v"] = j.fuel_t * 1000 / j.kg_nm / j.sea_h
    j["t_h"] = j.fuel_t * (1 - (j.co2_port_t / j.co2_t).fillna(0)) / j.sea_h
    return j[np.isfinite(j.v) & (j.v > 3) & (j.v < 30) & np.isfinite(j["T"]) & (j.t_h > 0)].reset_index(drop=True)


def model_t_h(j):
    """The model's fuel an hour at sea (t) of each matched ship at its MRV mean speed."""
    out = np.empty(len(j))
    for i, r in enumerate(j.itertuples()):
        sh = Ship(id=str(r.imo), cls=r.cls, loa=float(r.length), beam=float(r.width), draught=float(r.T), level=2,
                  source="s", destination="d", spawn_t=0.0)
        p = E.Profile(sh)
        me = E.admiralty_kw(p, r.v, r.T)
        ae, boiler = p.aux_kw("sea")
        out[i] = (me * E.sfc_main(p, me / p.mcr) + ae * E.SFC_BASE["AE"] + boiler * E.SFC_BASE["boiler"]) / 1e6
    return out


def ratios(j, factor):
    E.ME_POWER_FACTOR = factor
    return model_t_h(j) / j.t_h.to_numpy()


def fit(j, lo=0.5, hi=2.0, tol=1e-4):
    """The factor that makes the median ratio 1 (the median rises with the factor)."""
    while hi - lo > tol:
        mid = (lo + hi) / 2
        if np.median(ratios(j, mid)) < 1.0:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 3)


def report(name, j, r):
    g = pd.DataFrame({"cls": j.cls, "r": r}).groupby("cls").r
    by = {c: f"{v:.3f}" for c, v in g.median().items()}
    lr = np.log(r)
    log.info("%s: %d ships, median %.3f (by class %s), fuel-weighted %.3f, log-sd %.2f", name, len(j), np.median(r),
             by, float((r * j.t_h).sum() / j.t_h.sum()), lr.std())


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fit", type=int, default=2024)
    p.add_argument("--check", type=int, nargs="*", default=[2025])
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    warnings.filterwarnings("ignore")
    ships = ais_ships()
    jf = matched(a.fit, ships)
    report(f"MRV {a.fit}, factor 1 (IHS fleet means)", jf, ratios(jf, 1.0))
    k = fit(jf)
    report(f"MRV {a.fit}, factor {k} (fitted)", jf, ratios(jf, k))
    for y in a.check:
        jc = matched(y, ships)
        report(f"MRV {y}, factor 1", jc, ratios(jc, 1.0))
        report(f"MRV {y}, factor {k} (held out)", jc, ratios(jc, k))
    print(f"ME_POWER_FACTOR = {k}")


if __name__ == "__main__":
    main()
