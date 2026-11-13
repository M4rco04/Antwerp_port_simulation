"""Named places on the navigation graph (PLAN.md §3, §4, §6): where ships come from and go to, the
pilot and tug points, and the reference points of the rules.

graph.graph["places"][name] = {"kind", "node", "longitude", "latitude", "snap_m", "description", ...}:

    source        every entry source of src/data/entry_probabilities.py (sea gates, canals, ports,
                  anchorages); the exits of background_traffic.py ("exit_<source>") use the same node
    approach      a virtual node beyond each sea gate (type "approach", one "virtual" edge of
                  APPROACH_EDGE_M to the gate) where a ship enters the model hours before its ETA
                  under virtual arrival (PLAN.md §4); its real distance out is the ship's own
    pilot_station Wandelaar and Steenbank (sea pilots board)
    pilot_change  Vlissingen (sea -> river pilot) and every lock (river -> dock pilot)
    pilot_base    where pilot boats lie (AIS, src/data/port_infrastructure.py)
    tug_base      where tugs lie between jobs (AIS)
    reference     CP, buoy 35, De Nolle - Nieuwe Sluis, Antwerp Roads (rules and GTA points)

graph.graph["destinations"][zone] = {"node", "berths"}: the berth zones of background_traffic.py
(antwerp_right_bank_docks, ...) with the charted berths in them; the other destinations are sources.

Places outside the Scheldt (Zeebrugge, Oosterschelde) snap to the nearest sea cell and are marked
outside=True; snap_m says how far a place is from its node.
"""

from __future__ import annotations

import logging
import math
import re
import sys
from pathlib import Path

import numpy as np
import shapely
from pyproj import Transformer

log = logging.getLogger("places")

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
APPROACH_EDGE_M = 50_000.0
CORE_MIN_DEPTH_M = 8.0          # places snap to cells joined to the main river by water at least this deep ...
INLAND_CORE_DEPTH_M = 3.0       # ... or this for places only inland craft use
INLAND_ONLY = ("albert_canal", "upper_sea_scheldt", "schelde_rijn_canal", "zuid_beveland_canal")
SEA_GATES = ("sea_west", "sea_southwest", "sea_north")
# a ship enters or leaves at sea in deep water: the median AIS position of the north gate lies on a bank of
# 9 m with 20 m of water 4 km away, and every 15 m ship from the north started on it
SEA_GATE_MIN_DEPTH_M = 20.0
OUTSIDE = ("zeebrugge", "oosterschelde")
CALL_PLACES = ("vlissingen",)   # placed at the median of the AIS calls there (background_traffic.ZONE_LOCATION)
# entry source -> what to snap it to: a node region, a canal zone, or an anchorage name
SNAP = {
    "ghent_terneuzen_canal": {"zone": "ghent_terneuzen_canal"},
    "zuid_beveland_canal": {"zone": "zuid_beveland_canal"},
    "schelde_rijn_canal": {"zone": "schelde_rijn_canal"},
    "upper_sea_scheldt": {"region": ("river",)},
    "albert_canal": {"region": ("port",)},
    "antwerp_port": {"region": ("port",)},
    "terneuzen": {"region": ("port", "river")},
    "vlissingen": {"region": ("port",)},
    "breskens": {"region": ("port", "river")},
}
# (lon, lat), description, approximate
PILOT_STATIONS = {
    "wandelaar": ((2.715, 51.370), "Wandelaar pilot station, 51°22.2'N 002°42.9'E (regs §1.2)", False),
    "steenbank": ((3.370, 51.620), "Steenbank pilot station (northern approach); position approximate", True),
}
REFERENCES = {
    "cp": ((4.2175, 51.3642), "CP, coordination point at the Zuid-Saeftinghe light: RTA / GTA point for Antwerp", False),
    "buoy_35": ((3.9536, 51.3845), "buoy 35: tug orders for arrivals (HPV 8.6.2), 3 nm spacing rule", False),
    "de_nolle_nieuwe_sluis": ((3.540, 51.430), "line Fort De Nolle - Nieuwe Sluis (IMO2 visibility rule)", True),
    "antwerp_roads": ((4.395, 51.235), "Antwerp Roads (Rede van Antwerpen): GTA point for the Upper Sea Scheldt", True),
    "walsoorden_mouth": ((4.0316, 51.3934), "Walsoorden harbour mouth", False),
}
VLISSINGEN_PILOT_CHANGE = ((3.590, 51.441), "Vlissingen Roads: sea pilot -> river pilot (regs §1.2)")


def _data_module(name):
    if str(DATA_DIR) not in sys.path:
        sys.path.insert(0, str(DATA_DIR))
    try:
        return __import__(name)
    except ImportError:
        log.warning("%s.py not found: run src/data/fit_*.py first", name)
        return None


class _Snapper:
    def __init__(self, graph):
        self.to_xy = Transformer.from_crs("EPSG:4326", graph.graph["crs"], always_xy=True).transform
        rows = [(n, d) for n, d in graph.nodes(data=True) if d["type"] not in ("lock", "anchorage", "approach")]
        self.ids = np.array([n for n, _ in rows])
        self.X = np.array([d["x"] for _, d in rows])
        self.Y = np.array([d["y"] for _, d in rows])
        self.region = np.array([d["region"] for _, d in rows])
        self.zone = np.array([d["zone"] for _, d in rows])
        self.depth = np.array([d["depth_m"] for _, d in rows])
        import networkx as nx
        self.cores = {}
        for depth in (CORE_MIN_DEPTH_M, INLAND_CORE_DEPTH_M):
            deep = graph.edge_subgraph([(u, v) for u, v, e in graph.edges(data=True) if e["depth_m"] >= depth])
            self.cores[depth] = np.isin(self.ids, list(max(nx.connected_components(deep), key=len)))
        self.core = self.cores[CORE_MIN_DEPTH_M]

    def __call__(self, lon, lat, mask=None, core_depth=CORE_MIN_DEPTH_M):
        self.core = self.cores[core_depth]
        x, y = self.to_xy(lon, lat)
        d = np.hypot(self.X - x, self.Y - y)
        in_core = self.core if mask is None else (mask & self.core)
        if not in_core.any():                       # nothing deep enough there: nearest cell of the mask
            log.warning("no cell joined to the river by %.0f m of water near %.4f, %.4f", CORE_MIN_DEPTH_M, lon, lat)
            in_core = np.ones(len(d), dtype=bool) if mask is None else mask
        d = np.where(in_core, d, np.inf)
        i = int(np.argmin(d))
        return int(self.ids[i]), float(d[i])


def _place(graph, kind, node, lon, lat, snap_m, description, **extra):
    return {"kind": kind, "node": int(node), "longitude": round(float(lon), 5), "latitude": round(float(lat), 5),
            "snap_m": round(float(snap_m)), "description": description, **extra}


def add_approach_node(graph, name, gate):
    """A virtual node beyond a sea gate (PLAN.md §4 virtual arrival)."""
    node = max(graph.nodes) + 1
    g = graph.nodes[gate]
    graph.add_node(node, **{k: g.get(k) for k in ("x", "y", "longitude", "latitude", "tide", "tide_gauge")},
                   region="virtual", zone="approach", type="approach", name=name, depth_m=50.0, depth_source="virtual",
                   drying=False, is_berth=False, berths=[], terminal=None, basin=None, fairway=True, lane=None,
                   lane_offset_m=None, speed_zone="sea", speed_limit_kn=None, stretches=[])
    graph.add_edge(node, gate, weight=APPROACH_EDGE_M, depth_m=50.0, kind="virtual")
    return node


def add_places(graph):
    snap = _Snapper(graph)
    places = {}
    entry = _data_module("entry_probabilities")
    background = _data_module("background_traffic")
    infra = _data_module("port_infrastructure")
    anchorages = graph.graph.get("anchorages", {})

    # every source with a rate needs a place: a ship that came in from sea and anchored has its anchorage as
    # source but no first fix there, so SOURCE_LOCATION does not list it; its anchorage node says where it is
    anchorage_of = {"anchorage_" + re.sub(r"[^a-z0-9]+", "_", a.lower()).strip("_"): a for a in anchorages}
    locations = dict(entry.SOURCE_LOCATION) if entry else {}
    for rates in (entry.RATE_PER_HOUR.values() if entry else []):
        for name in rates:
            if name not in locations and name in anchorage_of:
                d = graph.nodes[anchorages[anchorage_of[name]]]
                locations[name] = {"lon": d["longitude"], "lat": d["latitude"]}
    # a port where ships call lies where its calls are, not where ships leaving it are first heard: nine in ten
    # calls at Vlissingen are at Vlissingen-Oost (Sloehaven), 7 km up-river of the town, where the place lay.
    # Sea-going ships for it stopped short of the river section off Vlissingen and inland craft sailed past it
    # (validation: 60 against 106 sea-going passages a day there, 74 against 13 inland)
    for name in CALL_PLACES:
        loc = (getattr(background, "ZONE_LOCATION", {}) if background else {}).get(name)
        if loc and name in locations:
            locations[name] = {"lon": loc["lon"], "lat": loc["lat"]}
    for name, loc in locations.items():
        lon, lat = loc["lon"], loc["lat"]
        rule = SNAP.get(name, {"region": ("sea",)} if name in SEA_GATES or name in OUTSIDE else {})
        if name in anchorage_of:
            node, dist = anchorages[anchorage_of[name]], 0.0
        else:
            mask = None
            if "zone" in rule:
                mask = snap.zone == rule["zone"]
            elif "region" in rule:
                mask = np.isin(snap.region, rule["region"])
            if name in SEA_GATES:
                mask = mask & (snap.depth >= SEA_GATE_MIN_DEPTH_M)
            node, dist = snap(lon, lat, mask, INLAND_CORE_DEPTH_M if name in INLAND_ONLY else CORE_MIN_DEPTH_M)
        places[name] = _place(graph, "source", node, lon, lat, dist,
                              (entry.SOURCE_DESCRIPTION.get(name, name) if hasattr(entry, "SOURCE_DESCRIPTION") else name),
                              outside=name in OUTSIDE, exit=f"exit_{name}")
        if name in SEA_GATES:
            a = add_approach_node(graph, f"approach_{name}", node)
            places[f"approach_{name}"] = _place(graph, "approach", a, lon, lat, 0.0,
                                                f"virtual approach beyond {name} (virtual arrival)", gate=name,
                                                edge_m=APPROACH_EDGE_M)

    for name, ((lon, lat), desc, approx) in PILOT_STATIONS.items():
        node, dist = snap(lon, lat, snap.region == "sea")
        places[f"pilot_station_{name}"] = _place(graph, "pilot_station", node, lon, lat, dist, desc, approximate=approx)
    (lon, lat), desc = VLISSINGEN_PILOT_CHANGE
    node, dist = snap(lon, lat, snap.region == "river")
    places["pilot_change_vlissingen"] = _place(graph, "pilot_change", node, lon, lat, dist, desc)
    for n, d in graph.nodes(data=True):
        if d["type"] == "lock":
            places[f"pilot_change_{d['name'].lower().replace(' ', '_')}"] = _place(
                graph, "pilot_change", n, d["longitude"], d["latitude"], 0.0, f"{d['name']} lock: river pilot <-> dock pilot")
    for name, ((lon, lat), desc, approx) in REFERENCES.items():
        node, dist = snap(lon, lat, np.isin(snap.region, ("river", "port")))
        places[name] = _place(graph, "reference", node, lon, lat, dist, desc, approximate=approx)
    for kind, rows in (("tug_base", getattr(infra, "TUG_BASES", [])), ("pilot_base", getattr(infra, "PILOT_BASES", []))):
        for r in rows:
            node, dist = snap(r["lon"], r["lat"])
            places[r["name"]] = _place(graph, kind, node, r["lon"], r["lat"], dist,
                                       f"{kind.replace('_', ' ')} in {r['area']} (AIS: {r['hours']} vessel-hours, {r['vessels']} vessels)",
                                       hours=r["hours"], vessels=r["vessels"])
    graph.graph["places"] = places

    # destinations: berth zones with their berths, the rest are the sources of the same name
    dest = {}
    names = set()
    if background:
        for table in (background.P_DESTINATION_GIVEN_CLASS, getattr(background, "P_EXIT_GIVEN_CLASS", {})):
            for v in table.values():
                names |= set(v)
        for per in getattr(background, "NEXT_CALL", {}).values():
            for zone, following in per.items():
                names |= {zone} | (set(following) - {"leave"})
    berths = graph.graph.get("berths", {})
    for zone in sorted(names):
        base = zone[5:] if zone.startswith("exit_") else zone
        if base in places:
            dest[zone] = {"node": places[base]["node"], "berths": [], "place": base}
            continue
        ids = [b for b, r in berths.items() if r["zone"] == zone and r["nodes"]]
        if ids:
            xy = np.array([(graph.nodes[berths[b]["nodes"][0]]["x"], graph.nodes[berths[b]["nodes"][0]]["y"]) for b in ids])
            centre = xy.mean(axis=0)
            rep = berths[ids[int(np.argmin(np.hypot(*(xy - centre).T)))]]["nodes"][0]
            dest[zone] = {"node": int(rep), "berths": ids, "place": None}
        elif "antwerp_port" in places:
            dest[zone] = {"node": places["antwerp_port"]["node"], "berths": [], "place": "antwerp_port"}
        else:
            log.warning("destination %s has no place", zone)
    graph.graph["destinations"] = dest
    far = {k: v["snap_m"] for k, v in places.items() if v["snap_m"] > 2000}
    log.info("%d places (%s), %d destinations; places more than 2 km from their node: %s", len(places),
             dict(zip(*np.unique([p["kind"] for p in places.values()], return_counts=True))), len(dest), far)
    return places
