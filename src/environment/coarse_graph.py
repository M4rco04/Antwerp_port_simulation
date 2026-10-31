"""The coarse routing graph (PLAN.md §5.1, §8): what the VTS plans on.

The fine graph is cut into regions around seed cells, spread over the water about SPACING_M
apart: the deepest cell of each block, so the coarse graph follows the fairway and channels.
Every lock, anchorage and terminal is a region of its own. Each fine cell belongs to the seed it
reaches first through the water (multi-source Dijkstra), so a region never jumps across land.

    coarse node   = a region: its seed cell, kind (water / lock / anchorage / terminal), name
    coarse node   also max_depth_m: the deepest cell of the region
    coarse edge   = two regions that touch: length_m and the fine path between their seeds,
                    crossing_depth_m (the deepest fine edge across the border: no ship deeper than
                    this gets from one region to the other directly) and bottleneck_depth_m (the
                    deepest draught that gets between the two seeds inside the two regions alone)

On the fine graph each node gets "coarse_node" (its region) and every fine edge between two
regions "coarse_edge" (the pair), so a reservation on a coarse edge covers those cells.

Routing is hierarchical: coarse_route() searches the coarse graph with crossing_depth_m and
max_depth_m (optimistic: the deep water between two seeds may wind through a third region where
channels run side by side), refine() then finds the fine path inside the corridor of regions along
the coarse route (and their neighbours), falling back to the whole graph if the corridor is too
shallow.

    C = build_coarse(G)
    path = coarse_route(C, a, b, draught_m, ukc_m, loa_m, beam_m, G=G)   coarse nodes
    fine = refine(G, C, path, a_fine, b_fine, draught_m, ...)            fine nodes
    expand(C, path)                                                      fine path along the seeds (no depth check)
    RouteCache(C, G).get(a, b, draught_m, ...)                           cached coarse routes
"""

from __future__ import annotations

import heapq
import logging
import math

import networkx as nx
import numpy as np

log = logging.getLogger("coarse")

SPACING_M = {"sea": 4000.0, "river": 2000.0, "canal": 2000.0, "port": 800.0}
SPECIAL = ("lock", "anchorage")


def _seeds(G):
    """Seed cells: one per SPACING_M block of each region (river: the deepest), plus every lock,
    anchorage and terminal access node."""
    seeds = {}
    blocks = {}
    for n, d in G.nodes(data=True):
        if d["type"] in SPECIAL:
            seeds[n] = d["type"]
            continue
        if d.get("terminal") and d["type"] == "terminal":
            seeds[n] = "terminal"
            continue
        sp = SPACING_M.get(d["region"])
        if sp is None:
            continue
        key = (d["region"], d.get("basin"), int(d["x"] // sp), int(d["y"] // sp))
        # the deepest cell of the block: a seed on a bank would cap every route through its region
        cx, cy = (key[2] + 0.5) * sp, (key[3] + 0.5) * sp
        score = (-round(d["depth_m"]), math.hypot(d["x"] - cx, d["y"] - cy))
        if key not in blocks or score < blocks[key][0]:
            blocks[key] = (score, n)
    for _, n in blocks.values():
        seeds.setdefault(n, "water")
    return seeds


def _regions(G, seeds):
    """Region of every fine node: the seed it reaches first through the water. Locks and
    anchorages are regions on their own and are not passed through."""
    region, dist = {}, {}
    heap = []
    for s in seeds:
        region[s], dist[s] = s, 0.0
        if G.nodes[s]["type"] not in SPECIAL:
            heapq.heappush(heap, (0.0, s, s))
    while heap:
        d, n, s = heapq.heappop(heap)
        if d > dist.get(n, math.inf) or region.get(n) != s:
            continue
        for m, e in G[n].items():
            if G.nodes[m]["type"] in SPECIAL or m in seeds:
                continue
            nd = d + e["weight"]
            if nd < dist.get(m, math.inf):
                dist[m], region[m] = nd, s
                heapq.heappush(heap, (nd, m, s))
    return region


def _widest_path(G, nodes, a, b):
    """Path a -> b within nodes that maximises its shallowest edge (the bottleneck depth)."""
    best = {a: math.inf}
    prev = {}
    heap = [(-math.inf, a)]
    done = set()
    while heap:
        negw, n = heapq.heappop(heap)
        if n in done:
            continue
        done.add(n)
        if n == b:
            break
        for m, e in G[n].items():
            if m not in nodes or m in done:
                continue
            w = min(-negw, e["depth_m"])
            if w > best.get(m, -math.inf):
                best[m], prev[m] = w, n
                heapq.heappush(heap, (-w, m))
    if b not in prev and a != b:
        return None, -math.inf
    path = [b]
    while path[-1] != a:
        path.append(prev[path[-1]])
    return path[::-1], best[b]


def build_coarse(G):
    seeds = _seeds(G)
    region = _regions(G, seeds)
    for n, d in G.nodes(data=True):
        d["coarse_node"] = region.get(n)
    C = nx.Graph()
    for s, kind in seeds.items():
        d = G.nodes[s]
        C.add_node(s, kind=kind, name=d.get("name") or (d.get("terminal") if kind == "terminal" else None),
                   x=d["x"], y=d["y"], longitude=d["longitude"], latitude=d["latitude"], region=d["region"],
                   zone=d["zone"], basin=d.get("basin"), depth_m=d["depth_m"])
    members = {}
    for n, r in region.items():
        members.setdefault(r, set()).add(n)
    crossings = {}
    for u, v, e in G.edges(data=True):
        ru, rv = region.get(u), region.get(v)
        e["coarse_edge"] = None
        if ru is None or rv is None or ru == rv:
            continue
        key = (min(ru, rv), max(ru, rv))
        e["coarse_edge"] = key
        n, deepest = crossings.get(key, (0, -math.inf))
        crossings[key] = (n + 1, max(deepest, e["depth_m"]))
    for s in seeds:
        C.nodes[s]["max_depth_m"] = float(max(G.nodes[n]["depth_m"] for n in members[s]))
    for (a, b), (n_cross, crossing_depth) in crossings.items():
        nodes = members[a] | members[b]
        sub = G.subgraph(nodes)
        try:
            path = nx.shortest_path(sub, a, b, weight="weight")
        except nx.NetworkXNoPath:
            continue
        deep, bottleneck = _widest_path(G, nodes, a, b)
        kinds = {C.nodes[a]["kind"], C.nodes[b]["kind"]}
        C.add_edge(a, b, length_m=float(nx.path_weight(G, path, "weight")), path=path,
                   min_depth_m=float(min(G.edges[u, v]["depth_m"] for u, v in zip(path, path[1:]))),
                   crossing_depth_m=float(crossing_depth), bottleneck_depth_m=float(bottleneck), deep_path=deep,
                   fine_edges=n_cross,
                   kind="lock" if "lock" in kinds else "anchorage" if "anchorage" in kinds else "water")
    C.graph.update(spacing_m=SPACING_M, n_fine_nodes=G.number_of_nodes())
    log.info("Coarse graph: %d nodes (%s), %d edges", C.number_of_nodes(),
             dict(zip(*np.unique([d["kind"] for _, d in C.nodes(data=True)], return_counts=True))), C.number_of_edges())
    return C


def coarse_route(C, source, target, draught_m, ukc_m=0.0, loa_m=0.0, beam_m=0.0, G=None, level=None,
                 lock_penalty_m=10_000.0, closed=frozenset()):
    """Coarse path source -> target (coarse nodes) whose every edge and region may let the ship
    through (crossing depth and region depth + water level >= draught + UKC), passing only locks
    whose chambers fit it (needs G for the Lock objects) and no anchorage on the way.
    level(coarse node) -> m above LAT, default LAT. closed: coarse edges (pairs) to avoid."""
    need = draught_m + ukc_m
    lvl = level or (lambda n: 0.0)

    def weight(u, v, e):
        if (min(u, v), max(u, v)) in closed:
            return None
        for n in (u, v):
            if C.nodes[n]["kind"] == "anchorage" and n not in (source, target):
                return None
        if e["kind"] == "lock":
            # as find_route: the chambers decide, at the level of the water the ship comes from
            lock_node, water_node = (u, v) if C.nodes[u]["kind"] == "lock" else (v, u)
            if C.nodes[water_node]["max_depth_m"] + lvl(water_node) < need:
                return None
            if G is not None:
                lock, h = G.nodes[lock_node]["lock"], lvl(water_node)
                if not any(c.fits_size(loa_m, beam_m) and need <= c.sill_depth_m + h for c in lock.chambers):
                    return None
            return e["length_m"] + lock_penalty_m / 2
        h_uv = min(lvl(u), lvl(v))
        if e["crossing_depth_m"] + h_uv < need or min(C.nodes[u]["max_depth_m"], C.nodes[v]["max_depth_m"]) + h_uv < need:
            return None
        return e["length_m"]

    def h(u, v):
        return math.hypot(C.nodes[u]["x"] - C.nodes[v]["x"], C.nodes[u]["y"] - C.nodes[v]["y"])

    return nx.astar_path(C, source, target, heuristic=h, weight=weight)


def corridor(G, C, path, neighbours=True):
    """Fine nodes of the regions on a coarse path (and of the regions next to them)."""
    regions = set(path)
    if neighbours:
        regions |= {m for n in path for m in C[n] if C.nodes[m]["kind"] not in SPECIAL}
    return {n for n, d in G.nodes(data=True) if d.get("coarse_node") in regions}


def refine(G, C, path, source, target, draught_m, ukc_m=0.0, loa_m=0.0, beam_m=0.0, water_level=None,
           lock_penalty_m=10_000.0):
    """Fine route source -> target (fine nodes) inside the corridor of a coarse path; the whole
    graph if the corridor is too shallow."""
    from antwerp_port import find_route

    nodes = corridor(G, C, path) | {source, target}
    try:
        return find_route(G.subgraph(nodes), source, target, draught_m, ukc_m, loa_m, beam_m,
                          lock_penalty_m=lock_penalty_m, water_level=water_level)
    except nx.NetworkXNoPath:
        log.info("corridor of %d regions too shallow, routing on the whole graph", len(path))
        return find_route(G, source, target, draught_m, ukc_m, loa_m, beam_m,
                          lock_penalty_m=lock_penalty_m, water_level=water_level)


def expand(C, path, deep=True):
    """Fine node path for a coarse path (the deep path of each coarse edge, or the shortest)."""
    fine = []
    for a, b in zip(path, path[1:]):
        e = C.edges[a, b]
        seg = e["deep_path" if deep and e.get("deep_path") else "path"]
        if seg[0] != a:
            seg = seg[::-1]
        fine.extend(seg if not fine else seg[1:])
    return fine


def draught_class(draught_m, step_m=0.5):
    return math.ceil(draught_m / step_m) * step_m


class RouteCache:
    """Coarse routes per (start, end, draught class, size class); reused until an edge on them
    is closed (PLAN.md §8)."""

    def __init__(self, C, G=None):
        self.C, self.G, self.routes = C, G, {}

    def get(self, source, target, draught_m, ukc_m=0.0, loa_m=0.0, beam_m=0.0, closed=frozenset()):
        key = (source, target, draught_class(draught_m + ukc_m), math.ceil(loa_m / 50), math.ceil(beam_m / 5))
        path = self.routes.get(key)
        if path is not None and not any((min(a, b), max(a, b)) in closed for a, b in zip(path, path[1:])):
            return path
        path = coarse_route(self.C, source, target, draught_m, ukc_m, loa_m, beam_m, G=self.G, closed=closed)
        self.routes[key] = path
        return path
