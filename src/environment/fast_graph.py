"""Array form of the navigation graph for the simulation step loop (PLAN.md §5.1, §5.3).

networkx is too slow to touch every cell every 5 minutes. FastGraph keeps the same graph as numpy
arrays indexed 0..N-1 (index i is graph node ids[i]):

    node arrays   x, y, longitude, latitude, depth_m, region / zone / type / basin codes, chainage_m,
                  flow_dir, lane, lane_offset_m, fairway, speed_limit_kn, coarse (index of the node's
                  coarse region seed), is_berth
    CSR adjacency indptr, indices (both directions of every edge), and per entry: weight (m),
                  depth_m, kind code, edge id (one per undirected edge, u / v arrays)
    levels        water level (m above LAT) at every node for one or many times, from a row / table
                  of TideModel.levels() (a sparse matrix: tide = (1 - w) * gauge a + w * gauge b;
                  basins behind locks at their fixed level), the vectorised tide.node_levels
    passable      node / edge masks for a draught (+ UKC) at a level vector; PassabilityCache keeps
                  them per step and draught class, as PLAN.md §5.3 asks
    route         shortest path (scipy Dijkstra) with the same rules as antwerp_port.find_route:
                  no edge shallower than the need, locks only through a chamber that fits, anchorages
                  only as start or end; optionally inside a node mask (a coarse corridor)

    fg = FastGraph.from_graph(G)                 # or FastGraph.load(path) after fg.save(path)
    fg.bind_tide(model)                          # once: gauge columns and basin levels
    lv = fg.levels(model.levels(times))          # (n_times, N)
    path = fg.route(a, b, draught_m, ukc_m, loa_m, beam_m, level=lv[0])
"""

from __future__ import annotations

import logging

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import dijkstra

log = logging.getLogger("fast_graph")

EDGE_KINDS = ("sea", "river", "canal", "port", "link", "lock_gate", "anchorage_access", "virtual")
# locks that AIS shows almost nobody using (Royers, Kattendijk: 0.4 passages a day against 50 at the main
# locks): a route takes them only when there is no other way, not to save a few km through the docks
LITTLE_USED_LOCKS = ("Royers", "Kattendijk")
LITTLE_USED_LOCK_PENALTY_M = 100_000.0
NODE_FIELDS_FLOAT = ("x", "y", "longitude", "latitude", "depth_m", "chainage_m", "lane_offset_m", "speed_limit_kn")
NODE_FIELDS_CODE = ("region", "zone", "type", "basin", "speed_zone")
LOCK_PENALTY_M = 10_000.0
KEEP_RIGHT_PENALTY = 0.3


def _codes(values):
    labels = sorted({v for v in values if v is not None})
    lookup = {v: i for i, v in enumerate(labels)}
    return np.array([lookup.get(v, -1) for v in values], dtype=np.int16), labels


class FastGraph:
    def __init__(self, arrays, labels, graph=None):
        self.__dict__.update(arrays)
        self.labels = labels
        self.n = len(self.ids)
        self.index = {int(n): i for i, n in enumerate(self.ids)}
        self.graph = graph                       # the networkx graph (Lock objects), may be None
        self._tide = None

    # ------------------------------------------------------------------ build / io
    @classmethod
    def from_graph(cls, G):
        ids = np.array(sorted(G.nodes), dtype=np.int64)
        index = {int(n): i for i, n in enumerate(ids)}
        nodes = [G.nodes[n] for n in ids]
        arr, labels = {"ids": ids}, {}
        for f in NODE_FIELDS_FLOAT:
            arr[f] = np.array([np.nan if d.get(f) is None else d[f] for d in nodes], dtype=np.float64)
        for f in NODE_FIELDS_CODE:
            arr[f], labels[f] = _codes([d.get(f) for d in nodes])
        arr["lane"] = np.array([-9999 if d.get("lane") is None else d["lane"] for d in nodes], dtype=np.int32)
        arr["fairway"] = np.array([bool(d.get("fairway")) for d in nodes])
        arr["is_berth"] = np.array([bool(d.get("is_berth")) for d in nodes])
        arr["flow_dir"] = np.array([d.get("flow_dir") or (np.nan, np.nan) for d in nodes], dtype=np.float64)
        arr["coarse"] = np.array([index.get(d.get("coarse_node"), -1) for d in nodes], dtype=np.int64)
        # tide interpolation: gauge names as labels
        gauges = sorted({g for d in nodes if d.get("tide") for g in d["tide"][:2]})
        gi = {g: i for i, g in enumerate(gauges)}
        tide = [d.get("tide") for d in nodes]
        arr["tide_a"] = np.array([gi[t[0]] if t else -1 for t in tide], dtype=np.int16)
        arr["tide_b"] = np.array([gi[t[1]] if t else -1 for t in tide], dtype=np.int16)
        arr["tide_w"] = np.array([t[2] if t else 0.0 for t in tide], dtype=np.float64)
        arr["tide_gauge"], labels["tide_gauge"] = _codes([d.get("tide_gauge") for d in nodes])
        labels["gauges"] = gauges
        # edges
        eu, ev, ew, ed, ek = [], [], [], [], []
        for u, v, e in G.edges(data=True):
            eu.append(index[u]); ev.append(index[v]); ew.append(e["weight"]); ed.append(e["depth_m"])
            ek.append(EDGE_KINDS.index(e["kind"]) if e["kind"] in EDGE_KINDS else -1)
        eu, ev = np.array(eu, dtype=np.int64), np.array(ev, dtype=np.int64)
        m = len(eu)
        rows, cols = np.r_[eu, ev], np.r_[ev, eu]
        eid = np.r_[np.arange(m), np.arange(m)]
        order = np.lexsort((cols, rows))
        rows, cols, eid = rows[order], cols[order], eid[order]
        arr.update(edge_u=eu, edge_v=ev, edge_weight=np.array(ew), edge_depth=np.array(ed),
                   edge_kind=np.array(ek, dtype=np.int8),
                   indptr=np.r_[0, np.cumsum(np.bincount(rows, minlength=len(ids)))].astype(np.int64),
                   indices=cols.astype(np.int64), entry_edge=eid.astype(np.int64))
        fg = cls(arr, labels, G)
        log.info("FastGraph: %d nodes, %d edges", fg.n, m)
        return fg

    def save(self, path):
        arrays = {k: v for k, v in self.__dict__.items() if isinstance(v, np.ndarray) and not k.startswith("_")}
        np.savez_compressed(path, **arrays, labels=np.array([repr(self.labels)]))

    @classmethod
    def load(cls, path, graph=None):
        import ast

        z = np.load(path, allow_pickle=False)
        arrays = {k: z[k] for k in z.files if k != "labels"}
        return cls(arrays, ast.literal_eval(str(z["labels"][0])), graph)

    # ------------------------------------------------------------------ helpers
    def code(self, field, label):
        return self.labels[field].index(label)

    def mask(self, field, label):
        return getattr(self, field) == self.code(field, label)

    def neighbours(self, i):
        return self.indices[self.indptr[i]:self.indptr[i + 1]]

    @property
    def entry_rows(self):
        if not hasattr(self, "_rows"):
            self._rows = np.repeat(np.arange(self.n), np.diff(self.indptr))
        return self._rows

    # ------------------------------------------------------------------ water levels
    def bind_tide(self, model):
        """Gauge columns and fixed basin levels from a TideModel (once)."""
        from tide import BASIN_LEVELS_NAP_M, basin_key

        g = len(self.labels["gauges"])
        has = self.tide_a >= 0
        r = np.r_[np.flatnonzero(has), np.flatnonzero(has)]
        c = np.r_[self.tide_a[has], self.tide_b[has]]
        w = np.r_[1.0 - self.tide_w[has], self.tide_w[has]]
        A = sparse.csr_matrix((w, (r, c)), shape=(self.n, g))
        const = np.zeros(self.n)
        basins = self.labels["basin"]
        gauges = self.labels["tide_gauge"]
        for i in np.flatnonzero(~has & (self.basin >= 0)):
            gauge = gauges[self.tide_gauge[i]] if self.tide_gauge[i] >= 0 else "antwerpen.loodsgebouw"
            const[i] = model.basin_level_m(basins[self.basin[i]], gauge)
        self._tide = (A, const)
        return self

    def levels(self, levels):
        """Water level at every node: levels = one row (Series / dict) or a DataFrame of
        TideModel.levels(); returns (N,) or (n_times, N)."""
        A, const = self._tide
        gauges = self.labels["gauges"]
        if hasattr(levels, "columns"):
            L = levels[gauges].to_numpy()
            return np.asarray((A @ L.T).T) + const
        row = np.array([levels[g] for g in gauges], dtype=np.float64)
        return A @ row + const

    # ------------------------------------------------------------------ passability
    def passable_nodes(self, level, need):
        return self.depth_m + level >= need

    def lock_sill(self, loa_m, beam_m):
        """Per lock node index: the deepest sill among chambers the ship fits (-inf if none)."""
        out = {}
        for i in np.flatnonzero(self.mask("type", "lock")):
            lock = self.graph.nodes[int(self.ids[i])]["lock"]
            sills = [c.sill_depth_m for c in lock.chambers if c.fits_size(loa_m, beam_m)]
            out[int(i)] = max(sills) if sills else -np.inf
        return out

    def _static(self):
        if getattr(self, "_st", None) is None:
            is_lock, anch = self.mask("type", "lock"), self.mask("type", "anchorage")
            rows, cols = self.entry_rows, self.indices
            self._st = {"is_lock": is_lock, "anch": anch, "depth": self.edge_depth[self.entry_edge],
                        "weight": self.edge_weight[self.entry_edge],
                        "lock_entry": is_lock[rows] | is_lock[cols], "anch_entry": anch[rows] | anch[cols]}
            extra = np.zeros(len(rows))
            for i in np.flatnonzero(is_lock):
                if self.graph.nodes[int(self.ids[i])]["name"] in LITTLE_USED_LOCKS:
                    extra[(rows == i) | (cols == i)] = LITTLE_USED_LOCK_PENALTY_M / 2
            self._st["lock_extra"] = extra
            self._st["lock_k"] = np.flatnonzero(self._st["lock_entry"])
            self._st["anch_k"] = np.flatnonzero(self._st["anch_entry"])
        return self._st

    def _lock_entries(self, name):
        """Bool per CSR entry: into or out of this lock."""
        cache = self.__dict__.setdefault("_lock_entry_cache", {})
        if name not in cache:
            i = next(j for j in np.flatnonzero(self._static()["is_lock"]) if self.graph.nodes[int(self.ids[j])]["name"] == name)
            cache[name] = (self.entry_rows == i) | (self.indices == i)
        return cache[name]

    def passable_entries(self, level, need, loa_m=0.0, beam_m=0.0, ends=(), entries=None):
        """Bool mask over the CSR entries a ship may sail along (over entries, an index array of
        CSR entries, when given)."""
        st = self._static()
        if entries is None:                     # all entries: no index arrays (a tenth of the time)
            rows, cols, depth = self.entry_rows, self.indices, st["depth"]
            lock_k, anch_k = st["lock_k"], st["anch_k"]
        else:
            rows, cols, depth = self.entry_rows[entries], self.indices[entries], st["depth"][entries]
            lock_k, anch_k = np.flatnonzero(st["lock_entry"][entries]), np.flatnonzero(st["anch_entry"][entries])
        ok = depth + np.minimum(level[rows], level[cols]) >= need
        if len(lock_k):
            is_lock = st["is_lock"]
            sill = self.lock_sill(loa_m, beam_m)
            r, c = rows[lock_k], cols[lock_k]
            lock_i = np.where(is_lock[r], r, c)
            water_i = np.where(is_lock[r], c, r)
            ok[lock_k] = np.array([sill[int(l)] for l in lock_i]) + level[water_i] >= need
        if len(anch_k):
            ends = set(int(x) for x in ends)
            ok[anch_k] &= np.array([(not st["anch"][r] or r in ends) and (not st["anch"][c] or c in ends)
                                    for r, c in zip(rows[anch_k], cols[anch_k])])
        return ok

    def keep_right_factor(self, penalty=KEEP_RIGHT_PENALTY, margin_m=25.0):
        """Per CSR entry: 1 + penalty where the move u -> v ends on the wrong side of the axis for
        its direction (upstream on the left bank / downstream on the right bank), else 1. Moves
        across the axis and cells without an axis (sea, docks, canals) are neutral."""
        if getattr(self, "_keep_right", None) is None:
            rows, cols = self.entry_rows, self.indices
            dx, dy = self.x[cols] - self.x[rows], self.y[cols] - self.y[rows]
            n = np.maximum(np.hypot(dx, dy), 1e-9)
            cos = (dx * self.flow_dir[rows, 0] + dy * self.flow_dir[rows, 1]) / n
            off = self.lane_offset_m[cols]
            with np.errstate(invalid="ignore"):
                wrong = ((cos > 0.3) & (off < -margin_m)) | ((cos < -0.3) & (off > margin_m))
            self._keep_right = np.where(wrong, 1.0 + penalty, 1.0)
        return self._keep_right

    def reachable(self, source, draught_m, ukc_m=0.0, loa_m=0.0, beam_m=0.0, level=None):
        """Bool per node: can a ship of this size get there from source (one Dijkstra for all
        nodes; anchorages are not passed through)."""
        s = self.index[int(source)]
        level = np.zeros(self.n) if level is None else level
        e = np.arange(len(self.indices))
        ok = self.passable_entries(level, draught_m + ukc_m, loa_m, beam_m, ends=(s,), entries=e)
        e = e[ok]
        M = sparse.csr_matrix((self._static()["weight"][e], (self.entry_rows[e], self.indices[e])), shape=(self.n, self.n))
        dist = dijkstra(M, directed=True, indices=s)
        out = np.isfinite(dist)
        anch = self._static()["anch"]
        if anch.any():                          # an anchorage is reachable when a cell next to it is
            for a in np.flatnonzero(anch):
                out[a] = out[self.neighbours(a)].any()
        return out

    def route(self, source, target, draught_m, ukc_m=0.0, loa_m=0.0, beam_m=0.0, level=None, nodes_mask=None,
              lock_penalty_m=LOCK_PENALTY_M, keep_right=False, min_clearance=None, lane_factor=None,
              depth_penalty=None, avoid_locks=(), lock_cost=None):
        """Shortest allowed path between two graph node ids (list of node ids); raises
        networkx.NetworkXNoPath like find_route. keep_right: prefer the starboard half of the
        river (regs §5.1), see keep_right_factor. min_clearance: only cells with at least this
        much water to either side (self.clearance, see clearance.py), for wide ships. lane_factor: a
        cost multiplier per CSR entry (lanes.Lanes.factor: hold the starboard side of the buoyed
        fairway); where it is nan the keep-right factor applies. depth_penalty = (level, need_m, per_m):
        a cell shallower than need_m at that level costs 1 + per_m x the metres it lacks: the route keeps
        to the deep channel wherever there is one, without forbidding the cells that need the tide.
        avoid_locks: names of locks this ship takes only if no other will do. lock_cost: {lock name: metres}
        added to a passage of that lock (a lock this ship would rather not take)."""
        import networkx as nx

        s, t = self.index[int(source)], self.index[int(target)]
        level = np.zeros(self.n) if level is None else level
        st = self._static()
        rows, cols = self.entry_rows, self.indices
        if min_clearance is not None and getattr(self, "clearance", None) is not None:
            wide = self.clearance >= min_clearance
            nodes_mask = wide if nodes_mask is None else (nodes_mask & wide)
        # every array runs over all CSR entries and an entry the ship may not use weighs inf: the matrix keeps
        # the graph's own CSR layout (no index arrays, no COO -> CSR sort: these took a third of a route)
        ok = self.passable_entries(level, draught_m + ukc_m, loa_m, beam_m, ends=(s, t))
        if nodes_mask is not None:
            keep = nodes_mask.copy()
            keep[[s, t]] = True
            ok &= keep[rows] & keep[cols]
        w = st["weight"] + np.where(st["lock_entry"], lock_penalty_m / 2, 0.0) + st["lock_extra"]
        for name in avoid_locks:
            w = w + self._lock_entries(name) * LITTLE_USED_LOCK_PENALTY_M / 2
        for name, metres in (lock_cost or {}).items():
            w = w + self._lock_entries(name) * metres / 2
        if lane_factor is not None:
            w = w * np.where(np.isfinite(lane_factor), lane_factor, self.keep_right_factor() if keep_right else 1.0)
        elif keep_right:
            w = w * self.keep_right_factor()
        if depth_penalty is not None:
            low, need, per_m = depth_penalty
            short = need - (st["depth"] + np.minimum(low[rows], low[cols]))
            w = w * np.where(st["lock_entry"], 1.0, 1.0 + per_m * np.clip(short, 0.0, None))
        M = sparse.csr_matrix((np.where(ok, w, np.inf), cols, self.indptr), shape=(self.n, self.n))
        # limit: an entry of weight inf is never taken (without it the search would walk them at distance inf)
        dist, pred = dijkstra(M, directed=True, indices=s, return_predecessors=True, limit=ROUTE_LIMIT_M)
        if not np.isfinite(dist[t]):
            raise nx.NetworkXNoPath(f"Node {target} not reachable from {source}")
        path = [t]
        while path[-1] != s:
            path.append(pred[path[-1]])
        return [int(self.ids[i]) for i in path[::-1]]


ROUTE_LIMIT_M = 1e12                     # longer than any route (weights are metres, with penalties)


class PassabilityCache:
    """Passable-node masks per step and draught class (PLAN.md §5.3: only the classes in use)."""

    def __init__(self, fg, step_m=0.5):
        self.fg, self.step_m = fg, step_m
        self.step, self.masks = None, {}

    def get(self, step, level, need_m):
        if step != self.step:
            self.step, self.masks = step, {}
        key = np.ceil(need_m / self.step_m) * self.step_m
        if key not in self.masks:
            self.masks[key] = self.fg.passable_nodes(level, key)
        return self.masks[key]
