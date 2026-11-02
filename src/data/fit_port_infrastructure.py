"""Fit the port infrastructure the AIS shows (PLAN.md §6, §7): berth use, tug and pilot bases,
mooring and unmooring times.

    BERTH_USE        per charted berth (slots_cords LPL_UN): calls by ship class seen in the AIS
                     (a berth stop of >= 0.5 h within BERTH_MATCH_M of the berth polygon), and
                     whether it is a tanker berth (tankers are allowed only there, regs §10.5)
    TUG_BASES        where tugs lie between jobs: clusters of their stops, with hours and tugs seen
    PILOT_BASES      the same for pilot boats (Brabo, LRD tenders, "PILOT" in the name)
    MOORING_MIN      approach and departure manoeuvre time of sea-going ships at a berth,
                     t = base + k * LOA (+ lognormal noise), per berth area (tidal / behind a lock)
    PILOT_DEMAND     ships needing a pilot (sea-going, LOA > 80 m, under way) at the same moment, per
                     pilotage zone (sea: west of Vlissingen; river: Vlissingen to Antwerp; dock: in the
                     basins behind the locks), over the AIS snapshots: median, 95th, 99th percentile, max.
                     The pilot pools of the simulation are sized from it (data/equipment has no pilot count).
    DOCK_SPEED_KN    speed over ground of sea-going ships under way (>= 1 kn) per dock basin and
                     within LOCK_APPROACH_M of a lock: median, 95th percentile, fixes. No published
                     dock speed limit was found, so the graph takes the 95th percentile as the limit.
                     Needs the navigation graph (cache/antwerp_scheldt_graph.pkl) for the basins.

The manoeuvre is measured from the last AIS fix 1 km or more from the berth to the first fix
lying still (arrival), and from the last fix lying still to the first fix 1 km or more away
(departure), so it includes about 1 km of slow sailing; t_base absorbs it.

Tugs are the 42 harbour tugs of data/equipment/tugs.csv plus every other ship with AIS type 52.

The result is written as a plain Python module (default src/data/port_infrastructure.py).

Usage:
    py src/data/fit_port_infrastructure.py
"""
import argparse
import logging
import math
import warnings
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from ais_pipeline import BERTHS, PORT_ZONES, REPO_ROOT, SIMULATED_CLASSES, find_stops, prepare, to_km, write_module

log = logging.getLogger("infrastructure")

EQUIPMENT = REPO_ROOT / "data" / "equipment"
BERTH_MATCH_M = 150.0
TANKER_CLASSES = ("tanker", "inland_tanker")
TANKER_BERTH_MIN_CALLS = 2         # tanker or tank-barge calls
TANKER_BERTH_MIN_SHARE = 0.5
BASE_CLUSTER_M = 600.0              # stops closer than this belong to one base
BASE_MIN_HOURS = 50.0               # a base: at least this many vessel-hours over the data ...
BASE_MIN_VESSELS = 2                # ... by at least this many vessels
SEA_GOING = ("container", "bulk_general", "tanker", "passenger")
MANOEUVRE_DISTANCE_KM = 1.0
MANOEUVRE_MAX_MIN = 180.0           # longer: the ship waited on the way (lock, anchorage), not a manoeuvre
MAX_FIX_GAP_MIN = 15.0              # the fixes either side of the moment must be this close in time
TIDAL_ZONES = ("antwerp_river_quays", "antwerp_deurganckdok")
GRAPH = REPO_ROOT / "cache" / "antwerp_scheldt_graph.pkl"
UNDER_WAY_KN = 1.0
LOCK_APPROACH_M = 600.0
SNAP_MAX_M = 100.0


def load_berths():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        berths = gpd.read_file(BERTHS)
    number = pd.to_numeric(berths.LPL.str.extract(r"^[A-Z]?(\d+)")[0])
    berths["geom_km"] = [shapely.transform(g, lambda c: np.column_stack(to_km(c[:, 0], c[:, 1]))) for g in berths.geometry]
    berths["number"] = number
    return berths


def berth_use(stops, ships, berths):
    calls = stops[(stops.kind == "berth") & stops.mmsi.map(ships["class"]).isin(SIMULATED_CLASSES)].copy()
    calls["class"] = calls.mmsi.map(ships["class"])
    x, y = to_km(calls.lon.to_numpy(), calls.lat.to_numpy())
    tree = shapely.STRtree(berths.geom_km.values)
    pi, bi = tree.query_nearest(shapely.points(x, y), max_distance=BERTH_MATCH_M / 1000)
    calls = calls.iloc[pi].assign(berth=berths.LPL_UN.to_numpy()[bi])
    calls = calls.drop_duplicates(["visit", "berth", "start"])
    out = {}
    for berth, grp in calls.groupby("berth"):
        counts = {c: int(n) for c, n in grp["class"].value_counts().items()}
        n = sum(counts.values())
        tanker = sum(counts.get(c, 0) for c in TANKER_CLASSES)
        out[berth] = {"calls": counts, "max_loa_m": float(np.nanmax(grp.mmsi.map(ships.length))) if
                      grp.mmsi.map(ships.length).notna().any() else None,
                      "tanker_berth": bool(tanker >= TANKER_BERTH_MIN_CALLS and tanker / n >= TANKER_BERTH_MIN_SHARE)}
    log.info("%d berth calls matched to %d of %d charted berths; %d tanker berths", len(calls), len(out), len(berths),
             sum(v["tanker_berth"] for v in out.values()))
    return dict(sorted(out.items()))


def place_name(lon, lat):
    for name, (box, *_ ) in PORT_ZONES.items():
        if box[0] <= lon <= box[2] and box[1] <= lat <= box[3]:
            return name
    return "other"


def bases(stops, mmsis, label):
    """Clusters of the stops of these vessels (single linkage within BASE_CLUSTER_M)."""
    st = stops[stops.mmsi.isin(mmsis)].reset_index(drop=True)
    x, y = to_km(st.lon.to_numpy(), st.lat.to_numpy())
    pts = np.column_stack([x, y])
    parent = np.arange(len(st))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    tree = shapely.STRtree(shapely.points(x, y))
    a, b = tree.query(shapely.points(x, y), predicate="dwithin", distance=BASE_CLUSTER_M / 1000)
    for i, j in zip(a, b):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj
    st["cluster"] = [find(i) for i in range(len(st))]
    out = []
    for _, grp in st.groupby("cluster"):
        hours = float(grp.hours.sum())
        if hours < BASE_MIN_HOURS or grp.mmsi.nunique() < BASE_MIN_VESSELS:
            continue
        w = grp.hours.to_numpy()
        lon, lat = float(np.average(grp.lon, weights=w)), float(np.average(grp.lat, weights=w))
        out.append({"lon": round(lon, 5), "lat": round(lat, 5), "area": place_name(lon, lat), "hours": round(hours, 1),
                    "vessels": int(grp.mmsi.nunique()), "stops": len(grp)})
    out.sort(key=lambda r: -r["hours"])
    for i, r in enumerate(out):
        r["name"] = f"{label}_{i + 1}_{r['area']}"
    log.info("%s bases: %s", label, [(r["name"], r["hours"], r["vessels"]) for r in out])
    return out


def manoeuvres(df, stops, ships):
    """Arrival and departure manoeuvre minutes of sea-going ships at berths."""
    calls = stops[(stops.kind == "berth") & stops.mmsi.map(ships["class"]).isin(SEA_GOING)]
    by_visit = {v: g for v, g in df[df.visit.isin(calls.visit)].groupby("visit")}
    rows = []
    for c in calls.itertuples():
        g = by_visit[c.visit]
        t = g.t.to_numpy()
        x, y = to_km(g.lon.to_numpy(), g.lat.to_numpy())
        sx, sy = to_km(c.lon, c.lat)
        far = np.hypot(x - sx, y - sy) >= MANOEUVRE_DISTANCE_KM
        loa = ships.length.get(c.mmsi)
        if not loa or not np.isfinite(loa):
            continue
        for kind, ok in (("arrival", c.start_observed), ("departure", c.end_observed)):
            if not ok:
                continue
            if kind == "arrival":
                before = np.flatnonzero(far & (t < c.start))
                if not len(before):
                    continue
                i = before[-1]
                if i + 1 < len(t) and (t[i + 1] - t[i]) / np.timedelta64(1, "m") > MAX_FIX_GAP_MIN:
                    continue
                minutes = (c.start - t[i]) / np.timedelta64(1, "m")
            else:
                after = np.flatnonzero(far & (t > c.end))
                if not len(after):
                    continue
                i = after[0]
                if i > 0 and (t[i] - t[i - 1]) / np.timedelta64(1, "m") > MAX_FIX_GAP_MIN:
                    continue
                minutes = (t[i] - c.end) / np.timedelta64(1, "m")
            if 0 < minutes <= MANOEUVRE_MAX_MIN:
                rows.append({"kind": kind, "loa": float(loa), "minutes": float(minutes),
                             "area": "tidal" if c.zone in TIDAL_ZONES else "dock" if str(c.zone).startswith("antwerp") else "other"})
    return pd.DataFrame(rows)


def fit_manoeuvres(m):
    """t = base + k * LOA, residuals lognormal around the line (sigma of log(t / fitted))."""
    out = {}
    for (kind, area), grp in m[m.area != "other"].groupby(["kind", "area"]):
        if len(grp) < 8:
            continue
        k, base = np.polyfit(grp.loa, grp.minutes, 1)
        if k < 0:                       # no length effect visible: a constant
            k, base = 0.0, float(grp.minutes.median())
        fitted = np.maximum(base + k * grp.loa, 1.0)
        sigma = float(np.std(np.log(grp.minutes / fitted)))
        out[f"{kind}_{area}"] = {"base_min": round(float(base), 2), "per_m_loa_min": round(float(k), 4),
                                 "sigma": round(sigma, 3), "n": len(grp), "median_min": round(float(grp.minutes.median()), 1)}
    log.info("manoeuvre fits: %s", out)
    return out


def pilot_demand(df, ships):
    """Simultaneous ships needing a pilot, per zone, over the snapshots."""
    import pickle
    import sys

    from pyproj import Transformer
    from scipy.spatial import cKDTree

    sys.path.insert(0, str(REPO_ROOT / "src" / "environment"))
    graph = pickle.load(open(GRAPH, "rb"))["graph"]
    nodes = [d for _, d in graph.nodes(data=True) if d["type"] not in ("lock", "anchorage", "approach")]
    tree = cKDTree([(d["x"], d["y"]) for d in nodes])
    loa = df.mmsi.map(ships.length)
    f = df[(df.sog >= UNDER_WAY_KN) & df.mmsi.map(ships["class"]).isin(SEA_GOING) & (loa > 80) & df.in_scheldt].copy()
    x, y = Transformer.from_crs("EPSG:4326", graph.graph["crs"], always_xy=True).transform(f.lon.to_numpy(), f.lat.to_numpy())
    idx = tree.query(np.column_stack([x, y]))[1]
    zone = np.array([nodes[i].get("speed_zone") or "" for i in idx])
    f["zone"] = np.where(np.isin(zone, ("dock", "canal")), "dock", np.where(zone == "river", "river",
                         np.where(zone == "sea", "sea", "")))
    counts = f[f.zone != ""].groupby(["t", "zone"]).mmsi.nunique().unstack(fill_value=0)
    counts = counts.reindex(sorted(df.t.unique()), fill_value=0)
    out = {z: {"p50": float(counts[z].median()), "p95": float(np.percentile(counts[z], 95)),
               "p99": float(np.percentile(counts[z], 99)), "max": int(counts[z].max()), "snapshots": len(counts)}
           for z in counts.columns}
    log.info("pilot demand: %s", out)
    return out


def dock_speeds(df, ships):
    """Speeds of sea-going ships under way in the docks, per basin and near the locks."""
    import pickle

    from pyproj import Transformer
    from scipy.spatial import cKDTree

    if not GRAPH.is_file():
        log.warning("%s missing: no dock speeds", GRAPH)
        return {}
    import sys

    sys.path.insert(0, str(REPO_ROOT / "src" / "environment"))     # the pickle holds Lock / Terminal objects
    graph = pickle.load(open(GRAPH, "rb"))["graph"]
    nodes = [(n, d) for n, d in graph.nodes(data=True) if d["type"] not in ("lock", "anchorage", "approach")]
    tree = cKDTree([(d["x"], d["y"]) for _, d in nodes])
    locks = cKDTree([(d["x"], d["y"]) for _, d in graph.nodes(data=True) if d["type"] == "lock"])
    fixes = df[(df.sog >= UNDER_WAY_KN) & df.mmsi.map(ships["class"]).isin(SEA_GOING) & (df.port_zone != "")]
    x, y = Transformer.from_crs("EPSG:4326", graph.graph["crs"], always_xy=True).transform(fixes.lon.to_numpy(), fixes.lat.to_numpy())
    dist, idx = tree.query(np.column_stack([x, y]))
    near_lock = locks.query(np.column_stack([x, y]))[0] <= LOCK_APPROACH_M
    basin = np.array([nodes[i][1].get("basin") or "" for i in idx])
    region = np.array([nodes[i][1]["region"] for i in idx])
    # near a lock: only the outer harbours and docks, not the river traffic passing the lock heads
    area = np.where(near_lock & np.isin(region, ("port", "canal")), "lock_approach",
                    np.where((region == "port") & (basin != "") & ~near_lock, basin, ""))
    sog = fixes.sog.to_numpy()
    out = {}
    for name in sorted(set(area) - {""}):
        m = (area == name) & (dist <= SNAP_MAX_M)
        if m.sum() >= 30:
            out[str(name)] = {"p50": round(float(np.median(sog[m])), 1), "p95": round(float(np.percentile(sog[m], 95)), 1),
                         "fixes": int(m.sum()), "ships": len(set(fixes.mmsi.to_numpy()[m]))}
    log.info("dock speeds: %s", out)
    return out


MODULE_FUNCTIONS = '''

def is_tanker_berth(berth_id):
    """True / False from the AIS calls, None if no ship was seen there."""
    use = BERTH_USE.get(berth_id)
    return None if use is None else use["tanker_berth"]


def mooring_minutes(loa_m, kind="arrival", area="tidal", rng=None):
    """Manoeuvre time at a berth (kind arrival / departure, area tidal / dock): the fitted line,
    with lognormal noise when rng (numpy Generator) is given."""
    import math
    fit = MOORING_MIN.get(f"{kind}_{area}") or MOORING_MIN.get(f"{kind}_tidal") or next(iter(MOORING_MIN.values()))
    t = max(fit["base_min"] + fit["per_m_loa_min"] * loa_m, 1.0)
    return t * math.exp(rng.normal(0.0, fit["sigma"])) if rng is not None else t
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("port_infrastructure.py"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    data = prepare()
    stops = find_stops(data.df)
    ships = data.ships
    berths = load_berths()

    tugs = pd.read_csv(EQUIPMENT / "tugs.csv", sep=";", decimal=",")
    brabo = pd.read_csv(EQUIPMENT / "pilots_brabo.csv", sep=";")
    mdk = pd.read_csv(EQUIPMENT / "pilots_mdk.csv", sep=";")
    imo = pd.to_numeric(ships.imo, errors="coerce")
    name = ships.name.fillna("").str.upper().str.replace(r"\s+", " ", regex=True).str.strip()
    is_tug = imo.isin(set(tugs["IMO number"].dropna().astype(int))) | name.isin(set(tugs["Tug name"].str.upper())) \
        | (ships.ship_type == 52)
    is_pilot = ships.index.isin(brabo["MMSI number"]) | imo.isin(set(mdk["IMO number"].dropna().astype(int))) \
        | name.str.contains("BRABO|LOODS|PILOT")
    log.info("%d tugs and %d pilot boats in the AIS", is_tug.sum(), is_pilot.sum())

    m = manoeuvres(data.df, stops, ships)
    tables = {
        "BERTH_USE": berth_use(stops, ships, berths),
        "TUG_BASES": bases(stops, ships.index[is_tug], "tug_base"),
        "PILOT_BASES": bases(stops, ships.index[is_pilot], "pilot_base"),
        "MOORING_MIN": fit_manoeuvres(m),
        "DOCK_SPEED_KN": dock_speeds(data.df, ships),
        "PILOT_DEMAND": pilot_demand(data.df, ships),
    }
    period = f"{data.df.t.min():%Y-%m-%d %H:%M} to {data.df.t.max():%Y-%m-%d %H:%M} UTC"
    docstring = __doc__.split("Usage:")[0].replace("Fit the port", "Port", 1) + \
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z by src/data/fit_port_infrastructure.py from AIS {period}.\n"
    write_module(args.out, docstring, tables, MODULE_FUNCTIONS)


if __name__ == "__main__":
    main()
