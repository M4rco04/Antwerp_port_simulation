"""Navigation attributes of the cells and the location-bound traffic rules (PLAN.md §5.2, regs §2, §5-§8).

assign_cell_attributes() gives every node of the navigation graph:

    lane_offset_m   signed distance from the channel axis (river: the estuary axis; canals: their
                    centreline), positive on the right bank looking upstream / inland, so positive
                    is starboard for an inbound ship and port for an outbound one. None at sea and
                    in the docks.
    lane            lane_offset_m in lanes of the river grid (RIVER_ACROSS_M), 0 = the axis
    fairway         inside the main fairway (regs §2.4). Western Scheldt: inside the lateral
                    buoys of the main fairway (Rijkswaterstaat; union of hulls of consecutive buoys); Zeeschelde (no buoys in the data): within ZEESCHELDE_FAIRWAY_HALF_M of
                    the axis (assumed), likewise MOUTH_FAIRWAY_HALF_M off Vlissingen below the first buoy; sea
                    and mouth: the buoyed Wielingen, Oostgat and Sardijngeul (hull of
                    their lateral buoys) and the Belgian deep-water route and traffic lanes; canals:
                    all; docks: False (regs §2.5 main dock waterways are not modelled yet)
    speed_zone      "sea" (pilot station to Vlissingen), "river" (Vlissingen to Antwerp), "canal",
                    "dock": the legs of the JA22 planning speeds (PLANNING_SPEED_KN)
    speed_limit_kn  None where only "safe speed" applies (the whole river: regs §7 found no number);
                    in the docks and near the locks no published limit was found either, so it is the
                    speed sea-going ships keep to in the AIS (95th percentile per dock basin and near
                    the locks; DOCK_SPEED_LIMIT_KN / LOCK_APPROACH_SPEED_KN without AIS)
    main_waterway   "right_bank" / "left_bank" on the main dock waterways (regs §2.5), else None;
                    dock_priority(a, b) gives the right of way in the docks
    lock_precaution within LOCK_APPROACH_M of a lock (HPV 8.3.6 precautionary area)
    stretches       names of the regulated stretches the cell lies in (STRETCHES)

graph.graph["stretches"] has each stretch's chainage range and source, graph.graph["reference_chainage_m"]
the reference lines (CP, buoy 35, De Nolle-Nieuwe Sluis, ...).

encounter_conflicts(stretches, a, b, kind) tells which rules forbid two ships to meet ("meet") or
overtake ("overtake") in those stretches; min_spacing_m() the following distance a rule requires.
Ships are dicts with loa, beam and the flags ulcv, imo2_gas, special_transport, oversized.
"""

from __future__ import annotations

import logging
import math

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import LineString

log = logging.getLogger("rules")

RIVER_ACROSS_M = 50.0
ZEESCHELDE_FAIRWAY_HALF_M = 150.0           # assumed: no buoy data upstream of the border
MOUTH_FAIRWAY_HALF_M = 500.0                # assumed: Vlissingen precautionary area, below the first main-fairway buoy
# dock and lock-approach speeds: no published limit was found (regs §7). They come from the AIS
# (src/data/port_infrastructure.py DOCK_SPEED_KN: the SPEED_PERCENTILE of sea-going ships under
# way); these values only when that is missing
DOCK_SPEED_LIMIT_KN = 6.0                    # assumed fallback
LOCK_APPROACH_SPEED_KN = 4.0                 # assumed fallback, within LOCK_APPROACH_M of a lock
SPEED_PERCENTILE = "p95"
LOCK_APPROACH_M = 600.0
NM = 1852.0

# main waterways in the docks (regs §2.5, HPV 8.3.2), traced through the dock basin between two
# ends: right bank kanaaldok B3 (from the Kreekrak locks) past the Berendrecht/Zandvliet locks,
# B2, B1, Hansadok, 5th Havendok and Amerikadok to Albertdok (Royers lock); left bank Verrebroekdok
# along the Waaslandkanaal to the Kallo lock. Cells within MAIN_WATERWAY_HALF_M of the traced line.
MAIN_DOCK_WATERWAYS = {
    "right_bank": {"basin": "antwerp_central_docks", "from": ("lock", "Kreekrak"), "to": ("lock", "Royers")},
    "left_bank": {"basin": "antwerp_left_bank_docks", "from": ("point", (4.205, 51.288)), "to": ("lock", "Kallo")},
}
MAIN_WATERWAY_HALF_M = 100.0

# main fairways (regs §2.4) by the "fairway" field of the Rijkswaterstaat buoys
RIVER_FAIRWAY_BUOYS = ("HOOFDVAARWATER WESTERSCHELDE",)
SEA_FAIRWAY_BUOYS = ("WIELINGEN", "OOSTGAT", "SARDIJNGEUL")
SEA_FAIRWAY_ZONES = ("Deep water route", "traffic flow")      # Belgian MSP shipping zones (name contains)
BUOY_MAX_OFF_AXIS_M = 2500.0
BUOY_WINDOW = 6                             # consecutive buoys per hull piece of the fairway polygon
BUOY_MARGIN_M = 25.0

# JA22 Appendix 1 planning speeds over the ground (kn), regs §8.5: (class, draught class) -> leg
PLANNING_SPEED_KN = {
    ("container", "<=14.5"): {"arrival": {"sea": 15.0, "river": 13.0}, "departure": {"sea": 16.0, "river": 12.0}},
    ("container", ">14.5"): {"arrival": {"sea": 14.5, "river": 12.5}, "departure": {"sea": 15.5, "river": 11.5}},
    ("bulk_tanker", "any"): {"arrival": {"sea": 12.0, "river": 12.0}, "departure": {"sea": 12.0, "river": 10.0}},
}

# reference points (lon, lat): their chainage goes to graph.graph["reference_chainage_m"]
REFERENCE_POINTS = {
    "vlissingen": ((3.600, 51.440), "pilot change sea -> river (regs §1.2); end of the 'sea' planning leg"),
    "de_nolle_nieuwe_sluis": ((3.540, 51.430), "line Fort De Nolle - Nieuwe Sluis (IMO2 visibility rule, regs §9); approximate"),
    "buoy_35": ((3.9536, 51.3845), "buoy 35 (Rijkswaterstaat): tug orders, 3 nm spacing rule"),
    "walsoorden": ((4.0316, 51.3934), "Walsoorden harbour mouth (sector light)"),
    "cp": ((4.2175, 51.3642), "CP, coordination point at the Zuid-Saeftinghe light (regs §0)"),
    "border": ((4.250, 51.355), "Dutch-Belgian border on the river; approximate"),
}

# regulated stretches: a chainage range between two points on the axis (lon, lat), or the hull of
# the buoys of a fairway, or within radius_m of a point
STRETCHES = {
    "sardijngeul": {"buoys": "SARDIJNGEUL", "source": "NtM 1/27", "approximate": False},
    "vlissingen_roads": {"between": ((3.560, 51.440), (3.640, 51.440)), "source": "NtM 1/60", "approximate": True},
    # between two charted main-fairway buoys (Rijkswaterstaat): Pas van Borssele around buoy 13,
    # Nauw van Bath around buoy 75 (both named so in buoy notices), Bocht van Bath the bend at
    # 51.389 N 4.205 E. The end buoys are chosen from the chart; the regulations give no limits.
    "pas_van_borssele": {"buoys_between": ("9", "15"), "source": "JA22 3.3, NtM 1/60", "approximate": False},
    "walsoorden_mouth": {"around": ((4.0316, 51.3934), 1000.0), "source": "GB25", "approximate": True},
    "nauw_van_bath": {"buoys_between": ("66", "77"), "source": "JA22 4.3", "approximate": False},
    "bocht_van_bath": {"buoys_between": ("77", "83"), "source": "NtM 1/60", "approximate": False},
    "buoy_35_to_cp": {"between": ((3.9536, 51.3845), (4.2175, 51.3642)), "source": "JA22", "approximate": False},
}


def _is(ship, flag):
    return bool(ship.get(flag))


def _big(ship, loa):
    return ship.get("loa", 0) >= loa


# encounter rules (regs §6): stretches, the kinds forbidden, and when the pair is affected
ENCOUNTER_RULES = [
    {"id": "sardijngeul_80m", "stretches": ("sardijngeul",), "kinds": ("meet", "overtake"),
     "pair": lambda a, b: _big(a, 80) and _big(b, 80), "source": "NtM 1/27"},
    {"id": "ulcv_avoid_meeting", "stretches": ("pas_van_borssele", "nauw_van_bath"), "kinds": ("meet",),
     "pair": lambda a, b: any(_is(x, "ulcv") and (_is(y, "imo2_gas") or _is(y, "special_transport") or _is(y, "oversized"))
                              for x, y in ((a, b), (b, a))), "source": "JA22 3.3 / 4.3"},
    {"id": "imo2_gas", "stretches": ("pas_van_borssele", "bocht_van_bath"), "kinds": ("meet", "overtake"),
     "pair": lambda a, b: any(_is(x, "imo2_gas") and (_is(y, "special_transport") or _is(y, "oversized") or _is(y, "imo2_gas"))
                              for x, y in ((a, b), (b, a))), "source": "NtM 1/60 4.d4"},
    {"id": "walsoorden_oversized", "stretches": ("walsoorden_mouth",), "kinds": ("meet", "overtake"),
     "pair": lambda a, b: _is(a, "oversized") and _is(b, "oversized"), "source": "GB25"},
]
SPACING_RULES = [
    {"id": "buoy35_cp_3nm", "stretches": ("buoy_35_to_cp",), "distance_m": 3 * NM,
     "pair": lambda a, b: any(_is(x, "ulcv") and _big(y, 300) for x, y in ((a, b), (b, a))), "source": "JA22"},
]


def encounter_conflicts(stretches, a, b, kind):
    """Rule ids forbidding ships a and b to meet / overtake (kind) in any of these stretches."""
    s = set(stretches)
    return [r["id"] for r in ENCOUNTER_RULES if kind in r["kinds"] and s & set(r["stretches"]) and r["pair"](a, b)]


def min_spacing_m(stretches, a, b):
    """Smallest distance between two ships sailing the same way that a rule asks for (0 if none)."""
    s = set(stretches)
    return max((r["distance_m"] for r in SPACING_RULES if s & set(r["stretches"]) and r["pair"](a, b)), default=0.0)


def dock_priority(a, b):
    """Who has right of way in the docks (regs §2.5 / §10.2, HPV 8.3.2): "a", "b", or None when the
    standard rules decide. Ships are dicts with not_under_command, dock_oversized and main_waterway
    (sailing along a main dock waterway, as opposed to coming out of a side dock or a lock)."""
    for flag in ("not_under_command", "dock_oversized"):
        fa, fb = _is(a, flag), _is(b, flag)
        if fa != fb:
            return "a" if fa else "b"
        if fa and fb:
            return None                     # two of a kind: the standard rules
    ma, mb = _is(a, "main_waterway"), _is(b, "main_waterway")
    if ma != mb:
        return "a" if ma else "b"
    return None


def planning_speed_kn(ship_class, draught_m, direction, leg):
    """JA22 planning speed over the ground; None for classes JA22 does not list."""
    if ship_class == "container":
        key = ("container", ">14.5" if draught_m > 14.5 else "<=14.5")
    elif ship_class in ("bulk_general", "tanker"):
        key = ("bulk_tanker", "any")
    else:
        return None
    return PLANNING_SPEED_KN[key][direction].get(leg)


# ---------------------------------------------------------------------------
# building


def _tangent(line, s, h=200.0):
    a = shapely.line_interpolate_point(line, np.clip(s - h, 0, line.length))
    b = shapely.line_interpolate_point(line, np.clip(s + h, 0, line.length))
    d = shapely.get_coordinates(b) - shapely.get_coordinates(a)
    return d / np.maximum(np.hypot(d[:, 0], d[:, 1]), 1e-9)[:, None]


def _signed_offset(line, x, y):
    """Chainage and signed offset (right of the line's direction positive) of points."""
    pts = shapely.points(x, y)
    s = shapely.line_locate_point(line, pts)
    foot = shapely.get_coordinates(shapely.line_interpolate_point(line, s))
    t = _tangent(line, s)
    dx, dy = x - foot[:, 0], y - foot[:, 1]
    return s, -(t[:, 0] * dy - t[:, 1] * dx)          # cross(t, d) > 0 is left


def _buoy_fairway(axis, buoys):
    """Main fairway polygon from its lateral buoys: the union of the convex hulls of every
    BUOY_WINDOW consecutive buoys (ordered along the axis), so it follows the bends whatever the
    axis does there. Returns the polygon and the chainage range the buoys cover."""
    b = buoys[buoys.fairway.isin(RIVER_FAIRWAY_BUOYS) & buoys.category.str.startswith("lateral")]
    x, y = b.geometry.x.to_numpy(), b.geometry.y.to_numpy()
    s, off = _signed_offset(axis, x, y)
    keep = (s > 0) & (s < axis.length) & (np.abs(off) < BUOY_MAX_OFF_AXIS_M)
    order = np.argsort(s[keep])
    pts = np.column_stack([x[keep], y[keep]])[order]
    hulls = [shapely.MultiPoint(pts[i:i + BUOY_WINDOW]).convex_hull for i in range(len(pts) - BUOY_WINDOW + 1)]
    poly = shapely.union_all(hulls).buffer(BUOY_MARGIN_M)
    log.info("main fairway from %d lateral buoys, chainage %.1f-%.1f km, %.1f km2", len(pts), s[keep].min() / 1000,
             s[keep].max() / 1000, poly.area / 1e6)
    return poly, float(s[keep].min()), float(s[keep].max())


def _end_node(graph, end, basin_nodes, to_xy):
    kind, what = end
    if kind == "lock":
        lock = next(n for n, d in graph.nodes(data=True) if d["type"] == "lock" and d["name"] == what)
        return next(m for m in graph[lock] if m in basin_nodes)
    x, y = to_xy(*what)
    return min(basin_nodes, key=lambda n: math.hypot(graph.nodes[n]["x"] - x, graph.nodes[n]["y"] - y))


def assign_dock_waterways(graph):
    """main_waterway (name or None) on the dock cells of the main dock waterways."""
    import networkx as nx

    to_xy = Transformer.from_crs("EPSG:4326", graph.graph["crs"], always_xy=True).transform
    for d in graph.nodes.values():
        d["main_waterway"] = None
    info = {}
    for name, spec in MAIN_DOCK_WATERWAYS.items():
        basin_nodes = {n for n, d in graph.nodes(data=True) if d.get("basin") == spec["basin"] and d["type"] != "lock"}
        a, b = (_end_node(graph, spec[k], basin_nodes, to_xy) for k in ("from", "to"))
        path = nx.shortest_path(graph.subgraph(basin_nodes), a, b, weight="weight")
        line = LineString([(graph.nodes[n]["x"], graph.nodes[n]["y"]) for n in path])
        ids = np.array([n for n in basin_nodes if graph.nodes[n]["region"] == "port"])
        X = np.array([graph.nodes[n]["x"] for n in ids])
        Y = np.array([graph.nodes[n]["y"] for n in ids])
        near = shapely.dwithin(line, shapely.points(X, Y), MAIN_WATERWAY_HALF_M)
        for n in ids[near]:
            graph.nodes[int(n)]["main_waterway"] = name
        info[name] = {"length_km": round(line.length / 1000, 1), "cells": int(near.sum()),
                      "line": [(round(x, 1), round(y, 1)) for x, y in line.simplify(25).coords]}
    graph.graph["main_dock_waterways"] = info
    log.info("main dock waterways: %s", {k: (v["length_km"], v["cells"]) for k, v in info.items()})


def dock_speeds():
    """AIS speeds in the docks (port_infrastructure.DOCK_SPEED_KN), or None."""
    import sys
    from pathlib import Path

    data = str(Path(__file__).resolve().parents[1] / "data")
    if data not in sys.path:
        sys.path.insert(0, data)
    try:
        import port_infrastructure
    except ImportError:
        return None
    return getattr(port_infrastructure, "DOCK_SPEED_KN", None)


def assign_cell_attributes(graph, buoys, zones_be, lines):
    """Lane, fairway, speed and stretch attributes of every node (see the module docstring).
    buoys / zones_be: chart layers in the graph's CRS; lines: channel centrelines (name -> LineString)."""
    to_xy = Transformer.from_crs("EPSG:4326", graph.graph["crs"], always_xy=True).transform
    axis = LineString(graph.graph["estuary_axis"])
    nodes = graph.nodes
    ids = np.array(list(graph.nodes))
    X = np.array([nodes[n]["x"] for n in ids])
    Y = np.array([nodes[n]["y"] for n in ids])
    region = np.array([nodes[n]["region"] for n in ids])
    basin = np.array([nodes[n].get("basin") is not None for n in ids])
    has_axis = np.array([nodes[n].get("chainage_m") is not None for n in ids])

    # lanes
    offset = np.full(len(ids), np.nan)
    chain = np.full(len(ids), np.nan)
    m = has_axis & ~basin & np.isin(region, ("river", "port"))
    chain[m], offset[m] = _signed_offset(axis, X[m], Y[m])
    for name, line in lines.items():
        if name in ("western_scheldt", "zeeschelde"):
            continue
        mc = (region == "canal") & np.array([nodes[n]["zone"] == name for n in ids])
        if mc.any():
            _, offset[mc] = _signed_offset(line, X[mc], Y[mc])

    # fairway
    poly, s_lo, s_hi = _buoy_fairway(axis, buoys)
    fairway = np.zeros(len(ids), dtype=bool)
    in_buoyed = m & (chain >= s_lo) & (chain <= s_hi)
    fairway[in_buoyed] = shapely.contains_xy(poly, X[in_buoyed], Y[in_buoyed])
    upstream = m & (chain > s_hi)
    fairway[upstream] = np.abs(offset[upstream]) <= ZEESCHELDE_FAIRWAY_HALF_M
    mouth = m & (chain < s_lo)
    fairway[mouth] = np.abs(offset[mouth]) <= MOUTH_FAIRWAY_HALF_M
    fairway[region == "canal"] = True
    sea_polys = []
    for name in SEA_FAIRWAY_BUOYS:
        b = buoys[(buoys.fairway == name) & buoys.category.str.startswith("lateral")]
        if len(b) >= 3:
            sea_polys.append(shapely.MultiPoint(list(zip(b.geometry.x, b.geometry.y))).convex_hull.buffer(100.0))
    for _, z in zones_be.iterrows():
        if any(k.lower() in str(z["name"]).lower() for k in SEA_FAIRWAY_ZONES):
            sea_polys.append(z.geometry)
    sea_area = shapely.union_all(sea_polys)
    open_water = (region != "canal") & ~basin & np.isin(region, ("sea", "river", "port"))
    fairway[open_water] |= shapely.contains_xy(sea_area, X[open_water], Y[open_water])

    # reference chainages and speed zones
    ref = {}
    for name, ((lon, lat), desc) in REFERENCE_POINTS.items():
        x, y = to_xy(lon, lat)
        ref[name] = round(float(axis.project(shapely.Point(x, y))), 1)
    zone = np.where(region == "sea", "sea", np.where(region == "canal", "canal", np.where(basin, "dock", "river")))
    zone[m & (chain < ref["vlissingen"])] = "sea"
    zone[(region == "port") & ~has_axis & ~basin] = "dock"           # tidal harbours off the axis (Vlissingen, Terneuzen)
    limit = np.full(len(ids), np.nan)
    observed = dock_speeds() or {}
    basin_name = np.array([nodes[n].get("basin") or "" for n in ids])
    limit[zone == "dock"] = DOCK_SPEED_LIMIT_KN
    for name, row in observed.items():
        if name != "lock_approach":
            limit[(zone == "dock") & (basin_name == name)] = row[SPEED_PERCENTILE]
    approach_kn = observed.get("lock_approach", {}).get(SPEED_PERCENTILE, LOCK_APPROACH_SPEED_KN)
    lock_area = np.zeros(len(ids), dtype=bool)
    lock_xy = np.array([(d["x"], d["y"]) for _, d in graph.nodes(data=True) if d["type"] == "lock"])
    if len(lock_xy):
        near = shapely.STRtree(shapely.points(lock_xy)).query(shapely.points(X, Y), predicate="dwithin",
                                                              distance=LOCK_APPROACH_M)[0]
        limit[np.unique(near)] = np.fmin(limit[np.unique(near)], approach_kn)
        lock_area[np.unique(near)] = True

    # stretches
    stretch_of = [[] for _ in ids]
    info = {}
    for name, spec in STRETCHES.items():
        if "buoys" in spec:
            b = buoys[buoys.fairway == spec["buoys"]]
            poly = shapely.MultiPoint(list(zip(b.geometry.x, b.geometry.y))).convex_hull.buffer(200.0)
            hit = shapely.contains_xy(poly, X, Y)
            s_range = [float(np.nanmin(chain[hit & m])), float(np.nanmax(chain[hit & m]))] if (hit & m).any() else None
        elif "between" in spec or "buoys_between" in spec:
            if "buoys_between" in spec:
                main = buoys[buoys.fairway.isin(RIVER_FAIRWAY_BUOYS)].set_index("name")
                p0, p1 = (main.geometry[n] for n in spec["buoys_between"])
            else:
                (lon0, lat0), (lon1, lat1) = spec["between"]
                p0, p1 = shapely.Point(*to_xy(lon0, lat0)), shapely.Point(*to_xy(lon1, lat1))
            s0, s1 = axis.project(p0), axis.project(p1)
            s_range = [float(min(s0, s1)), float(max(s0, s1))]
            hit = m & (chain >= s_range[0]) & (chain <= s_range[1])
        else:
            (lon, lat), radius = spec["around"]
            s0 = axis.project(shapely.Point(*to_xy(lon, lat)))
            s_range = [float(s0 - radius), float(s0 + radius)]
            hit = m & (chain >= s_range[0]) & (chain <= s_range[1])
        for i in np.flatnonzero(hit):
            stretch_of[i].append(name)
        info[name] = {"chainage_m": [round(v, 1) for v in s_range] if s_range else None, "cells": int(hit.sum()),
                      "source": spec["source"], "approximate": spec["approximate"],
                      "limits": [f"buoy {b}" for b in spec["buoys_between"]] if "buoys_between" in spec else None}

    for i, n in enumerate(ids):
        d = nodes[n]
        d["lane_offset_m"] = None if np.isnan(offset[i]) else round(float(offset[i]), 1)
        d["lane"] = None if np.isnan(offset[i]) else int(round(offset[i] / RIVER_ACROSS_M))
        d["fairway"] = bool(fairway[i])
        d["speed_zone"] = None if d["type"] in ("lock", "anchorage") else str(zone[i])
        d["speed_limit_kn"] = None if np.isnan(limit[i]) else float(limit[i])
        d["stretches"] = stretch_of[i]
        d["lock_precaution"] = bool(lock_area[i])           # HPV 8.3.6: do not hinder ships manoeuvring at the lock
    graph.graph.update(stretches=info, reference_chainage_m=ref, planning_speed_kn=PLANNING_SPEED_KN,
                       speed_limits={"dock_kn": {k: v[SPEED_PERCENTILE] for k, v in observed.items() if k != "lock_approach"}
                                     or DOCK_SPEED_LIMIT_KN, "lock_approach_kn": approach_kn,
                                     "lock_approach_m": LOCK_APPROACH_M,
                                     "source": f"AIS {SPEED_PERCENTILE} of sea-going ships" if observed else "assumed"})
    assign_dock_waterways(graph)
    log.info("cell attributes: %d cells with a lane, %d in the fairway, speed zones %s, stretches %s",
             int((~np.isnan(offset)).sum()), int(fairway.sum()),
             dict(zip(*np.unique(zone, return_counts=True))), {k: v["cells"] for k, v in info.items()})
