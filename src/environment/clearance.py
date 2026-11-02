"""How much water there is around every cell of the mesh: the distance from the cell's centre to the
edge of the water (m). A ship of beam B fits on a cell when its clearance is at least B / 2.

The mesh is drawn on a RES_M raster: every edge between two water cells is sampled along its length
(the edges only exist over water), the drawing is closed over the gaps between the grid lines, and a
Euclidean distance transform gives the distance to the nearest pixel that is not water. A cell at
the edge of the mesh stands for water up to half a lane beyond its centre, so half the lane width
is added (and the one pixel the distance transform counts at the edge taken off). Sea cells get
SEA_CLEARANCE_M (the sea grid ends where the traffic ends, not at a bank).
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

RES_M = 25.0
SEA_CLEARANCE_M = 1000.0
LANE_WIDTH_M = {"sea": 250.0, "river": 50.0, "canal": 50.0, "port": 50.0}
MAX_EDGE_M = 400.0


def lane_width(fg):
    """Width of the lane a cell stands for (across the fairway), per node."""
    out = np.full(fg.n, 50.0)
    for region, w in LANE_WIDTH_M.items():
        if region in fg.labels["region"]:
            out[fg.mask("region", region)] = w
    return out


def node_clearance(fg):
    special = np.isin(fg.type, [fg.code("type", t) for t in ("lock", "anchorage", "approach")])
    sea = fg.mask("region", "sea")
    inland = ~special & ~sea
    u, v = fg.edge_u, fg.edge_v
    keep = ~special[u] & ~special[v] & (inland[u] | inland[v])
    u, v = u[keep], v[keep]
    x0, y0 = fg.x[inland].min() - 1000, fg.y[inland].min() - 1000
    x1, y1 = fg.x[inland].max() + 1000, fg.y[inland].max() + 1000
    width, height = int((x1 - x0) / RES_M) + 1, int((y1 - y0) / RES_M) + 1
    length = np.hypot(fg.x[v] - fg.x[u], fg.y[v] - fg.y[u])
    ok = length <= MAX_EDGE_M
    u, v, length = u[ok], v[ok], length[ok]
    steps = np.maximum(np.ceil(length / (RES_M / 2)).astype(int), 1)
    edge = np.repeat(np.arange(len(u)), steps + 1)
    frac = np.concatenate([np.linspace(0, 1, k + 1) for k in steps])
    px = fg.x[u][edge] + frac * (fg.x[v] - fg.x[u])[edge]
    py = fg.y[u][edge] + frac * (fg.y[v] - fg.y[u])[edge]
    cols = np.clip(((px - x0) / RES_M).astype(int), 0, width - 1)
    rows = np.clip(((py - y0) / RES_M).astype(int), 0, height - 1)
    water = np.zeros((height, width), dtype=bool)
    water[rows, cols] = True
    water = ndimage.binary_closing(water, structure=np.ones((3, 3), bool), iterations=2)
    dist = ndimage.distance_transform_edt(water).astype(np.float32) * RES_M
    out = np.full(fg.n, SEA_CLEARANCE_M)
    i = np.flatnonzero(inland)
    r = np.clip(((fg.y[i] - y0) / RES_M).astype(int), 0, height - 1)
    c = np.clip(((fg.x[i] - x0) / RES_M).astype(int), 0, width - 1)
    # a cell at the edge of the drawing is one pixel from "not water": that pixel is the edge of
    # its lane's centre line, the water reaches half a lane beyond it
    out[i] = np.maximum(dist[r, c] - RES_M, 0.0) + lane_width(fg)[i] / 2
    out[special] = np.inf
    return out
