"""Calibrate the current model (currents.py) on AIS speeds over the ground.

A ship sailing up or down the estuary goes faster over the ground with the current than against
it. Within one visit (one ship, one passage) its speed through the water hardly changes, so
regressing each visit's speed over ground on the modelled along-track current gives

    SOG = visit's own speed + scale(reach) * u_graph * direction + u_river

(u_graph: the current from the tidal storage inside the graph), one scale for the Western Scheldt
and one for the Zeeschelde.
The fit uses moving ships (>= MIN_SOG_KN) within MAX_OFF_AXIS_M of the estuary axis whose course
is within COURSE_TOLERANCE of the axis, and the tide + surge for the AIS period (KNMI weather).
Writes data/tides/current_calibration.json.

Usage:
    py src/environment/fit_currents.py --plot currents.png
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import LineString

import currents as C
import fit_tide
from antwerp_port import DEFAULT_OUTPUT, PROJECT_ROOT, TO_UTM, _tangents
from tide import TideModel

MIN_SOG_KN = 4.0
MAX_OFF_AXIS_M = 1500.0
COURSE_TOLERANCE = 0.85          # |cos(course - axis)| at least this: sailing up or down river
MIN_FIXES_PER_VISIT = 6
# speed changes bigger than this within a passage are manoeuvres (pilot, berthing), not current
MAX_ANOMALY_KN = 4.0

log = logging.getLogger("currents")


def ais_fixes(axis):
    """AIS fixes of moving ships along the estuary, with chainage and direction (+1 up, -1 down)."""
    sys.path.insert(0, str(PROJECT_ROOT / "src" / "data"))
    import ais_pipeline

    data = ais_pipeline.prepare()
    df = data.df[(data.df.sog >= MIN_SOG_KN) & data.df.cog.notna() & (data.df.lon > 3.55)].copy()
    x, y = TO_UTM(df.lon.to_numpy(), df.lat.to_numpy())
    pts = shapely.points(x, y)
    near = shapely.distance(axis, pts) < MAX_OFF_AXIS_M
    df, pts = df[near], pts[near]
    s = shapely.line_locate_point(axis, pts)
    t = _tangents(axis, s, h=200.0)
    course = np.radians(df.cog.to_numpy())
    cos = np.sin(course) * t[:, 0] + np.cos(course) * t[:, 1]        # cog is clockwise from north
    df["chainage_m"], df["direction"] = s, np.sign(cos)
    df = df[(np.abs(cos) >= COURSE_TOLERANCE) & (s > 0) & (s < axis.length)]
    df["sog_ms"] = df.sog * C.KNOT
    counts = df.groupby("visit").visit.transform("size")
    return df[counts >= MIN_FIXES_PER_VISIT]


def within_visit(df, cols):
    return df[cols] - df.groupby("visit")[cols].transform("mean")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plot", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    graph = pickle.load(open(DEFAULT_OUTPUT, "rb"))["graph"]
    tide = TideModel.load()
    axis = LineString(graph.graph["estuary_axis"])
    fixes = ais_fixes(axis)
    log.info("%d AIS fixes of %d passages along the estuary", len(fixes), fixes.visit.nunique())

    weather = fit_tide.load_weather()
    times = pd.date_range(fixes.t.min().floor("5min") - pd.Timedelta("10min"), fixes.t.max().ceil("5min") + pd.Timedelta("10min"),
                          freq="5min")
    model = C.CurrentModel(graph, tide, calibration=dict(C.DEFAULTS, scale=1.0, upstream_storage_m2=0.0))
    fixes["reach"] = model.reach[np.clip((fixes.chainage_m // model.slice_m).astype(int), 0, model.n_slices - 1)]
    field, (u_graph, u_head, u_river) = model.compute(times, weather, components=True)
    i = np.clip(times.searchsorted(fixes.t), 0, len(times) - 1)
    j = np.clip((fixes.chainage_m // model.slice_m).astype(int), 0, model.n_slices - 1).to_numpy()
    fixes["x_graph"] = u_graph[i, j] * fixes.direction
    fixes["x_head"] = u_head[i, j] * fixes.direction
    fixes["y"] = fixes.sog_ms - u_river[i, j] * fixes.direction
    d = within_visit(fixes, ["y", "x_graph", "x_head"])
    keep = (d.y.abs() <= MAX_ANOMALY_KN * C.KNOT).to_numpy()
    fixes, d = fixes[keep], d[keep]
    # one scale per reach. The storage above Antwerp is not fitted: its current follows dh/dt at the
    # head just like the in-graph part, so the two cannot be told apart and trade off (tried: the
    # Zeeschelde scale then drops to ~0.5 with ~12 km2 of storage). It stays at currents.UPSTREAM_STORAGE_M2.
    storage = C.DEFAULTS["upstream_storage_m2"]           # fixed at the physical estimate
    ws = (fixes.reach == "western_scheldt").to_numpy()
    X = np.column_stack([d.x_graph * ws, (d.x_graph + storage * d.x_head) * ~ws])
    beta, *_ = np.linalg.lstsq(X, d.y.to_numpy(), rcond=None)
    k_ws, k_zs = float(beta[0]), float(beta[1])
    k = np.where(ws, k_ws, k_zs)
    pred = k * (d.x_graph + storage * d.x_head)
    r2 = 1 - np.var(d.y - pred) / np.var(d.y)
    reach = {name: {"fixes": int(m.sum()), "r2": round(float(1 - np.var((d.y - pred)[m]) / np.var(d.y[m])), 3)}
             for name, m in (("western_scheldt", ws), ("zeeschelde", ~ws))}
    scale = {"western_scheldt": round(k_ws, 3), "zeeschelde": round(k_zs, 3)}
    cal = {"scale": scale, "upstream_storage_m2": round(storage, -4),
           "river_discharge_m3s": C.DEFAULTS["river_discharge_m3s"],
           "fit": {"fixes": len(fixes), "passages": int(fixes.visit.nunique()), "r2_within_passage": round(float(r2), 3),
                   "per_reach_scale": reach, "period": [str(fixes.t.min()), str(fixes.t.max())]}}
    C.CALIBRATION_FILE.write_text(json.dumps(cal, indent=2))
    log.info("scale %s, upstream storage %.1f km2, R2 within passages %.2f; per reach %s", scale, storage / 1e6, r2, reach)
    log.info("Saved %s", C.CALIBRATION_FILE)

    if args.plot:
        plot(args.plot, graph, tide, fixes, d, k, storage, cal)


def plot(path, graph, tide, fixes, d, scale, storage, cal):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(20, 12))
    ax = axes[0, 0]
    x = scale * (d.x_graph + storage * d.x_head) / C.KNOT
    ax.hexbin(x, d.y / C.KNOT, gridsize=60, cmap="Blues", mincnt=1)
    lim = np.nanpercentile(np.abs(x), 99)
    ax.plot([-lim, lim], [-lim, lim], "r--", lw=1, label="1:1")
    ax.set_xlabel("modelled current along the ship's track (kn), within-passage anomaly")
    ax.set_ylabel("ship's speed over ground (kn), within-passage anomaly")
    ax.set_title(f"AIS check: {cal['fit']['passages']} passages, R² = {cal['fit']['r2_within_passage']}", loc="left"); ax.legend()
    model = C.CurrentModel(graph, tide)
    times = pd.date_range("2026-11-09", "2026-11-10 06:00", freq="5min", tz="UTC")
    field = model.compute(times)
    ax = axes[0, 1]
    for km, label in ((5, "Vlissingen"), (25, "Terneuzen"), (45, "Hansweert"), (62, "Bath"), (80, "Liefkenshoek"), (92, "Antwerp")):
        if km * 1000 < model.n_slices * model.slice_m:
            ax.plot(times, field.at(km * 1000, slice(None)) / C.KNOT, lw=1, label=f"{label} (km {km})")
    ax.axhline(0, c="k", lw=.6); ax.set_ylabel("current, kn (+ flood / upstream)"); ax.legend(fontsize=8)
    ax.set_title("Modelled current at spring tide, 9-10 Nov 2026", loc="left"); ax.grid(lw=.3)
    ax = axes[1, 0]
    times = pd.date_range("2026-11-01", "2026-11-15", freq="10min", tz="UTC")
    field = model.compute(times)
    km = np.arange(model.n_slices) * model.slice_m / 1000
    ax.plot(km, field.u.max(axis=0) / C.KNOT, c="#d62728", label="strongest flood")
    ax.plot(km, -field.u.min(axis=0) / C.KNOT, c="#1f77b4", label="strongest ebb")
    ax.set_xlabel("km along the estuary from the mouth"); ax.set_ylabel("kn"); ax.legend(); ax.grid(lw=.3)
    ax.set_title("Peak currents along the estuary, 1-15 Nov 2026", loc="left")
    ax = axes[1, 1]
    span = fixes.groupby("visit").t.agg(lambda t: (t.max() - t.min()).total_seconds() / 3600)
    big = fixes[(fixes.length >= 150) & fixes.visit.map(span).between(2, 10)]
    one = big[big.visit == big.groupby("visit").size().idxmax()].sort_values("t")
    ax.plot(one.t, one.sog, "k.-", label=f"SOG of {one.mmsi.iloc[0]}")
    times = pd.date_range(one.t.min().floor("5min"), one.t.max().ceil("5min"), freq="5min")
    f = model.compute(times, fit_tide.load_weather())
    i = np.clip(times.searchsorted(one.t), 0, len(times) - 1)
    cur = f.at(one.chainage_m.to_numpy(), i) * one.direction.to_numpy() / C.KNOT
    ax2 = ax.twinx(); ax2.plot(one.t, cur, c="#d62728", label="modelled current along track"); ax2.set_ylabel("kn")
    ax.set_ylabel("kn"); ax.legend(loc="upper left"); ax2.legend(loc="upper right"); ax.grid(lw=.3)
    ax.set_title("One passage: speed over ground and the current it met", loc="left")
    fig.tight_layout(); fig.savefig(path, dpi=80)
    log.info("Saved %s", path)


if __name__ == "__main__":
    main()
