"""Tidal currents along the Scheldt (PLAN.md §5.3), from the tide by continuity.

The water that flows through a cross-section of the estuary is the water needed to raise (flood)
or lower (ebb) everything upstream of it:

    Q(s, t) = sum over slices upstream of s of  wet surface(h) * dh/dt
              + upstream_storage_m2 * dh/dt at the head   (Upper Sea Scheldt, Rupel: beyond the graph)
              - river_discharge_m3s
    u(s, t) = scale(reach) * Q / A(s, h)                  (m/s, positive = flood = upstream)

The estuary is cut into SLICE_M slices along the axis the graph builder stores (node attribute
"chainage_m"). The wet surface and the cross-section A of a slice at a water level h come from
the graph's own cells (depth below LAT + h > 0), and h from the tide model (tide.py). scale and
the upstream storage are calibrated on AIS speeds over ground by fit_currents.py
(data/tides/current_calibration.json).

    field = CurrentModel(graph, tide_model).compute(times, weather=None)
    field.at(chainage_m, i_time)                    current (m/s, + = flood) at a chainage
    field.along(graph, u, v, i_time)                 component along an edge u -> v (m/s, signed)
    field.speed_over_ground(graph, u, v, i_time, stw_kn)   knots over the ground on that edge

tide.tidal_window(..., currents=CurrentModel(...)) uses the current for the arrival times along a route.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CALIBRATION_FILE = PROJECT_ROOT / "data" / "tides" / "current_calibration.json"
SLICE_M = 500.0
# cross-sections are averaged over this many slices, and never taken smaller than MIN_SECTION_M2:
# a slice where two grids meet can hold few cells, which would make its section (and current) absurd
SECTION_SMOOTHING_SLICES = 5
MIN_SECTION_M2 = 3000.0
# area of water one graph node stands for (grid spacing, m x m)
CELL_AREA_M2 = {"river": 200.0 * 50.0, "canal": 200.0 * 50.0, "port": 50.0 * 50.0}
# Tidal water above the head of the graph (Upper Sea Scheldt to Ghent, Rupel, Durme, Nete): ~100 km
# of river ~250 m wide plus tributaries. A rough estimate: AIS cannot pin it down (see fit_currents.py).
UPSTREAM_STORAGE_M2 = 15e6
DEFAULTS = {"scale": {"western_scheldt": 1.0, "zeeschelde": 1.0}, "upstream_storage_m2": UPSTREAM_STORAGE_M2,
            "river_discharge_m3s": 120.0}
# the calibration scale changes here (about the Dutch-Belgian border)
REACH_SPLIT_LON = 4.2
KNOT = 1852.0 / 3600.0


def load_calibration():
    if CALIBRATION_FILE.is_file():
        return {**DEFAULTS, **json.loads(CALIBRATION_FILE.read_text())}
    return dict(DEFAULTS)


class CurrentModel:
    def __init__(self, graph, tide_model, calibration=None, slice_m=SLICE_M):
        self.graph, self.tide = graph, tide_model
        self.cal = calibration or load_calibration()
        self.slice_m = slice_m
        nodes = [n for n, d in graph.nodes(data=True) if "chainage_m" in d]
        s = np.array([graph.nodes[n]["chainage_m"] for n in nodes])
        depth = np.array([graph.nodes[n]["depth_m"] for n in nodes])
        area = np.array([CELL_AREA_M2.get(graph.nodes[n]["region"], 2500.0) for n in nodes])
        self.n_slices = int(s.max() // slice_m) + 1
        self.slice_of = dict(zip(nodes, (s // slice_m).astype(int)))
        gauges = tide_model.gauges
        col = {g: i for i, g in enumerate(gauges)}
        # per slice: its cells (depth, area) sorted deepest first, and its level as a mix of the gauges
        self.depths, self.cum_area, self.cum_vol, self.weights = [], [], [], np.zeros((self.n_slices, len(gauges)))
        j_of = (s // slice_m).astype(int)
        for j in range(self.n_slices):
            sel = np.flatnonzero(j_of == j)
            order = sel[np.argsort(-depth[sel])]
            self.depths.append(depth[order])
            self.cum_area.append(np.concatenate([[0.0], np.cumsum(area[order])]))
            self.cum_vol.append(np.concatenate([[0.0], np.cumsum(area[order] * depth[order])]))
            for i in sel:
                a, b, w = graph.nodes[nodes[i]]["tide"]
                self.weights[j, col[a]] += (1 - w) / max(len(sel), 1)
                self.weights[j, col[b]] += w / max(len(sel), 1)
        # which reach each slice is in (by the longitude of its middle on the axis)
        import shapely
        from shapely.geometry import LineString
        from pyproj import Transformer

        axis = LineString(graph.graph["estuary_axis"])
        mid = shapely.get_coordinates(shapely.line_interpolate_point(axis, (np.arange(self.n_slices) + 0.5) * slice_m))
        lon, _ = Transformer.from_crs("EPSG:32631", "EPSG:4326", always_xy=True).transform(mid[:, 0], mid[:, 1])
        self.reach = np.where(lon < REACH_SPLIT_LON, "western_scheldt", "zeeschelde")
        empty = self.weights.sum(axis=1) == 0                 # a slice without cells: copy the neighbour
        for j in np.flatnonzero(empty):
            k = j - 1 if j > 0 else j + 1
            self.weights[j] = self.weights[k]

    def _wet(self, j, h):
        """Wet surface (m2) and wet volume (m3) of slice j at levels h (array)."""
        d = self.depths[j]
        k = np.searchsorted(-d, h, side="left")              # cells with depth > -h are wet
        return self.cum_area[j][k], self.cum_vol[j][k] + h * self.cum_area[j][k]

    def compute(self, times, weather=None, components=False):
        """Current at every slice for the times (regular steps): CurrentField. components=True also
        returns the two parts the calibration needs (in-graph storage, storage above the head)."""
        times = pd.DatetimeIndex(times)
        L = self.tide.levels(times, weather).to_numpy()
        H = L @ self.weights.T                                # (times, slices) m above LAT
        dt = np.diff(times.as_unit("ns").asi8).mean() / 1e9          # step in seconds, whatever the unit
        dHdt = np.gradient(H, dt, axis=0)
        surface = np.zeros_like(H)
        section = np.zeros_like(H)
        for j in range(self.n_slices):
            surface[:, j], volume = self._wet(j, H[:, j])
            section[:, j] = volume / self.slice_m
        k = SECTION_SMOOTHING_SLICES
        kernel = np.ones(k) / k
        padded = np.pad(section, ((0, 0), (k // 2, k // 2)), mode="edge")
        section = np.apply_along_axis(lambda r: np.convolve(r, kernel, mode="valid"), 1, padded)
        # where the grids hand over, a slice can still be short of cells: no section below 80 % of the
        # running median over 10 km of river
        m = int(10_000 / self.slice_m) | 1
        median = pd.DataFrame(section.T).rolling(m, center=True, min_periods=1).median().to_numpy().T
        section = np.maximum(section, np.maximum(0.8 * median, MIN_SECTION_M2))
        inflow = surface * dHdt                               # m3/s each slice needs (+ = filling)
        q_graph = np.cumsum(inflow[:, ::-1], axis=1)[:, ::-1]   # through the downstream face of each slice
        head = dHdt[:, -1:] * np.ones((1, self.n_slices))
        u_graph, u_head = q_graph / section, head / section
        u_river = -self.cal["river_discharge_m3s"] / section
        scale = self.cal["scale"]
        k = np.array([scale[r] for r in self.reach]) if isinstance(scale, dict) else scale
        u = k * (u_graph + self.cal["upstream_storage_m2"] * u_head) + u_river
        field = CurrentField(times, u, self.slice_m, self.slice_of)
        if components:
            return field, (u_graph, u_head, u_river)
        return field


class CurrentField:
    def __init__(self, times, u, slice_m, slice_of):
        self.times, self.u, self.slice_m, self.slice_of = times, u, slice_m, slice_of

    def index(self, t):
        return int(np.clip(self.times.searchsorted(pd.Timestamp(t)), 0, len(self.times) - 1))

    def at(self, chainage_m, i_time):
        j = np.clip((np.asarray(chainage_m) // self.slice_m).astype(int), 0, self.u.shape[1] - 1)
        return self.u[i_time, j]

    def along(self, graph, u, v, i_time):
        """Current component along the edge u -> v (m/s; + = helps a ship sailing u -> v)."""
        d = graph.nodes[u]
        if "flow_dir" not in d:
            return 0.0
        e = np.array([graph.nodes[v]["x"] - d["x"], graph.nodes[v]["y"] - d["y"]])
        n = np.linalg.norm(e)
        if n == 0:
            return 0.0
        return float(self.u[i_time, self.slice_of[u]] * np.dot(e / n, d["flow_dir"]))

    def along_unit(self, graph, u, v):
        """(slice index, cos of the angle between the edge u -> v and the flood direction); slice -1
        where there is no current (sea, basins behind locks)."""
        d = graph.nodes[u]
        if "flow_dir" not in d or u not in self.slice_of:
            return (-1, 0.0)
        e = np.array([graph.nodes[v]["x"] - d["x"], graph.nodes[v]["y"] - d["y"]])
        n = np.linalg.norm(e)
        return (self.slice_of[u], float(np.dot(e / n, d["flow_dir"])) if n else 0.0)

    def speed_over_ground(self, graph, u, v, i_time, stw_kn):
        """Speed over the ground (kn) on the edge u -> v for a speed through the water (kn)."""
        return max(stw_kn + self.along(graph, u, v, i_time) / KNOT, 0.5)
