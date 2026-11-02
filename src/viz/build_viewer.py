"""Build an interactive viewer for one simulation run: a single self-contained HTML page.

    py src/viz/build_viewer.py results/test_7day            # -> results/test_7day/viewer.html
    py src/viz/build_viewer.py results/test_7day --open     # ... and open it in the browser

The page needs no server (open the file); it loads Leaflet, Chart.js and the base map tiles from
the internet. It shows:

    Live      the ships on a map, animated over the run (play / pause / speed / time slider), with
              charts of the port's state synced to the playhead; click a ship for its track,
              state timeline and events
    Analysis  time in the area by phase and class, container delays against the schedule, why
              ships waited for the VTS, lock passages, rule events, free quay at the terminals,
              and a searchable table of every ship

Inputs (written by src/sim/engine.py): positions.csv.gz, ships.csv, events.csv, timeseries.csv,
summary.json. The map layers (locks, anchorages, terminals, places, mesh) come from the
navigation graph and are cached in cache/viewer_layers.json.
"""

from __future__ import annotations

import argparse
import json
import math
import pickle
import sys
import webbrowser
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = Path(__file__).with_name("viewer_template.html")
GRAPH = ROOT / "cache" / "antwerp_scheldt_graph.pkl"
LAYER_CACHE = ROOT / "cache" / "viewer_layers.json"
ARRAYS = ROOT / "cache" / "antwerp_scheldt_graph.arrays.npz"
DEPTH_CACHE = ROOT / "cache" / "viewer_depth.json"
LEVEL_EVERY_MIN = 15.0                       # gauge levels sent to the page every 15 min (interpolated there)
COORD = 1e5                                  # lon / lat stored as integers of 1e-5 degree

# ship states -> the three activity groups the viewer colours by
STATE_GROUP = {
    "sailing": 0, "to_station": 0, "to_anchorage": 0,
    "wait_clearance": 1, "anchored": 1, "wait_pilot": 1, "lock_queue": 1, "pilot_change": 1, "boarding": 1,
    "spawned": 1,
    "in_lock": 2, "mooring": 2, "at_berth": 2, "unmooring": 2, "dwell_port": 2,
}
STATES = list(STATE_GROUP) + ["exited"]
# time in the area split into phases (minutes columns of ships.csv)
PHASES = {
    "Sailing": ["min_sailing", "min_to_station", "min_to_anchorage"],
    "Waiting for clearance or at anchor": ["min_wait_clearance", "min_anchored", "min_wait_pilot", "min_spawned"],
    "Pilot boarding and changes": ["min_boarding", "min_pilot_change"],
    "Locks": ["min_lock_queue", "min_in_lock"],
    "Berth and port": ["min_mooring", "min_at_berth", "min_unmooring", "min_dwell_port"],
}
CLASS_LABEL = {"container": "Container", "bulk_general": "Bulk / general cargo", "tanker": "Tanker",
               "inland_cargo": "Inland cargo", "inland_tanker": "Inland tanker", "passenger": "Passenger"}
KIND_GROUP = {"container": 0, "bulk_general": 1, "tanker": 1, "passenger": 1, "inland_cargo": 2, "inland_tanker": 2}
EVENT_SKIP = {"t", "ship", "event"}


def clean(v):
    if v is None:
        return None
    if isinstance(v, (float, np.floating)):
        return None if math.isnan(v) else round(float(v), 2)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


# ---------------------------------------------------------------------------------------------
# map layers from the navigation graph

def map_layers():
    if LAYER_CACHE.is_file() and GRAPH.is_file() and LAYER_CACHE.stat().st_mtime > GRAPH.stat().st_mtime:
        return json.loads(LAYER_CACHE.read_text())
    sys.path.insert(0, str(ROOT / "src" / "environment"))
    from pyproj import Transformer
    import shapely
    from shapely.geometry import MultiPoint

    to_lonlat = Transformer.from_crs("EPSG:32631", "EPSG:4326", always_xy=True).transform
    G = pickle.load(open(GRAPH, "rb"))["graph"]
    nd = G.nodes

    def ll(n):
        return [round(nd[n]["latitude"], 5), round(nd[n]["longitude"], 5)]

    locks = [{"name": name, "pos": ll(n),
              "chambers": [f"{c.name} {c.length_m:.0f} x {c.width_m:.0f} m" for c in nd[n]["lock"].chambers]}
             for name, n in G.graph["locks"].items()]
    anchorages = []
    for name, n in G.graph["anchorages"].items():
        a = nd[n]["anchorage"]
        pts = [(x, y) for _, x, y, _ in a.cells]
        if len(pts) >= 3:
            hull = MultiPoint(pts).convex_hull
            if hull.geom_type == "Polygon":
                xs, ys = hull.exterior.xy
                lon, lat = to_lonlat(np.array(xs), np.array(ys))
                anchorages.append({"name": name, "poly": [[round(b, 5), round(c, 5)] for b, c in zip(lat, lon)],
                                   "kind": a.kind})
                continue
        anchorages.append({"name": name, "pos": ll(n), "kind": a.kind})
    terminals = []
    for t in G.graph["terminals"]:
        line = np.asarray(t["quay_line"], dtype=float)
        lon, lat = to_lonlat(line[:, 0], line[:, 1])
        terminals.append({"name": t["name"], "line": [[round(b, 5), round(c, 5)] for b, c in zip(lat, lon)],
                          "sts": t.get("sts")})
    places = [{"name": k, "kind": p["kind"], "pos": [p["latitude"], p["longitude"]]}
              for k, p in G.graph["places"].items()
              if p["kind"] in ("pilot_station", "pilot_change", "reference", "source", "tug_base") and not p.get("outside")]
    mesh = {}
    for region in ("sea", "river", "canal", "port"):
        sel = [n for n, d in nd(data=True) if d.get("region") == region and "latitude" in d]
        mesh[region] = {"lat": [int(round(nd[n]["latitude"] * COORD)) for n in sel],
                        "lon": [int(round(nd[n]["longitude"] * COORD)) for n in sel]}
    out = {"locks": locks, "anchorages": anchorages, "terminals": terminals, "places": places, "mesh": mesh}
    LAYER_CACHE.write_text(json.dumps(out))
    return out


# ---------------------------------------------------------------------------------------------
# live depth: per water cell its depth below LAT and how its water level is made from the gauges

def depth_cells():
    """Every water cell: position, depth below LAT, and its level = (1 - w) gauge a + w gauge b, or a
    fixed basin level behind the locks (gauge a = -1, const). Integers: 1e-5 degree, cm, w x 1000."""
    if DEPTH_CACHE.is_file() and DEPTH_CACHE.stat().st_mtime > ARRAYS.stat().st_mtime:
        return json.loads(DEPTH_CACHE.read_text())
    sys.path.insert(0, str(ROOT / "src" / "environment"))
    from fast_graph import FastGraph
    from tide import TideModel

    fg = FastGraph.load(ARRAYS).bind_tide(TideModel.load())
    A, const = fg._tide
    A = A.tocsr()
    water = fg.mask("type", "water")
    idx = np.flatnonzero(water)
    ga, gb, w = np.full(len(idx), -1), np.full(len(idx), -1), np.zeros(len(idx))
    for k, i in enumerate(idx):
        cols, vals = A.indices[A.indptr[i]:A.indptr[i + 1]], A.data[A.indptr[i]:A.indptr[i + 1]]
        if len(cols):
            order = np.argsort(cols)
            cols, vals = cols[order], vals[order]
            ga[k] = cols[0]
            gb[k] = cols[-1]
            w[k] = vals[-1] if len(cols) > 1 else 0.0
    region = [fg.labels["region"][r] for r in fg.region[idx]]
    # cell shape: river and canal cells are 200 m along the channel x 50 m across; the along direction
    # is towards the farthest neighbour of the same region (the along-grid neighbour, 200 m away)
    ang = np.zeros(len(idx))
    for k, i in enumerate(idx):
        if region[k] not in ("river", "canal"):
            continue
        nb = fg.indices[fg.indptr[i]:fg.indptr[i + 1]]
        nb = nb[fg.region[nb] == fg.region[i]]
        if len(nb):
            d = np.hypot(fg.x[nb] - fg.x[i], fg.y[nb] - fg.y[i])
            j = nb[np.argmax(d)]
            ang[k] = math.degrees(math.atan2(fg.y[j] - fg.y[i], fg.x[j] - fg.x[i]))
    out = {"gauges": list(fg.labels["gauges"]),
           "lat": np.round(fg.latitude[idx] * COORD).astype(int).tolist(),
           "lon": np.round(fg.longitude[idx] * COORD).astype(int).tolist(),
           "depth": np.round(fg.depth_m[idx] * 100).astype(int).tolist(),
           "ga": ga.tolist(), "gb": gb.tolist(), "w": np.round(w * 1000).astype(int).tolist(),
           "c": np.round(const[idx] * 100).astype(int).tolist(),
           "along": [{"sea": 250, "river": 200, "canal": 200}.get(r, 50) for r in region],
           "across": [{"sea": 250, "river": 50, "canal": 50}.get(r, 50) for r in region],
           "ang": np.round(ang).astype(int).tolist()}
    DEPTH_CACHE.write_text(json.dumps(out, separators=(",", ":")))
    return out


def gauge_levels(run, gauges, start, end_min):
    """Water level at the gauges every LEVEL_EVERY_MIN (cm above LAT): the run's own (tide + surge) when
    it saved them, else the astronomical tide alone."""
    f = run / "levels.csv.gz"
    if f.is_file():
        lv = pd.read_csv(f)
        lv = lv[(lv.t % LEVEL_EVERY_MIN).abs() < 1e-6]
        source = "tide and surge of this run"
    else:
        sys.path.insert(0, str(ROOT / "src" / "environment"))
        from tide import TideModel
        t = np.arange(0.0, end_min + LEVEL_EVERY_MIN, LEVEL_EVERY_MIN)
        times = pd.Timestamp(start) + pd.to_timedelta(t, unit="min")
        lv = TideModel.load().levels(pd.DatetimeIndex(times))[gauges].reset_index(drop=True)
        lv.insert(0, "t", t)
        source = "astronomical tide only (this run did not save its levels)"
    return {"t": lv.t.round(1).tolist(), "cm": [np.round(lv[g].to_numpy() * 100).astype(int).tolist() for g in gauges],
            "source": source}


# ---------------------------------------------------------------------------------------------
# the run

def load_run(run: Path, warmup_days: float | None):
    summary = json.loads((run / "summary.json").read_text())
    step_min = float(summary.get("step_min", 5.0))
    warmup_min = float(summary["warmup_min"]) if "warmup_min" in summary else (warmup_days if warmup_days is not None else 2.0) * 1440
    start = summary.get("start")
    ts = pd.read_csv(run / "timeseries.csv")
    if start is None:
        start = str(pd.Timestamp(ts["time"].iloc[0]))
    ships = pd.read_csv(run / "ships.csv")
    pos = pd.read_csv(run / "positions.csv.gz")
    events = pd.read_csv(run / "events.csv", low_memory=False)
    return summary, step_min, warmup_min, start, ts, ships, pos, events


def pack_ships(ships, events, warmup_min, end_min):
    ships = ships.reset_index(drop=True)
    idx = {s: i for i, s in enumerate(ships.id)}
    end = ships.end_min.where(ships.end_min.notna(), end_min)
    hours = (end - ships.spawn_min) / 60.0
    phase = {name: ships[[c for c in cols if c in ships]].fillna(0).sum(axis=1) / 60.0 for name, cols in PHASES.items()}
    delay = (ships.moored_min - ships.scheduled_berth_min) / 60.0
    removed = set(events.loc[events.event == "infeasible", "ship"].dropna())
    status = np.where(ships.id.isin(removed), "removed", np.where(ships.finished, "finished", "in area"))
    cols = {
        "id": ships.id.tolist(), "name": ships.name.fillna("").tolist(), "cls": ships["class"].tolist(),
        "loa": ships.loa.round(1).tolist(), "beam": ships.beam.round(1).tolist(), "draught": ships.draught.round(2).tolist(),
        "teu": [clean(v) for v in ships.teu], "source": ships.source.fillna("").tolist(),
        "destination": ships.destination.fillna("").tolist(), "terminal": ships.terminal.fillna("").tolist(),
        "exit": ships.exit.fillna("").tolist(), "spawn": ships.spawn_min.round(1).tolist(),
        "end": [clean(v) for v in ships.end_min], "status": status.tolist(),
        "hours": hours.round(2).tolist(), "delay": [clean(v) for v in delay],
        "sched": [clean(v) for v in ships.scheduled_berth_min], "moored": [clean(v) for v in ships.moored_min],
        "after_warmup": (ships.spawn_min >= warmup_min).tolist(),
        "phase": {k: v.round(2).tolist() for k, v in phase.items()},
    }
    # events per ship: [t, event code, detail]
    names = sorted(events.event.dropna().unique())
    code = {n: i for i, n in enumerate(names)}
    extra = [c for c in events.columns if c not in EVENT_SKIP]
    per = [[] for _ in range(len(ships))]
    ev = events[events.ship.isin(idx)]
    vals = ev[extra].to_numpy(dtype=object)
    for (t, s, e), row in zip(ev[["t", "ship", "event"]].itertuples(index=False), vals):
        parts = []
        for c, v in zip(extra, row):
            v = clean(v)
            if v is None or v == "" or (c in ("source", "destination", "cls") and e == "spawned"):
                continue
            parts.append(f"{c}={v}")
        per[idx[s]].append([round(float(t), 1), code[e], ", ".join(parts)])
    return cols, idx, {"names": names, "per_ship": per}


def node_coords():
    """Latitude / longitude (1e-5 degree) of every graph node, by node index."""
    z = np.load(ARRAYS, allow_pickle=False)
    return (np.round(z["latitude"] * COORD).astype(int).tolist(), np.round(z["longitude"] * COORD).astype(int).tolist())


def pack_positions(pos, idx, step_min, run):
    """Per ship, its position records in time order (offsets per ship index):
        route >= 0   the ship is v metres along routes[route] (a list of nodes): drawn along that water
        route = -1   the ship lies at node v
    Runs saved before routes were recorded (15-min points) become node records at extra nodes, flagged
    legacy, which the page joins with straight lines as before."""
    lat, lon = node_coords()
    st_code = {s: i for i, s in enumerate(STATES)}
    pos = pos[pos.ship.isin(idx)].copy()
    pos["i"] = pos.ship.map(idx).astype(int)
    legacy = "route" not in pos.columns
    route_nodes, route_off = [], [0]
    if legacy:
        pts = pos[["lat", "lon"]].round(5)
        uniq = pts.drop_duplicates().reset_index(drop=True)
        key = {(a, b): len(lat) + k for k, (a, b) in enumerate(zip(uniq.lat, uniq.lon))}
        lat += [int(round(v * COORD)) for v in uniq.lat]
        lon += [int(round(v * COORD)) for v in uniq.lon]
        pos["route"] = -1
        pos["value"] = [key[(a, b)] for a, b in zip(pts.lat, pts.lon)]
    else:
        routes = json.loads((run / "routes.json").read_text())
        new_id, remap = {}, {}
        for rid in sorted(pos.route[pos.route >= 0].unique()):
            k = tuple(routes[int(rid)])
            if k not in new_id:
                new_id[k] = len(new_id)
                route_nodes += list(k)
                route_off.append(len(route_nodes))
            remap[int(rid)] = new_id[k]
        pos["route"] = pos.route.map(lambda r: remap.get(int(r), -1)).astype(int)
    pos = pos.sort_values(["i", "step"])
    counts = pos.groupby("i").size().reindex(range(len(idx)), fill_value=0).to_numpy()
    return {"off": np.r_[0, np.cumsum(counts)].tolist(), "t": (pos.step * step_min).round(1).tolist(),
            "route": pos.route.astype(int).tolist(), "v": np.round(pos.value.to_numpy()).astype(int).tolist(),
            "st": pos.state.map(lambda x: st_code.get(x, 0)).astype(int).tolist(), "legacy": legacy}, \
        {"nodes": route_nodes, "off": route_off}, {"lat": lat, "lon": lon}


def pack_timeseries(ts):
    g = {0: [], 1: [], 2: []}
    for s, k in STATE_GROUP.items():
        if f"n_{s}" in ts:
            g[k].append(f"n_{s}")
    out = {"t": ts.t.round(1).tolist(),
           "under_way": ts[g[0]].fillna(0).sum(axis=1).astype(int).tolist(),
           "waiting": ts[g[1]].fillna(0).sum(axis=1).astype(int).tolist(),
           "berth": ts[g[2]].fillna(0).sum(axis=1).astype(int).tolist(),
           "anchored": ts.get("n_anchored", pd.Series(0, index=ts.index)).fillna(0).astype(int).tolist()}
    for c in ("pilots_busy_sea", "pilots_busy_river", "pilots_busy_dock", "tugs_busy", "pilot_boats_busy",
              "boatmen_busy", "wind_bft", "visibility_m", "vts_requests", "lock_queue"):
        if c in ts:
            out[c] = [clean(v) for v in ts[c]]
    out["free_quay"] = {c[len("free_quay_"):]: [clean(v) for v in ts[c]] for c in ts.columns if c.startswith("free_quay_")}
    return out


def analysis(events, ships_cols):
    hold = events.loc[events.event == "vts_hold", "reason"].value_counts().to_dict()
    lock_entries = events.loc[(events.event == "enter") & events.ship.notna(), "lock"].value_counts().to_dict()
    rule_names = ["overtake_denied", "reroute", "squeeze_past", "hold_encounter_rule", "held_for_ulcv",
                  "weather_hold", "fallback_berth", "draught_capped", "no_anchorage", "anchorage_full", "infeasible"]
    rules = {n: int((events.event == n).sum()) for n in rule_names}
    return {"vts_hold": {k: int(v) for k, v in hold.items()}, "lock_entries": {k: int(v) for k, v in lock_entries.items()},
            "rules": rules}


def build(run: Path, out: Path | None = None, warmup_days: float | None = None):
    summary, step_min, warmup_min, start, ts, ships, pos, events = load_run(run, warmup_days)
    end_min = float(ts.t.max())
    ship_cols, idx, ev = pack_ships(ships, events, warmup_min, end_min)
    data = {
        "meta": {"run": run.name, "start": start, "step_min": step_min, "warmup_min": warmup_min,
                 "end_min": end_min, "summary": summary, "states": STATES,
                 "state_group": [STATE_GROUP.get(s, 1) for s in STATES], "class_label": CLASS_LABEL,
                 "kind_group": KIND_GROUP, "phases": list(PHASES)},
        "ships": ship_cols, "events": ev,
        "ts": pack_timeseries(ts), "analysis": analysis(events, ship_cols), "layers": map_layers(),
    }
    data["pos"], data["routes"], data["nodes"] = pack_positions(pos, idx, step_min, run)
    cells = depth_cells()
    data["depth"] = {"cells": cells, "levels": gauge_levels(run, cells["gauges"], start, end_min)}
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", blob).replace("__RUN__", run.name)
    out = out or run / "viewer.html"
    out.write_text(html, encoding="utf-8")
    return out, len(html)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run", type=Path, help="a run folder written by src/sim/engine.py --out")
    p.add_argument("--out", type=Path, help="the HTML file (default: <run>/viewer.html)")
    p.add_argument("--warmup", type=float, help="warm-up days, for runs saved before the summary recorded it")
    p.add_argument("--open", action="store_true", help="open the page in the browser")
    a = p.parse_args()
    out, size = build(a.run, a.out, a.warmup)
    print(f"wrote {out} ({size / 1e6:.1f} MB)")
    if a.open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main()
