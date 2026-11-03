"""Traffic lanes in the buoyed channels: ships hold the starboard side of their channel and follow it.

Channels come from the lateral buoys of the chart (IALA A: the buoyage runs from the sea, so going
upstream / inbound the green buoys are to starboard and the red ones to port). Each named channel is
the union of the convex hulls of every WINDOW consecutive buoys along it, buffered by MARGIN_M:

    main        the main route: Hoofdvaarwater Westerschelde (the river's main fairway) and, at sea,
                Wielingen, Oostgat and Sardijngeul
    side        side channels of the Western Scheldt (Schaar van de Spijkerplaat, Everingen, Zuid
                Everingen, Middelgat, Vaarwater langs Hoofdplaat, ... langs de Paulinapolder)
    sea         secondary channels at sea (Deurloo, Geul van de Rassen, ...): drawn, not used for routing

On the river every cell gets its position across the main fairway, p: 0 on the line of red buoys,
1 on the line of green buoys, below 0 / above 1 beyond them. Each line joins its buoys in buoy-number
order (numbered from the sea), and

    inside      p = d_red / (d_red + d_green)          d = distance to the red / green line
    beyond red  p = -d_red / w,  beyond green  p = 1 + d_green / w      w = the channel's width there

which holds in any bend (measuring across the river axis instead mixed the sides up in the Bocht van
Bath, where the axis cuts the corner). The lines are resampled every RESAMPLE_M and smoothed with a
Gaussian of SMOOTH_SIGMA_M, so p changes smoothly through the bends instead of zigzagging from buoy to
buoy. Where there are no buoys (above the border) the fairway is a band around the axis and p is
measured across the axis per SLICE_M of chainage. In a side channel each cell gets its position across
that channel, pc, the same way from the channel's own buoys.

The lanes are where ships actually sail. From the AIS, the fixes of sea-going ships of AIS_MIN_LOA_M or
more under way (>= AIS_MIN_SOG_KN) on the main fairway are split by direction (course against the
upstream direction of the river there); per BIN_M along the channel (the smoothed centre line between
the buoy lines; above the buoys, the chainage) the median p of each direction is that direction's lane,
smoothed along the river and kept on its own half (upstream LANE_UP, downstream LANE_DOWN), so the
starboard rule holds. Where AIS is thin the lanes default to 0.75 / 0.25.

A ship holds a lane, a target position for its direction (upstream / downstream):

    profile   main fairway                         side channels   elsewhere on the river
    sea       the AIS lanes                        avoided         avoided (outside the fairway)
    wide      30 % closer to the middle            avoided         avoided      ULCVs, tide-dependent ships
    small     0.15 closer to the starboard edge    0.75 / 0.25     a little extra   sea-going ships <= 80 m
    inland    at or beyond the edge                0.75 / 0.25     a little extra   inland craft

and the routing cost of a move grows with the distance of the cell it moves to from that lane:

    sea, wide       f = 1 + ALPHA |p - t| + BETA [outside the fairway]
    small, inland   in a side channel: f = 1 + ALPHA |pc - t|;  in the main fairway: small as above
                    with its own targets, inland 1 + ALPHA max(0, 1 - p) upstream / max(0, p) downstream;
                    elsewhere 1 + GAMMA (prefer marked water)

Whether a ship can use a channel at all is the routing's depth rule (draught + UKC against depth +
water level); these costs only choose among the water deep enough. Moves across the river
(|cos| < CROSS_COS against the flow direction) cost their length alone. Cells without a lane (sea,
docks, canals) keep the plain keep-right rule (fast_graph.keep_right_factor).

    lanes = Lanes.for_graph(fg)          # cached in cache/lanes.npz
    lanes.factor(fg, "sea")              # per CSR entry, for FastGraph.route(lane_factor=...)
    lanes.layers(fg, axis, to_lonlat)    # channel outlines and lane lines for the viewer
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "cache" / "lanes.npz"
CHARTS = ROOT / "data" / "charts" / "scheldt_navigation.gpkg"
VERSION = 5
SLICE_M = 250.0
SMOOTH_SLICES = 5
CELL_HALF_M = 25.0                  # half the across-river cell size: the edge lies beyond the outer cells
WINDOW = 4                          # buoys per hull when outlining a channel
MARGIN_M = 60.0
MIN_BUOYS = 3
MAIN = {"HOOFDVAARWATER WESTERSCHELDE": "main", "WIELINGEN": "main", "OOSTGAT": "main", "SARDIJNGEUL": "main"}
NOT_CHANNELS = ("NOORDZEE",)        # offshore marks, not a channel
TARGET_UPSTREAM = {"sea": 0.75, "wide": 0.65, "small": 0.90, "inland": 1.0}
SIDE_TARGET_UPSTREAM = 0.75
CHANNEL_USERS = ("small", "inland")
ALPHA = 2.0                         # cost per unit off the lane: the far side of a channel costs ~2x
BETA = 0.5                          # extra outside the main fairway (sea, wide)
GAMMA = 0.3                         # extra in unmarked water (small, inland)
CROSS_COS = 0.3
MAX_FACTOR = 6.0                    # far from any lane the cost stops growing (no absurd detours)
RESAMPLE_M = 25.0                   # buoy lines resampled this finely ...
SMOOTH_SIGMA_M = 300.0              # ... and smoothed with this Gaussian
BIN_M = 500.0                       # AIS lanes per this much of channel
AIS_MIN_LOA_M, AIS_MIN_SOG_KN = 100.0, 5.0
AIS_MIN_FIXES = 6                   # per bin and direction
AIS_DIR_COS = 0.7
LANE_UP, LANE_DOWN = (0.55, 0.95), (0.05, 0.45)
WIDE_TOWARDS_MIDDLE = 0.3
SMALL_TOWARDS_EDGE = 0.15


# ---------------------------------------------------------------------------------------------
# channels from the buoys

def buoy_key(name):
    """Sort key: buoy number then suffix ("66C" -> (66, "C")); buoys are numbered from the sea."""
    import re
    m = re.search(r"(\d+)\s*([A-Za-z]?)", str(name))
    return (int(m.group(1)), m.group(2).upper()) if m else (10 ** 6, str(name))


def channel_buoys():
    """{channel name: lateral buoys (GeoDataFrame, UTM)} for the named channels."""
    import geopandas as gpd
    b = gpd.read_file(CHARTS, layer="buoys_nl").to_crs("EPSG:32631")
    b = b[b.category.str.startswith("lateral") & ~b.fairway.isin(NOT_CHANNELS)]
    return {name: g for name, g in b.groupby("fairway")}


def smooth_line(line, sigma_m=SMOOTH_SIGMA_M, step=RESAMPLE_M):
    """The line resampled every `step` m and smoothed with a Gaussian of sigma_m (ends kept)."""
    import shapely
    from shapely.geometry import LineString
    from scipy.ndimage import gaussian_filter1d
    n = max(int(line.length // step), 2)
    xy = shapely.get_coordinates(shapely.line_interpolate_point(line, np.linspace(0, line.length, n + 1)))
    sig = min(sigma_m, line.length / 6) / step
    if sig >= 1:
        xy = np.column_stack([gaussian_filter1d(xy[:, k], sig, mode="nearest") for k in (0, 1)])
    return LineString(xy)


def buoy_lines(g, smooth=True):
    """The red and green lines of a channel (shapely LineStrings in buoy-number order, smoothed), or None."""
    from shapely.geometry import LineString
    out = []
    for colour in ("red", "green"):
        c = g[g.colour == colour]
        if len(c) < 2:
            return None
        c = c.iloc[sorted(range(len(c)), key=lambda i: buoy_key(c.name.iloc[i]))]
        line = LineString(np.column_stack([c.geometry.x, c.geometry.y]))
        out.append(smooth_line(line) if smooth else line)
    return tuple(out)


def centre_line(red, green, step=100.0):
    """The smooth line midway between a channel's red and green lines (from the sea upstream)."""
    import shapely
    t = np.arange(0.0, red.length, step)
    r = shapely.get_coordinates(shapely.line_interpolate_point(red, t))
    g = shapely.get_coordinates(shapely.line_interpolate_point(green, shapely.line_locate_point(green, shapely.points(r))))
    return smooth_line(shapely.linestrings((r + g) / 2), sigma_m=SMOOTH_SIGMA_M)


def ais_lanes(fg, p, key):
    """Per bin (key: an integer per node, -1 none) the AIS median p of sea-going ships going upstream and
    downstream: {bin: (t_up, t_down)} (nan where AIS is thin)."""
    import sys
    from scipy.spatial import cKDTree
    from pyproj import Transformer
    sys.path.insert(0, str(ROOT / "src" / "data"))
    import ais_pipeline

    data = ais_pipeline.prepare()
    df = data.df
    df = df[(df.sog >= AIS_MIN_SOG_KN) & df.cog.notna() & (df.length >= AIS_MIN_LOA_M) & df.in_scheldt]
    cls = data.visits["class"]                                   # indexed by visit id
    df = df[df.visit.map(cls).isin(["container", "bulk_general", "tanker"])]
    x, y = Transformer.from_crs("EPSG:4326", "EPSG:32631", always_xy=True).transform(df.lon.to_numpy(), df.lat.to_numpy())
    cells = np.flatnonzero((key >= 0) & np.isfinite(p))
    d, j = cKDTree(np.column_stack([fg.x[cells], fg.y[cells]])).query(np.column_stack([x, y]))
    n = cells[j]
    ok = d < 120
    course = np.radians(df.cog.to_numpy())
    cos = np.sin(course) * fg.flow_dir[n, 0] + np.cos(course) * fg.flow_dir[n, 1]
    k, pp, c = key[n][ok], p[n][ok], cos[ok]
    out = {}
    for b in np.unique(k):
        sel = k == b
        up, down = pp[sel & (c > AIS_DIR_COS)], pp[sel & (c < -AIS_DIR_COS)]
        out[int(b)] = (float(np.median(up)) if len(up) >= AIS_MIN_FIXES else np.nan,
                       float(np.median(down)) if len(down) >= AIS_MIN_FIXES else np.nan)
    return out


def smooth_targets(bins, values, lo, hi, default):
    """A lane per bin: gaps filled from the neighbours, a rolling median and mean along the river,
    kept within [lo, hi]."""
    import pandas as pd
    if not len(bins):
        return np.array([])
    full = pd.Series(np.nan, index=np.arange(bins.min(), bins.max() + 1))
    full[bins] = values
    full = full.interpolate(limit_direction="both").fillna(default)
    full = full.rolling(5, center=True, min_periods=1).median().rolling(5, center=True, min_periods=1).mean()
    return np.clip(full.reindex(bins).to_numpy(), lo, hi)


def buoy_positions(red, green, x, y):
    """Position across a channel from its red and green lines (see the module docstring); nan where a
    point lies beyond the ends of the lines."""
    import shapely
    pts = shapely.points(x, y)
    d_r, d_g = shapely.distance(pts, red), shapely.distance(pts, green)
    t_r, t_g = shapely.line_locate_point(red, pts), shapely.line_locate_point(green, pts)
    w = shapely.distance(shapely.line_interpolate_point(red, t_r), green)
    w = np.maximum(w, 50.0)
    p = d_r / np.maximum(d_r + d_g, 1e-9)
    p = np.where(d_g >= d_r + 0.95 * w, -d_r / w, p)
    p = np.where(d_r >= d_g + 0.95 * w, 1.0 + d_g / w, p)
    ends = (t_r <= 1.0) | (t_r >= red.length - 1.0) | (t_g <= 1.0) | (t_g >= green.length - 1.0)
    return np.where(ends, np.nan, p)


def channel_outlines(fg):
    """{name: (shapely polygon in UTM, kind)} for every buoyed channel with MIN_BUOYS or more."""
    import geopandas as gpd
    import shapely
    from scipy.spatial import cKDTree

    b = gpd.read_file(CHARTS, layer="buoys_nl").to_crs("EPSG:32631")
    b = b[b.category.str.startswith("lateral") & ~b.fairway.isin(NOT_CHANNELS)]
    river = fg.mask("region", "river") & np.isfinite(fg.chainage_m)
    tree = cKDTree(np.column_stack([fg.x[river], fg.y[river]]))
    ch = fg.chainage_m[river]
    out = {}
    for name, g in b.groupby("fairway"):
        if len(g) < MIN_BUOYS:
            continue
        pts = np.column_stack([g.geometry.x, g.geometry.y])
        d, j = tree.query(pts)
        names = g.name.astype(str).tolist()
        if all(buoy_key(n)[0] < 10 ** 6 for n in names):   # numbered from the sea: that order
            order = sorted(range(len(names)), key=lambda i: buoy_key(names[i]))
        elif np.all(d < 1500):                       # along the river: order by chainage
            order = np.argsort(ch[j])
        else:                                        # at sea: along the channel's main direction
            c = pts - pts.mean(axis=0)
            order = np.argsort(c @ np.linalg.svd(c, full_matrices=False)[2][0])
        pts = pts[order]
        w = min(WINDOW, len(pts))
        hulls = [shapely.MultiPoint(pts[i:i + w]).convex_hull for i in range(len(pts) - w + 1)]
        poly = shapely.union_all(hulls).buffer(MARGIN_M)
        kind = MAIN.get(name) or ("side" if np.all(d < 1500) else "sea")
        out[name] = (poly, kind)
    return out


def _positions(fg, cells, river):
    """Position across the band of `cells` (bool per node), per SLICE_M of chainage: (p per node on the
    river, slice edges)."""
    import pandas as pd

    s, off = fg.chainage_m, fg.lane_offset_m
    n = int(np.nanmax(s[river]) // SLICE_M) + 1
    k = (s[cells] // SLICE_M).astype(int)
    lo, hi = np.full(n, np.nan), np.full(n, np.nan)
    np.fmin.at(lo, k, off[cells])
    np.fmax.at(hi, k, off[cells])
    has = np.isfinite(lo)
    lo = pd.Series(lo).rolling(SMOOTH_SLICES, center=True, min_periods=1).median()
    hi = pd.Series(hi).rolling(SMOOTH_SLICES, center=True, min_periods=1).median()
    lo = lo.interpolate(limit_direction="both").to_numpy() - CELL_HALF_M
    hi = hi.interpolate(limit_direction="both").to_numpy() + CELL_HALF_M
    p = np.full(fg.n, np.nan)
    j = np.clip((s[river] // SLICE_M).astype(int), 0, n - 1)
    p[river] = (off[river] - lo[j]) / np.maximum(hi[j] - lo[j], 50.0)
    return p, np.column_stack([(np.arange(n) + 0.5) * SLICE_M, lo, hi, has])


class Lanes:
    def __init__(self, p, edges, chan, pc, names, tu=None, td=None, lanes_xy=None):
        self.tu = tu if tu is not None else np.full(len(p), np.nan)      # per node: the AIS lane upstream
        self.td = td if td is not None else np.full(len(p), np.nan)      # ... and downstream
        self.lanes_xy = lanes_xy if lanes_xy is not None else {}        # lane lines (UTM) for the viewer
        self.p = p                   # per node: position across the main fairway (nan: no lane here)
        self.edges = edges           # main fairway: (slice chainage, left offset, right offset, has cells)
        self.chan = chan             # per node: index of its side channel in names, -1 none
        self.pc = pc                 # per node: position across its side channel
        self.names = names
        self._factor = {}

    @classmethod
    def for_graph(cls, fg, arrays_path=ROOT / "cache" / "antwerp_scheldt_graph.arrays.npz"):
        if CACHE.is_file() and Path(arrays_path).is_file() and CACHE.stat().st_mtime > Path(arrays_path).stat().st_mtime:
            z = np.load(CACHE, allow_pickle=False)
            if "version" in z.files and int(z["version"]) == VERSION and len(z["p"]) == fg.n:
                return cls(z["p"], z["edges"], z["chan"], z["pc"], [str(x) for x in z["names"]], z["tu"], z["td"],
                           {"inbound": z["lane_in"], "outbound": z["lane_out"]})
        lanes = cls.build(fg)
        np.savez_compressed(CACHE, version=VERSION, p=lanes.p, edges=lanes.edges, chan=lanes.chan, pc=lanes.pc,
                            names=np.array(lanes.names), tu=lanes.tu, td=lanes.td,
                            lane_in=lanes.lanes_xy["inbound"], lane_out=lanes.lanes_xy["outbound"])
        return lanes

    @classmethod
    def build(cls, fg):
        import shapely

        river = fg.mask("region", "river") & np.isfinite(fg.chainage_m) & np.isfinite(fg.lane_offset_m)
        fair = river & fg.fairway.astype(bool)
        p, edges = _positions(fg, fair, river)               # across the axis: kept above the last buoy
        buoys = channel_buoys()
        main = buoy_lines(buoys["HOOFDVAARWATER WESTERSCHELDE"])
        idx = np.flatnonzero(river)
        q = buoy_positions(*main, fg.x[idx], fg.y[idx])
        ok = np.isfinite(q)
        p[idx[ok]] = q[ok]
        # along-channel bins: on the smoothed centre line where buoyed, by chainage above the buoys
        centre = centre_line(*main)
        a = np.full(fg.n, np.nan)
        a[idx[ok]] = shapely.line_locate_point(centre, shapely.points(fg.x[idx[ok]], fg.y[idx[ok]]))
        nb = int(centre.length // BIN_M) + 1
        key = np.full(fg.n, -1, dtype=np.int64)
        key[idx[ok]] = (a[idx[ok]] // BIN_M).astype(int)
        upper = idx[~ok]
        key[upper] = nb + (fg.chainage_m[upper] // BIN_M).astype(int)
        lanes = ais_lanes(fg, p, key)
        tu, td = np.full(fg.n, np.nan), np.full(fg.n, np.nan)
        lines = {"inbound": [], "outbound": []}
        for part in (np.arange(0, nb), np.arange(nb, key.max() + 1)):
            bins = np.array([b for b in part if b in lanes])
            if not len(bins):
                continue
            up = smooth_targets(bins, np.array([lanes[b][0] for b in bins]), *LANE_UP, TARGET_UPSTREAM["sea"])
            dn = smooth_targets(bins, np.array([lanes[b][1] for b in bins]), *LANE_DOWN, 1 - TARGET_UPSTREAM["sea"])
            # per node: interpolated between bin centres along its part
            cells = np.flatnonzero(np.isin(key, part))
            along = (a[cells] if part[0] == 0 else fg.chainage_m[cells]) / BIN_M - (0 if part[0] == 0 else 0)
            centres = (bins - part[0]) + 0.5
            tu[cells] = np.interp(along, centres, up)
            td[cells] = np.interp(along, centres, dn)
            if part[0] == 0:                                 # lane lines along the buoyed channel
                t = centres * BIN_M
                c = shapely.get_coordinates(shapely.line_interpolate_point(centre, t))
                r = shapely.get_coordinates(shapely.line_interpolate_point(main[0], shapely.line_locate_point(main[0], shapely.points(c))))
                g = shapely.get_coordinates(shapely.line_interpolate_point(main[1], shapely.line_locate_point(main[1], shapely.points(c))))
                lines["inbound"].append(r + up[:, None] * (g - r))
                lines["outbound"].append(r + dn[:, None] * (g - r))
        lanes_xy = {k: np.vstack(v) if v else np.zeros((0, 2)) for k, v in lines.items()}
        chan = np.full(fg.n, -1, dtype=np.int64)
        pc = np.full(fg.n, np.nan)
        names = []
        for name, (poly, kind) in channel_outlines(fg).items():
            if kind != "side":
                continue
            cells = river & ~fair & shapely.contains_xy(poly, fg.x, fg.y) & (chan < 0)
            if cells.sum() < 3:
                continue
            q, _ = _positions(fg, cells, river)
            lines = buoy_lines(buoys[name]) if name in buoys else None
            if lines is not None:                            # from the channel's own buoys where it has both colours
                qb = np.full(fg.n, np.nan)
                qb[cells] = buoy_positions(*lines, fg.x[cells], fg.y[cells])
                q = np.where(np.isfinite(qb), qb, q)
            chan[cells] = len(names)
            pc[cells] = q[cells]
            names.append(name)
        return cls(p, edges, chan, pc, names, tu, td, lanes_xy)

    def factor(self, fg, profile="sea"):
        """Routing cost multiplier per CSR entry (move u -> v) for a lane profile (nan: no lane)."""
        if profile in self._factor:
            return self._factor[profile]
        rows, cols = fg.entry_rows, fg.indices
        dx, dy = fg.x[cols] - fg.x[rows], fg.y[cols] - fg.y[rows]
        cos = (dx * fg.flow_dir[rows, 0] + dy * fg.flow_dir[rows, 1]) / np.maximum(np.hypot(dx, dy), 1e-9)
        up, down = cos > CROSS_COS, cos < -CROSS_COS
        along = up | down
        p = self.p[cols]
        t_up = TARGET_UPSTREAM[profile]
        lane_up = np.where(np.isfinite(self.tu[cols]), self.tu[cols], TARGET_UPSTREAM["sea"])
        lane_dn = np.where(np.isfinite(self.td[cols]), self.td[cols], 1 - TARGET_UPSTREAM["sea"])
        if profile == "wide":
            lane_up, lane_dn = 0.5 + (1 - WIDE_TOWARDS_MIDDLE) * (lane_up - 0.5), 0.5 + (1 - WIDE_TOWARDS_MIDDLE) * (lane_dn - 0.5)
        elif profile == "small":
            lane_up, lane_dn = np.minimum(lane_up + SMALL_TOWARDS_EDGE, 1.0), np.maximum(lane_dn - SMALL_TOWARDS_EDGE, 0.0)
        target = np.where(up, lane_up, lane_dn) if profile != "inland" else np.where(up, t_up, 1.0 - t_up)
        inside = (p >= 0) & (p <= 1)
        if profile == "inland":                          # in the main fairway only being too far in costs
            main = 1.0 + ALPHA * np.where(up, np.maximum(0.0, 1.0 - p), np.maximum(0.0, p))
        else:
            main = 1.0 + ALPHA * np.abs(p - target) + BETA * ~inside
        f = main
        if profile in CHANNEL_USERS:
            side = self.chan[cols] >= 0
            ts = np.where(up, SIDE_TARGET_UPSTREAM, 1.0 - SIDE_TARGET_UPSTREAM)
            in_side = 1.0 + ALPHA * np.abs(self.pc[cols] - ts)
            unmarked = 1.0 + GAMMA + (main - 1.0 if profile == "inland" else 0.0)
            f = np.where(side, in_side, np.where(inside, main, unmarked))
        f = np.minimum(f, MAX_FACTOR)
        out = np.where(along & np.isfinite(p), f, np.where(np.isfinite(p), 1.0, np.nan))
        self._factor[profile] = out
        return out

    # -----------------------------------------------------------------------------------------
    # for the viewer

    def layers(self, fg, axis_xy, to_lonlat):
        """Channel outlines (name, kind, rings) and the main fairway's lane lines, in lat / lon."""
        import shapely
        from shapely.geometry import LineString

        def ll(xs, ys):
            lon, lat = to_lonlat(np.asarray(xs), np.asarray(ys))
            return [[round(float(b), 5), round(float(a), 5)] for a, b in zip(lon, lat)]

        channels = []
        for name, (poly, kind) in channel_outlines(fg).items():
            polys = list(poly.geoms) if poly.geom_type == "MultiPolygon" else [poly]
            rings = [ll(*q.simplify(15).exterior.xy) for q in polys]
            channels.append({"name": name.title(), "kind": kind, "rings": rings,
                             "used": name in self.names})
        red, green = buoy_lines(channel_buoys()["HOOFDVAARWATER WESTERSCHELDE"])
        buoyed = self.lanes_xy
        axis = LineString(axis_xy)
        last = max(shapely.line_locate_point(axis, shapely.points(red.coords[-1])),
                   shapely.line_locate_point(axis, shapely.points(green.coords[-1])))
        s, lo, hi, has = self.edges.T
        keep = (s < axis.length) & (has > 0) & (s > last)
        s, lo, hi = s[keep], lo[keep], hi[keep]
        pts = shapely.get_coordinates(shapely.line_interpolate_point(axis, s))
        a = shapely.get_coordinates(shapely.line_interpolate_point(axis, np.clip(s + 50, 0, axis.length)))
        b = shapely.get_coordinates(shapely.line_interpolate_point(axis, np.clip(s - 50, 0, axis.length)))
        t = a - b
        t /= np.maximum(np.hypot(t[:, 0], t[:, 1]), 1e-9)[:, None]
        normal = np.column_stack([t[:, 1], -t[:, 0]])          # right of the upstream direction
        lanes = {}
        # above the buoys: the AIS lane of the cells there, per slice
        river = np.isfinite(self.p) & np.isfinite(fg.chainage_m)
        for name, arr in (("inbound", self.tu), ("outbound", self.td)):
            q = np.full(len(s), np.nan)
            sl = (fg.chainage_m[river] // SLICE_M).astype(int)
            vals = arr[river]
            for k, ss in enumerate(s):
                m = (sl == int(ss // SLICE_M)) & np.isfinite(vals)
                if m.any():
                    q[k] = np.median(vals[m])
            default = TARGET_UPSTREAM["sea"] if name == "inbound" else 1 - TARGET_UPSTREAM["sea"]
            q = np.where(np.isfinite(q), q, default)
            xy = np.vstack([buoyed[name], pts + normal * (lo + q * (hi - lo))[:, None]])
            from scipy.ndimage import gaussian_filter1d
            xy = np.column_stack([gaussian_filter1d(xy[:, k], 2, mode="nearest") for k in (0, 1)])
            lanes[name] = ll(xy[:, 0], xy[:, 1])
        return {"channels": channels, "lanes": lanes}
