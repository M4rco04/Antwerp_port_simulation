"""Calibrate the Zeeschelde currents (currents.py) on the Flemish current atlas.

AIS speeds over ground pin the current down poorly in the Zeeschelde (R2 ~0.1), and with the AIS
scale (~0.5) the model gave about 1 kn where real currents run 2-3 kn. The Stroomatlas Zeeschelde
of Flanders Hydraulics Research (Chu, Vanlede & Verwilligen 2022, WL rapporten 18_085_1; SCALDIS
model; depth-averaged speeds every half hour for a typical spring, mean and neap tide, timed on
high water at Antwerp) gives the speeds instead. data/tides/zeeschelde_stroomatlas.csv holds, per
atlas map, the 95th percentile of the speeds labelled on its vectors: the fairway, where ships sail.

The model current is

    u = scale(s) * (u_graph + storage * u_head(lag)) + u_river

with scale(s) a profile along the chainage s (currents.scale_profile): the Western Scheldt (AIS)
scale up to Bath, a ramp to the first atlas section, then one scale per atlas section with
TRANSITION_KM between them. The scales correct the graph's cross-sections, which get narrower and
less exact up the river, and turn the cross-section mean into the fairway speed. The scales, the
tidal storage above the head of the graph (Upper Sea Scheldt, Rupel, Durme, Nete; kept within
STORAGE_KM2, the area of that water) and the lag of
its filling behind the head (the tide reaches Temse and the Rupel later) are fitted by least squares
on |u| (section mean) against the atlas, for spring and neap tides of the model's own tide (tidal
coefficient at Antwerp: spring 1.12, neap 0.84 as in the atlas), timed on its high waters at Antwerp.
Then rerun fit_currents.py: it keeps these values, refits the Western Scheldt scale on AIS and
measures how much of the current ships' speed over ground shows (sog_response).

Usage:
    py src/environment/fit_currents_atlas.py
"""

from __future__ import annotations

import json
import logging
import pickle

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

import currents as C
from antwerp_port import DEFAULT_OUTPUT, PROJECT_ROOT
from tide import TideModel

ATLAS_FILE = PROJECT_ROOT / "data" / "tides" / "zeeschelde_stroomatlas.csv"
# atlas sections inside the graph: chainage (km along the estuary axis) of their ends
SECTIONS_KM = {"prosperpolder_boudewijnsluis": (63.4, 74.4), "boudewijnsluis_antwerpen": (74.4, 85.4),
               "antwerpen_hoboken": (85.4, 93.0)}
WESTERN_SCHELDT_TO_KM = 58.0            # Bath: the AIS scale holds up to here
TRANSITION_KM = 2.0
GAUGE = "antwerpen.loodsgebouw"
COEFFICIENT = {"spring": (1.06, 1.20), "neap": (0.76, 0.92)}   # tides of each kind (atlas: 1.12 / 0.84)
PERIOD = ("2026-01-01", "2026-04-01")
LAGS_MIN = range(0, 181, 15)
# The storage and the scales trade off (more storage, smaller scales fit the atlas nearly as well),
# so the storage is kept within what the tidal water above Hoboken can hold: Hoboken-Rupelmonde
# ~6 km2, Rupelmonde-Dendermonde ~6, Dendermonde-Ghent ~4, Rupel/Nete/Dijle/Zenne/Durme ~5.
STORAGE_KM2 = (5.0, 25.0)
log = logging.getLogger("fit_currents_atlas")


def profile(scales):
    """scale_profile knots for one scale per atlas section."""
    names = list(SECTIONS_KM)
    km, val = [WESTERN_SCHELDT_TO_KM], ["western_scheldt"]
    for i, name in enumerate(names):
        a, b = SECTIONS_KM[name]
        km += [a + (TRANSITION_KM / 2 if i else 0.0), b - (TRANSITION_KM / 2 if i < len(names) - 1 else 0.0)]
        val += [scales[i], scales[i]]
    return {"km": km, "scale": val}


def tide_profiles(model, tide):
    """Mean model components (u_graph, u_head, u_river), each per slice, per tide kind and atlas hour."""
    times = pd.date_range(*PERIOD, freq="10min", tz="UTC")
    _, (ug, uh, ur) = model.compute(times, components=True)
    h = tide.levels(times)[GAUGE].to_numpy()
    peaks = np.flatnonzero((h[1:-1] > h[:-2]) & (h[1:-1] >= h[2:])) + 1
    hws, ranges = [], []
    for p in peaks:                                          # high waters at Antwerp, range from the LW before
        lo = h[max(p - 48, 0):p].min()
        if h[p] - lo > 2.0:
            hws.append(p)
            ranges.append(h[p] - lo)
    ranges = np.array(ranges)
    coef = ranges / ranges.mean()
    hours = [x for x in np.arange(-6.0, 7.0, 0.5) if x != 0.0]
    out = {}
    for kind, (lo, hi) in COEFFICIENT.items():
        sel = [p for p, c in zip(hws, coef) if lo <= c <= hi]
        for hr in hours:
            idx = np.array([p + int(round(hr * 6)) for p in sel])
            idx = idx[(idx >= 0) & (idx < len(times))]
            out[(kind, hr)] = np.stack([x[idx].mean(axis=0) for x in (ug, uh, ur)])
    return out


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    graph = pickle.load(open(DEFAULT_OUTPUT, "rb"))["graph"]
    tide = TideModel.load()
    cal = C.load_calibration()
    atlas = pd.read_csv(ATLAS_FILE)
    atlas = atlas[atlas.section.isin(SECTIONS_KM)].reset_index(drop=True)
    obs = atlas.speed_p95_ms.to_numpy()
    rmse = lambda p: float(np.sqrt(np.mean((p - obs) ** 2)))
    names = list(SECTIONS_KM)
    best, before = None, None
    for lag in sorted(set(LAGS_MIN) | {cal.get("upstream_lag_min", 0.0)}):
        model = C.CurrentModel(graph, tide, calibration=dict(cal, scale=1.0, upstream_storage_m2=0.0,
                                                               upstream_lag_min=lag))
        km = model.slice_km
        prof = tide_profiles(model, tide)
        cols = {n: np.flatnonzero((km >= a) & (km < b)) for n, (a, b) in SECTIONS_KM.items()}

        def predict(scales, storage, c=None):
            c = c or dict(cal, scale_profile=profile(scales))
            k = C.scale_profile(km, c)
            if k is None:
                k = np.where(model.reach == "western_scheldt", c["scale"]["western_scheldt"], c["scale"]["zeeschelde"])
            out = []
            for r in atlas.itertuples():
                g, hh, rv = prof[(r.tide, r.hours_from_hw_antwerp)][:, cols[r.section]]
                out.append(abs(float(np.mean(k[cols[r.section]] * (g + storage * hh) + rv))))
            return np.array(out)

        fit = least_squares(lambda p: predict(p[:3], p[3] * 1e6) - obs, x0=[1.5, 1.5, 1.5, 15.0],
                            bounds=([0.2, 0.2, 0.2, STORAGE_KM2[0]], [6.0, 6.0, 6.0, STORAGE_KM2[1]]))
        e = rmse(predict(fit.x[:3], fit.x[3] * 1e6))
        log.info("lag %3d min: scales %s, storage %.1f km2, RMSE %.3f m/s", lag, np.round(fit.x[:3], 2), fit.x[3], e)
        if lag == cal.get("upstream_lag_min", 0.0) and before is None:
            before = predict(None, cal["upstream_storage_m2"], c=cal)
        if best is None or e < best[0]:
            best = (e, lag, fit.x, predict(fit.x[:3], fit.x[3] * 1e6))
    e, lag, x, pred = best
    log.info("best: lag %d min, scales %s, storage %.1f km2; RMSE %.2f m/s (calibration before: %.2f)",
             lag, dict(zip(names, np.round(x[:3], 3))), x[3], e, rmse(before))
    df = atlas.assign(model=pred, before=before)
    df["phase"] = np.where((df.hours_from_hw_antwerp > -5.0) & (df.hours_from_hw_antwerp <= 1.0), "flood", "ebb")
    summary = df.groupby(["section", "tide", "phase"])[["speed_p95_ms", "model", "before"]].max().round(2)
    log.info("peak speeds (m/s):\n%s", summary.to_string())
    cal["scale_profile"] = profile([round(float(v), 3) for v in x[:3]])
    cal["scale"]["zeeschelde"] = round(float(np.mean(x[:3])), 3)     # (used only without the profile)
    cal["upstream_storage_m2"] = round(float(x[3]) * 1e6, -5)
    cal["upstream_lag_min"] = float(lag)
    cal["zeeschelde_source"] = {
        "atlas": "Stroomatlas Zeeschelde, WL rapporten 18_085_1 (2022), 95th percentile of the vector speeds",
        "points": len(obs), "rmse_ms": round(e, 3), "rmse_before_ms": round(rmse(before), 3),
        "peaks_ms": {f"{s}/{t}/{p}": {"atlas": float(r.speed_p95_ms), "model": float(r.model)}
                     for (s, t, p), r in summary.iterrows()}}
    C.CALIBRATION_FILE.write_text(json.dumps(cal, indent=2))
    log.info("wrote %s; now rerun fit_currents.py (Western Scheldt scale, SOG response)", C.CALIBRATION_FILE)


if __name__ == "__main__":
    main()
