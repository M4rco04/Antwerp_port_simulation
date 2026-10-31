"""Build the navigation graph of the Scheldt for the simulation (PLAN.md §5, §8).

The graph is made of four kinds of grid, each laid only on water that ships use:

    sea     250 x 250 m, aligned to UTM: the open sea inside the AIS area, only where
            Scheldt-bound traffic sails (from the AIS data) and at the anchorages
    river   200 m along x 50 m across, following the fairway centreline (fitted to the AIS
            tracks of large ships): Western Scheldt from Vlissingen, Zeeschelde past Antwerp
    canal   the same curvilinear grid on the Ghent-Terneuzen canal, the Kanaal door
            Zuid-Beveland (Hansweert) and the Schelde-Rijnverbinding, up to the area edge
    port    50 x 50 m, aligned to UTM: Antwerp docks, Terneuzen, Vlissingen(-Oost), Breskens

The grids are joined by "link" edges. No edge crosses land: every edge is sampled every
few metres against the water mask (the depth chart, and OpenStreetMap water where the chart
has no data). Only the largest connected part is kept.

Every node has x, y (UTM 31N, m), longitude, latitude, region, zone, depth_m (m below LAT,
negative on drying banks), depth_source ("chart_LAT" or "nominal"), drying, is_berth,
berths (the slots_cords berth ids it serves) and terminal; graph.graph["berth_nodes"] maps a
berth id to its nodes. For the tide (tide.py): "tide" = (gauge_a, gauge_b, weight_b) on tidal
nodes, "basin" = the basin behind locks otherwise, and "tide_gauge" = the nearest gauge. For the
currents (currents.py): tidal river/port nodes get "chainage_m" (along the estuary axis from the
mouth) and "flow_dir" (unit vector pointing upstream, i.e. the flood direction).

Every lock is ONE node (type "lock", region "lock"): the grid cells inside its chambers are
removed, and "lock_gate" edges join the lock node to the water at both ends of each chamber
(depth = the chamber's sill). The node's "lock" attribute is a locks.Lock object with the
chambers, the two sides, the queues, the packing and the lock cycle (PLAN.md §7); see
locks.py. graph.graph["locks"] maps a lock name to its node. Unpickling the graph needs
src/environment on sys.path (for locks.py). Every edge has weight (length, m), depth_m (its shallowest point) and kind.
find_route() is A* that never uses an edge shallower than the ship's draught + UKC.

Usage:
    py src/environment/antwerp_port.py --no-browser
"""

from __future__ import annotations

import argparse
import collections
import json
import logging
import math
import pickle
import sys
import time
import webbrowser
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
import rasterio
import shapely
import shapely.ops
from pyproj import Transformer
from scipy import ndimage
from shapely.geometry import LineString, Polygon

from locks import Chamber, Lock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEPTH_RASTER = PROJECT_ROOT / "data" / "charts" / "scheldt_depth_LAT_wgs84.tif"
DEPTH_SOURCE_RASTER = PROJECT_ROOT / "data" / "charts" / "scheldt_depth_source_wgs84.tif"
CHARTS = PROJECT_ROOT / "data" / "charts" / "scheldt_navigation.gpkg"
SLOT_DATA = PROJECT_ROOT / "slots_cords" / "paczka_final.json"
OSM_CACHE = PROJECT_ROOT / "cache" / "osm"
OSM_WATER_FILE = PROJECT_ROOT / "cache" / "osm_water.gpkg"
DEFAULT_OUTPUT = PROJECT_ROOT / "cache" / "antwerp_scheldt_graph.pkl"
DEFAULT_HTML = PROJECT_ROOT / "cache" / "antwerp_scheldt_graph.html"
PROJECTED_CRS = "EPSG:32631"
GEOGRAPHIC_CRS = "EPSG:4326"

log = logging.getLogger("graph")

TO_UTM = Transformer.from_crs(GEOGRAPHIC_CRS, PROJECTED_CRS, always_xy=True).transform
TO_LONLAT = Transformer.from_crs(PROJECTED_CRS, GEOGRAPHIC_CRS, always_xy=True).transform

# grid spacing (m)
SEA_SPACING = 250.0
RIVER_ALONG, RIVER_ACROSS = 200.0, 50.0
PORT_SPACING = 50.0
# the AIS area (collector corners, lat/lon), grids are clipped to it plus a margin
AIS_AREA = [(51.388833, 2.517167), (51.718, 2.611333), (51.467, 4.299667), (51.180167, 4.433833)]
AREA_MARGIN_M = 1000.0
# OSM water is widened by this much, so 50 m grids get through narrow lock chambers
OSM_WATER_TOLERANCE_M = 20.0
# an edge is checked against the water mask at this many points
EDGE_SAMPLES = 11
# a channel grid row stops after this many land points in a row
CHANNEL_MAX_GAP = 2
# grid nodes this close to a node of a finer-priority grid are dropped, and joined by links
OVERLAP_M = {"channel": 110.0, "port": 110.0, "sea": 130.0}
# neighbouring grids are joined by links up to this long (longer when the sea grid is involved)
LINK_RADIUS_M = {"default": 250.0, "sea": 330.0}
LINKS_PER_NODE = 2
# sea cells within this many cells of observed traffic are kept
SEA_TRAFFIC_DILATION_CELLS = 4
ANCHORAGE_MARGIN_M = 500.0

# (lon, lat) waypoints; the centrelines are fitted to AIS tracks from here.
# max_offset_m: how far the grid reaches across from the centreline (with zone overrides).
CHANNELS = {
    "western_scheldt": {
        "region": "river", "corridor_m": 1200.0, "bin_m": 400.0, "smooth_m": 2000.0, "min_length": 200,
        "max_offset_m": 4500.0, "force_centre": False,
        "waypoints": [
            (3.50, 51.420), (3.56, 51.432), (3.60, 51.441), (3.635, 51.448), (3.665, 51.451), (3.69, 51.44),
            (3.71, 51.42), (3.735, 51.40), (3.76, 51.38), (3.79, 51.362), (3.82, 51.352), (3.85, 51.349),
            (3.88, 51.352), (3.91, 51.362), (3.94, 51.378), (3.96, 51.40), (3.975, 51.425), (3.995, 51.437),
            (4.015, 51.437), (4.03, 51.425), (4.035, 51.405), (4.045, 51.385), (4.07, 51.377), (4.11, 51.373),
            (4.15, 51.378), (4.18, 51.392), (4.20, 51.398), (4.215, 51.385), (4.232, 51.365), (4.25, 51.355),
        ],
    },
    # tighter bends past Antwerp: its own, less smoothed centreline. The two overlap by a few km
    # (smoothing shortens a centreline at its ends), and the overlap is joined by links.
    # within_river: fitted to, and laid on, the OSM river outline only (never into the docks)
    "zeeschelde": {
        "region": "river", "corridor_m": 400.0, "bin_m": 200.0, "smooth_m": 400.0, "min_length": 0,
        "max_offset_m": 1500.0, "force_centre": False, "within_river": True,
        "waypoints": [
            (4.205, 51.396), (4.215, 51.383), (4.230, 51.364), (4.255, 51.348), (4.270, 51.338), (4.278, 51.325),
            (4.280, 51.310), (4.283, 51.300), (4.292, 51.295), (4.302, 51.291), (4.311, 51.287), (4.316, 51.281),
            (4.311, 51.274), (4.305, 51.268), (4.302, 51.261), (4.309, 51.255), (4.322, 51.251), (4.338, 51.247),
            (4.352, 51.244), (4.367, 51.241), (4.382, 51.240), (4.393, 51.238), (4.398, 51.230), (4.395, 51.220),
            (4.387, 51.211), (4.375, 51.205), (4.360, 51.200), (4.345, 51.195), (4.335, 51.188), (4.330, 51.175),
        ],
    },
    "ghent_terneuzen_canal": {
        "region": "canal", "corridor_m": 300.0, "bin_m": 200.0, "smooth_m": 400.0, "min_length": 0,
        "max_offset_m": 150.0, "force_centre": True,
        "waypoints": [(3.818, 51.338), (3.822, 51.33), (3.828, 51.318), (3.832, 51.30), (3.837, 51.287),
                      (3.84, 51.277), (3.836, 51.266), (3.828, 51.257), (3.818, 51.246), (3.808, 51.235)],
    },
    "zuid_beveland_canal": {
        "region": "canal", "corridor_m": 300.0, "bin_m": 200.0, "smooth_m": 400.0, "min_length": 0,
        "max_offset_m": 150.0, "force_centre": True,
        "waypoints": [(4.006, 51.440), (4.009, 51.447), (4.009, 51.455), (4.003, 51.465), (3.998, 51.478),
                      (3.998, 51.49), (4.001, 51.50), (4.006, 51.507), (4.012, 51.513), (4.02, 51.52)],
    },
    "schelde_rijn_canal": {
        "region": "canal", "corridor_m": 300.0, "bin_m": 200.0, "smooth_m": 400.0, "min_length": 0,
        "max_offset_m": 150.0, "force_centre": True,
        "waypoints": [(4.296, 51.373), (4.28, 51.376), (4.262, 51.379), (4.248, 51.386), (4.24, 51.40),
                      (4.236, 51.42), (4.232, 51.44), (4.229, 51.46), (4.226, 51.48), (4.224, 51.49)],
    },
}
# where the chart's harbour/lock cells are unusable (shallow artefacts at the Terneuzen lock
# gates): no river grid there, the port grid with its nominal depth covers it instead
RIVER_EXCLUDED = [(3.805, 51.322, 3.83, 51.334)]
# the Belgian-Dutch border on the Scheldt: upriver of it the chart only has edge artefacts and
# coarse EMODnet cells, so the Belgian river always gets its nominal depth
BORDER_LAT = 51.365
NOMINAL_ONLY_ZONES = ("zeeschelde", "upper_sea_scheldt")

# port grids: (lon_min, lat_min, lon_max, lat_max)
PORTS = {
    "antwerp": (4.17, 51.17, 4.46, 51.40),
    "terneuzen": (3.78, 51.322, 3.88, 51.35),
    "vlissingen": (3.54, 51.435, 3.76, 51.475),
    "breskens": (3.53, 51.388, 3.58, 51.405),
}
# not port: the Verdronken Land van Saeftinghe and the Doel flats west of the river, which OSM
# maps as water
PORT_EXCLUDED = [(4.15, 51.305, 4.255, 51.40), (4.25, 51.322, 4.267, 51.346)]
# where OpenStreetMap water is fetched (and trusted over the chart)
OSM_AREAS = {
    "antwerp": (4.15, 51.16, 4.47, 51.42),
    "schelde_rijn": (4.19, 51.37, 4.32, 51.50),
    "hansweert": (3.96, 51.43, 4.06, 51.53),
    "terneuzen": (3.76, 51.22, 3.92, 51.36),
    "vlissingen": (3.52, 51.38, 3.78, 51.48),
}
OSM_TAGS = {"natural": "water", "waterway": ["riverbank", "dock", "canal", "lock"]}
# Overpass times out on big boxes: download in tiles of at most this size (degrees)
OSM_TILE_DEG = (0.16, 0.13)
OSM_RETRIES = 6
# public Overpass servers, tried in turn when one is overloaded
OVERPASS_URLS = ("https://overpass-api.de/api", "https://overpass.kumi.systems/api",
                 "https://overpass.private.coffee/api")

# Antwerp docks by quay number (slots_cords LPL), for the nominal depths
ANTWERP_DOCKS = [
    (1, 199, "antwerp_city_docks"),
    (200, 599, "antwerp_central_docks"),
    (600, 799, "antwerp_north_docks"),
    (800, 999, "zeeschelde"),
    (1100, 1699, "antwerp_left_bank_docks"),
    (1700, 1799, "antwerp_deurganckdok"),
]

# Approximate depths (m below LAT) where the chart has no data: the published maximum
# draught + ~10 % UKC, or the lock sill (port_regulations_agent_rules.md §8, §17;
# alokacja_przestrzenna_w_terminalach.md). Replace with charted values when available.
NOMINAL_DEPTH_M = {
    "western_scheldt": 12.0,           # only used where the chart has a hole
    "zeeschelde": 14.5,                # tide-independent draught 13.10 m
    "upper_sea_scheldt": 8.8,          # berths upstream of Kallo: 8.0 m
    "antwerp_city_docks": 6.4,         # Royers lock sill -6.42 m TAW
    "antwerp_central_docks": 10.3,     # Boudewijn lock sill -10.33 m TAW
    "antwerp_north_docks": 13.6,       # Berendrecht / Zandvliet sills -13.6 m TAW
    "antwerp_left_bank_docks": 14.0,   # Kallo -12.58 / Kieldrecht -17.8 m TAW
    "antwerp_deurganckdok": 18.7,      # MPET / Antwerp Gateway draught 17.0 m
    "antwerp_other": 10.3,
    "ghent_terneuzen_canal": 13.75,    # draught 12.5 m
    "terneuzen": 13.75,
    "zuid_beveland_canal": 6.0,        # CEMT VIb
    "schelde_rijn_canal": 6.0,         # CEMT VIb
    "vlissingen": 14.0,
    "breskens": 4.0,
}

# container terminals: berth polygons in slots_cords with this TERMINAL code
TERMINALS = (
    {"name": "MPET", "code": "1700", "quay_m": 3700, "draft_m": 17.0, "capacity": "9 ULCV / 12-14 mieszanych"},
    {"name": "DP World Antwerp Gateway", "code": "1742", "quay_m": 2500, "draft_m": 17.0,
     "capacity": "6 ULCV / 8-10 mieszanych"},
    {"name": "PSA Noordzee Terminal", "code": "S913", "quay_m": 1225, "draft_m": 17.0, "capacity": "3 ULCV"},
    {"name": "PSA Europa Terminal", "code": "S869", "quay_m": 1180, "draft_m": 16.0, "capacity": "2-3 duże statki"},
)
BERTH_SNAP_M = 60.0

# Locks (PLAN.md §7). Per chamber: name, OSM way id of its centreline (or its (lon, lat) points
# where OSM has none), length x width (m; None =
# the OSM centreline length), sill depth (m below TAW, taken as LAT: about 0.5 m off) and the source
# (regs = port_regulations_agent_rules.md §17; nominal = the canal's nominal depth, to replace).
LOCKS = {
    "Berendrecht": {"preferred_min_beam_m": 43.0,
                    "chambers": [("Berendrecht", 185465548, 500, 68, 13.6, "regs")]},
    "Zandvliet": {"chambers": [("Zandvliet", 185465550, 500, 57, 13.6, "regs")]},
    "Kieldrecht": {"chambers": [("Kieldrecht", 365506065, 500, 68, 17.8, "regs")]},
    "Kallo": {"chambers": [("Kallo", 195720347, 310, 50, 12.58, "regs")]},   # 310 m between inner gates
    "Boudewijn": {"chambers": [("Boudewijn", 195718562, 360, 45, 10.33, "regs")]},
    "Van Cauwelaert": {"chambers": [("Van Cauwelaert", 195718563, 270, 35, 9.83, "regs")]},
    # OSM maps only Royers' outer harbour (way 195722543); the chamber runs from its head to Amerikadok
    "Royers": {"chambers": [("Royers", [(4.3993, 51.2399), (4.3992, 51.2431)], 180, 22, 6.42, "regs")]},
    "Kattendijk": {"chambers": [("Kattendijk", 493501022, None, 25, 6.4, "nominal")]},
    "Kreekrak": {"chambers": [("Kreekrak west", 375938969, 320, 24, 6.0, "nominal"),
                              ("Kreekrak east", 375938971, 320, 24, 6.0, "nominal")]},
    "Hansweert": {"chambers": [("Hansweert west", 250756276, 280, 24, 6.0, "nominal"),
                               ("Hansweert east", 250756275, 280, 24, 6.0, "nominal")]},
    "Terneuzen": {"chambers": [("Terneuzen new lock", 814596856, 427, 55, 13.75, "nominal"),
                               ("Terneuzen west lock", 661754736, 290, 40, 13.75, "nominal"),
                               ("Terneuzen east lock", 661754735, 260, 24, 6.0, "nominal")]},
    "Vlissingen (Kanaal door Walcheren)": {"chambers": [("Walcheren canal lock", 491657969, None, 24, 6.0, "nominal"),
                                                         ("Walcheren canal small lock", 491657979, None, 10, 3.0, "nominal")]},
}
# tide gauges (fetch_tide_data.py): along the estuary, and at sea
RIVER_GAUGES = ("vlissingen", "terneuzen", "hansweert", "walsoorden", "schaarvandenoord", "rilland.bath",
                "fortliefkenshoek", "kallosluis.schelde", "antwerpen.loodsgebouw")
SEA_GAUGES = ("westkapelle", "cadzand.2", "vlissingen")
# routing cost of passing a lock, as an equivalent distance (~45 min at 7 kn)
LOCK_PASSAGE_PENALTY_M = 10_000.0
# a chamber end is joined to the nearest water nodes within this distance
GATE_REACH_M = 300.0
GATE_LINKS_PER_END = 3
# more edges than this between the two sides of a lock means they really are the same water
SEAL_MAX_CUT = 60
TIDAL_ZONES = ("western_scheldt", "zeeschelde", "upper_sea_scheldt", "antwerp_deurganckdok", "terneuzen", "vlissingen")


# ---------------------------------------------------------------------------
# inputs


def utm_box(lon0, lat0, lon1, lat1):
    xs, ys = TO_UTM([lon0, lon1, lon1, lon0], [lat0, lat0, lat1, lat1])
    return Polygon(zip(xs, ys))


def ais_area():
    lat, lon = zip(*AIS_AREA)
    return Polygon(zip(*TO_UTM(lon, lat)))


class Chart:
    """The depth raster (m below LAT, NaN on land) and its source raster (1 = Rijkswaterstaat 20 m,
    2 = EMODnet ~115 m)."""

    def __init__(self, depth_path=DEPTH_RASTER, source_path=DEPTH_SOURCE_RASTER):
        with rasterio.open(depth_path) as src:
            self.depth = src.read(1).astype(np.float32)
            self.depth_inv = ~src.transform
            if src.nodata is not None and not np.isnan(src.nodata):
                self.depth[self.depth == src.nodata] = np.nan
        with rasterio.open(source_path) as src:
            self.source = src.read(1)
            self.source_inv = ~src.transform

    @staticmethod
    def _pick(array, inv, lon, lat, fill):
        col, row = inv * (lon, lat)
        col, row = np.floor(col).astype(np.int64), np.floor(row).astype(np.int64)
        ok = (row >= 0) & (row < array.shape[0]) & (col >= 0) & (col < array.shape[1])
        out = np.full(len(lon), fill, dtype=np.float64)
        out[ok] = array[row[ok], col[ok]]
        return out

    def sample(self, x, y):
        lon, lat = TO_LONLAT(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
        depth = self._pick(self.depth, self.depth_inv, lon, lat, np.nan)
        source = self._pick(self.source, self.source_inv, lon, lat, 0).astype(np.int8)
        return depth, source


def _osm_tiles():
    for lon0, lat0, lon1, lat1 in OSM_AREAS.values():
        xs = np.linspace(lon0, lon1, math.ceil(round((lon1 - lon0) / OSM_TILE_DEG[0], 6)) + 1)
        ys = np.linspace(lat0, lat1, math.ceil(round((lat1 - lat0) / OSM_TILE_DEG[1], 6)) + 1)
        for x0, x1 in zip(xs, xs[1:]):
            for y0, y1 in zip(ys, ys[1:]):
                yield tuple(round(float(v), 4) for v in (x0, y0, x1, y1))


def fetch_osm_water(refresh=False):
    """OSM water polygons in OSM_AREAS (UTM) and the lock centrelines (osm_id, name, geometry),
    read from OSM_WATER_FILE or downloaded tile by tile."""
    if OSM_WATER_FILE.is_file() and not refresh and "river" in gpd.list_layers(OSM_WATER_FILE).name.values:
        water = gpd.read_file(OSM_WATER_FILE, layer="water").to_crs(PROJECTED_CRS)
        lock_lines = gpd.read_file(OSM_WATER_FILE, layer="lock_lines").to_crs(PROJECTED_CRS)
        river = gpd.read_file(OSM_WATER_FILE, layer="river").to_crs(PROJECTED_CRS)
        return shapely.union_all(water.geometry.values), lock_lines, shapely.union_all(river.geometry.values)
    ox.settings.cache_folder = str(OSM_CACHE)
    ox.settings.use_cache = True
    ox.settings.requests_timeout = 180
    parts, lines, rivers = [], [], []
    tiles = list(_osm_tiles())
    for i, bounds in enumerate(tiles, 1):
        for attempt in range(1, OSM_RETRIES + 1):
            ox.settings.overpass_url = OVERPASS_URLS[(attempt - 1) % len(OVERPASS_URLS)]
            try:
                log.info("OSM water tile %d/%d %s from %s", i, len(tiles), bounds, ox.settings.overpass_url)
                water = ox.features_from_bbox(bbox=bounds, tags=OSM_TAGS)
                break
            except Exception as e:  # Overpass is flaky: timeouts, rate limits, dropped connections
                if attempt == OSM_RETRIES:
                    raise
                log.warning("Tile failed (%s), retrying", str(e)[:120])
                time.sleep(20 * attempt)
        is_lock = water.get("lock", pd.Series(index=water.index, dtype=object)).eq("yes")
        is_lock |= water.get("waterway", pd.Series(index=water.index, dtype=object)).eq("lock")
        is_lock |= water.get("name", pd.Series(index=water.index, dtype=object)).fillna("").str.endswith("sluis")
        line = water[is_lock & water.geom_type.eq("LineString")]
        lines.append(gpd.GeoDataFrame({"osm_id": [i for _, i in line.index], "name": line.get("name")},
                                      geometry=line.geometry.values, crs=line.crs).to_crs(PROJECTED_CRS))
        water = water[water.geom_type.isin(["Polygon", "MultiPolygon"])]
        parts.append(water.to_crs(PROJECTED_CRS).geometry)
        is_river = water.get("water", pd.Series(index=water.index, dtype=object)).eq("river")
        is_river |= water.get("waterway", pd.Series(index=water.index, dtype=object)).eq("riverbank")
        rivers.append(water[is_river].to_crs(PROJECTED_CRS).geometry)
    merged = shapely.union_all(np.concatenate([p.values for p in parts]))
    river = shapely.union_all(np.concatenate([r.values for r in rivers]))
    lock_lines = pd.concat(lines).drop_duplicates("osm_id")
    gpd.GeoDataFrame(geometry=[merged], crs=PROJECTED_CRS).to_file(OSM_WATER_FILE, layer="water")
    lock_lines.to_file(OSM_WATER_FILE, layer="lock_lines")
    gpd.GeoDataFrame(geometry=[river], crs=PROJECTED_CRS).to_file(OSM_WATER_FILE, layer="river")
    log.info("Saved %s", OSM_WATER_FILE)
    return merged, lock_lines, river


class Water:
    """Water mask: the chart, and OSM water inside OSM_AREAS (where it is trusted over the
    coarse EMODnet cells; Rijkswaterstaat chart cells count everywhere)."""

    def __init__(self, chart, osm_water, osm_river):
        self.chart = chart
        self.osm = osm_water.buffer(OSM_WATER_TOLERANCE_M)
        self.river = osm_river.buffer(OSM_WATER_TOLERANCE_M)
        self.osm_areas = shapely.union_all([utm_box(*b) for b in OSM_AREAS.values()])
        for geom in (self.osm, self.river, self.osm_areas):
            shapely.prepare(geom)

    def in_river(self, x, y):
        """Inside the OSM river outline (the Scheldt itself, not its docks)."""
        return shapely.contains_xy(self.river, np.asarray(x, dtype=float), np.asarray(y, dtype=float))

    def classify(self, x, y):
        x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
        depth, source = self.chart.sample(x, y)
        in_osm_area = shapely.contains_xy(self.osm_areas, x, y)
        in_osm = np.zeros(len(x), dtype=bool)
        in_osm[in_osm_area] = shapely.contains_xy(self.osm, x[in_osm_area], y[in_osm_area])
        chart_water = np.isfinite(depth) & ((source == 1) | ~in_osm_area)
        return chart_water | in_osm, depth, source


def scheldt_traffic():
    """Positions of the simulated ship classes on Scheldt-bound visits (src/data/ais_pipeline.py)."""
    sys.path.insert(0, str(PROJECT_ROOT / "src" / "data"))
    import ais_pipeline

    data = ais_pipeline.prepare()
    visits = data.visits
    keep = visits.index[visits.scheldt_bound & visits["class"].isin(ais_pipeline.SIMULATED_CLASSES)]
    df = data.df[data.df.visit.isin(keep)]
    x, y = TO_UTM(df.lon.to_numpy(), df.lat.to_numpy())
    return {"x": x, "y": y, "sog": df.sog.fillna(0).to_numpy(), "length": df.length.fillna(0).to_numpy()}


# ---------------------------------------------------------------------------
# centrelines


def _resample(line, step):
    distances = np.arange(0.0, line.length, step)
    distances = np.append(distances, line.length)
    return shapely.get_coordinates(shapely.line_interpolate_point(line, distances))


def _tangents(line, s, h=25.0):
    a = shapely.get_coordinates(shapely.line_interpolate_point(line, np.clip(s - h, 0, line.length)))
    b = shapely.get_coordinates(shapely.line_interpolate_point(line, np.clip(s + h, 0, line.length)))
    t = b - a
    return t / np.linalg.norm(t, axis=1, keepdims=True)


def fit_centreline(spec, traffic, water, iterations=3):
    """Pull the waypoint line onto the median AIS track: per bin along the line, the median
    sideways offset of the moving ships near it, smoothed."""
    lon, lat = zip(*spec["waypoints"])
    line = LineString(zip(*TO_UTM(lon, lat)))
    moving = (traffic["sog"] > 2) & (traffic["length"] >= spec["min_length"])
    if spec.get("within_river"):
        moving &= water.in_river(traffic["x"], traffic["y"])
    points = shapely.points(traffic["x"][moving], traffic["y"][moving])
    for _ in range(iterations):
        dense = _resample(line, 50.0)
        line = LineString(dense)
        near = points[shapely.distance(line, points) < spec["corridor_m"]]
        if len(near) < 20:
            break
        s = shapely.line_locate_point(line, near)
        foot = shapely.get_coordinates(shapely.line_interpolate_point(line, s))
        t = _tangents(line, s)
        rel = shapely.get_coordinates(near) - foot
        offset = t[:, 0] * rel[:, 1] - t[:, 1] * rel[:, 0]          # positive to the left
        n_bins = int(line.length // spec["bin_m"]) + 1
        bins = np.minimum((s // spec["bin_m"]).astype(int), n_bins - 1)
        median = np.full(n_bins, np.nan)
        for b in np.unique(bins):
            sel = offset[bins == b]
            if len(sel) >= 5:
                median[b] = np.median(sel)
        valid = np.isfinite(median)
        if not valid.any():
            break
        centres = (np.arange(n_bins) + 0.5) * spec["bin_m"]
        median = np.interp(centres, centres[valid], median[valid])
        median = ndimage.gaussian_filter1d(median, spec["smooth_m"] / spec["bin_m"], mode="nearest")
        s_dense = shapely.line_locate_point(line, shapely.points(dense))
        t_dense = _tangents(line, s_dense)
        shift = np.interp(s_dense, centres, median)
        dense = dense + shift[:, None] * np.column_stack([-t_dense[:, 1], t_dense[:, 0]])
        sigma = spec["smooth_m"] / 50.0
        dense = np.column_stack([ndimage.gaussian_filter1d(dense[:, i], sigma, mode="nearest") for i in (0, 1)])
        line = LineString(dense)
    return line


# ---------------------------------------------------------------------------
# grids


class Builder:
    def __init__(self, water, area):
        self.water = water
        self.area = area
        self.x, self.y, self.region, self.zone, self.grid = [], [], [], [], []
        self.edges = []          # (a, b, kind, exempt from the water check)

    def add_nodes(self, x, y, region, zone, grid):
        start = sum(len(a) for a in self.x)
        self.x.append(np.asarray(x, dtype=float))
        self.y.append(np.asarray(y, dtype=float))
        self.region.append(np.full(len(x), region, dtype=object))
        self.zone.append(np.asarray(zone, dtype=object) if not isinstance(zone, str)
                         else np.full(len(x), zone, dtype=object))
        self.grid.append(np.full(len(x), grid, dtype=object))
        return np.arange(start, start + len(x))

    def arrays(self):
        return (np.concatenate(self.x), np.concatenate(self.y), np.concatenate(self.region),
                np.concatenate(self.zone))

    def far_from(self, x, y, regions, distance):
        """Mask of the points farther than distance from every node of these regions."""
        if not self.x:
            return np.ones(len(x), dtype=bool)
        X, Y, R, _ = self.arrays()
        ref = np.isin(R, regions)
        if not ref.any():
            return np.ones(len(x), dtype=bool)
        tree = shapely.STRtree(shapely.points(X[ref], Y[ref]))
        hit = tree.query(shapely.points(x, y), predicate="dwithin", distance=distance)[0]
        keep = np.ones(len(x), dtype=bool)
        keep[hit] = False
        return keep

    def in_area(self, x, y):
        return shapely.contains_xy(self.area, x, y)


def channel_grid(builder, name, spec, line):
    """Curvilinear grid along a centreline: stations every RIVER_ALONG, lanes every RIVER_ACROSS,
    each lane reaching out from the centre while there is water."""
    s = np.arange(0.0, line.length, RIVER_ALONG)
    centre = shapely.get_coordinates(shapely.line_interpolate_point(line, s))
    t = _tangents(line, s, h=50.0)
    normal = np.column_stack([-t[:, 1], t[:, 0]])
    theta = np.unwrap(np.arctan2(t[:, 1], t[:, 0]))
    kappa = ndimage.gaussian_filter1d(np.gradient(theta, s), 500.0 / RIVER_ALONG, mode="nearest")

    max_offset = np.full(len(s), spec["max_offset_m"])
    J = int(max_offset.max() // RIVER_ACROSS)
    lanes = np.arange(-J, J + 1)
    X = centre[:, 0, None] + lanes[None, :] * RIVER_ACROSS * normal[:, 0, None]
    Y = centre[:, 1, None] + lanes[None, :] * RIVER_ACROSS * normal[:, 1, None]
    offset = np.abs(lanes)[None, :] * RIVER_ACROSS
    inner = (lanes[None, :] * kappa[:, None]) > 0
    # on the inside of a bend the lanes would cross beyond the radius of curvature
    allowed = (offset <= max_offset[:, None]) & ~(inner & (offset * np.abs(kappa)[:, None] > 0.8))
    # and wherever a lane stops moving forward along the river the grid folds over itself
    forward = (X[1:] - X[:-1]) * t[:-1, 0, None] + (Y[1:] - Y[:-1]) * t[:-1, 1, None]
    folded = forward < 0.5 * RIVER_ALONG
    allowed[:-1] &= ~folded
    allowed[1:] &= ~folded
    allowed &= builder.in_area(X.ravel(), Y.ravel()).reshape(X.shape)
    if spec["region"] == "river":
        lon, lat = TO_LONLAT(X, Y)
        for lon0, lat0, lon1, lat1 in RIVER_EXCLUDED:
            allowed &= ~((lon >= lon0) & (lon <= lon1) & (lat >= lat0) & (lat <= lat1))
    wet = builder.water.classify(X.ravel(), Y.ravel())[0].reshape(X.shape)
    if spec.get("within_river"):
        wet &= builder.water.in_river(X.ravel(), Y.ravel()).reshape(X.shape)

    keep = np.zeros_like(wet)
    for k in range(len(s)):
        for side in (1, -1):
            gap = 0
            for jj in range(0, J + 1):
                col = J + side * jj
                if not allowed[k, col]:
                    break
                if wet[k, col]:
                    keep[k, col], gap = True, 0
                else:
                    gap += 1
                    if gap > CHANNEL_MAX_GAP:
                        break
    if spec["force_centre"]:
        keep[:, J] |= allowed[:, J]
    # where an earlier channel already lies, it keeps the water (the grids are linked later)
    keep &= builder.far_from(X.ravel(), Y.ravel(), ["river", "canal"], OVERLAP_M["channel"]).reshape(X.shape)

    index = np.full(X.shape, -1)
    k_idx, j_idx = np.nonzero(keep)
    zone = river_zones(X[keep], Y[keep]) if spec["region"] == "river" else name
    index[k_idx, j_idx] = builder.add_nodes(X[keep], Y[keep], spec["region"], zone, name)
    for (dk, dj), a, b, first_col in neighbour_pairs(index):
        both = (a >= 0) & (b >= 0)
        exempt = np.zeros_like(both)
        if spec["force_centre"] and (dk, dj) == (1, 0):
            exempt[:, J - first_col] = True          # the centre lane follows the ship tracks
        builder.edges.extend((int(u), int(v), spec["region"], bool(e))
                             for u, v, e in zip(a[both], b[both], exempt[both]))
    log.info("%s: %d stations, %d nodes", name, len(s), int(keep.sum()))


def river_zones(x, y):
    lon, lat = TO_LONLAT(x, y)
    zone = np.full(len(x), "western_scheldt", dtype=object)
    zone[(lon > 4.2) & (lat < BORDER_LAT)] = "zeeschelde"
    zone[(lon > 4.3) & (lat < 51.225)] = "upper_sea_scheldt"
    return zone


def square_grid(builder, bounds_utm, spacing, keep_fn):
    """UTM-aligned grid of the points keep_fn accepts, with 8-neighbour edges."""
    x0, y0, x1, y1 = bounds_utm
    xs = np.arange(math.floor(x0 / spacing) * spacing, x1 + spacing, spacing)
    ys = np.arange(math.floor(y0 / spacing) * spacing, y1 + spacing, spacing)
    X, Y = np.meshgrid(xs, ys)
    keep = keep_fn(X.ravel(), Y.ravel()).reshape(X.shape)
    return X, Y, keep


def neighbour_pairs(index):
    """For each of the 4 forward neighbour directions of a 2-D index grid: the direction, the
    node ids of both ends (-1 = no node) and the first column of the 'a' window."""
    rows, cols = index.shape
    for di, dj in ((0, 1), (1, 0), (1, 1), (1, -1)):
        c0, c1 = max(0, -dj), cols - max(0, dj)
        yield (di, dj), index[0:rows - di, c0:c1], index[di:rows, c0 + dj:c1 + dj], c0


def add_square_edges(builder, index, kind):
    for _, a, b, _ in neighbour_pairs(index):
        both = (a >= 0) & (b >= 0)
        builder.edges.extend((int(u), int(v), kind, False) for u, v in zip(a[both], b[both]))


def port_grid(builder, name, bounds, berth_zones):
    poly = utm_box(*bounds)

    def keep(x, y):
        ok = shapely.contains_xy(poly, x, y) & builder.in_area(x, y)
        lon, lat = TO_LONLAT(x, y)
        for lon0, lat0, lon1, lat1 in PORT_EXCLUDED:
            ok &= ~((lon >= lon0) & (lon <= lon1) & (lat >= lat0) & (lat <= lat1))
        ok[ok] = builder.water.classify(x[ok], y[ok])[0]
        ok[ok] = builder.far_from(x[ok], y[ok], ["river", "canal"], OVERLAP_M["port"])
        return ok

    X, Y, mask = square_grid(builder, poly.bounds, PORT_SPACING, keep)
    zone = berth_zones(X[mask], Y[mask]) if name == "antwerp" else np.full(int(mask.sum()), name, dtype=object)
    if name == "antwerp":
        # cells in the river outline the river grid does not reach (the outer harbours in front of
        # the locks) are tidal river water, not dock
        river = builder.water.in_river(X[mask], Y[mask])
        zone[river] = river_zones(X[mask][river], Y[mask][river])
    index = np.full(X.shape, -1)
    index[mask] = builder.add_nodes(X[mask], Y[mask], "port", zone, f"port_{name}")
    add_square_edges(builder, index, "port")
    log.info("port %s: %d nodes", name, int(mask.sum()))


def sea_grid(builder, traffic, anchorages):
    """Open-sea grid where Scheldt-bound ships sail (dilated AIS positions) and at anchorages."""
    x0, y0, x1, y1 = builder.area.bounds
    xs = np.arange(math.floor(x0 / SEA_SPACING) * SEA_SPACING, x1 + SEA_SPACING, SEA_SPACING)
    ys = np.arange(math.floor(y0 / SEA_SPACING) * SEA_SPACING, y1 + SEA_SPACING, SEA_SPACING)
    X, Y = np.meshgrid(xs, ys)
    occupied = np.zeros(X.shape, dtype=bool)
    ix = np.round((traffic["x"] - xs[0]) / SEA_SPACING).astype(int)
    iy = np.round((traffic["y"] - ys[0]) / SEA_SPACING).astype(int)
    ok = (ix >= 0) & (ix < len(xs)) & (iy >= 0) & (iy < len(ys))
    occupied[iy[ok], ix[ok]] = True
    r = SEA_TRAFFIC_DILATION_CELLS
    disk = np.hypot(*np.mgrid[-r:r + 1, -r:r + 1]) <= r
    needed = ndimage.binary_dilation(occupied, structure=disk)
    needed |= shapely.contains_xy(anchorages, X.ravel(), Y.ravel()).reshape(X.shape)
    lon, _ = TO_LONLAT(X, Y)
    cand = needed & (lon < 3.62) & builder.in_area(X.ravel(), Y.ravel()).reshape(X.shape)
    flat = np.flatnonzero(cand)
    wet = builder.water.classify(X.ravel()[flat], Y.ravel()[flat])[0]
    flat = flat[wet]
    flat = flat[builder.far_from(X.ravel()[flat], Y.ravel()[flat], ["river"], OVERLAP_M["sea"])]
    mask = np.zeros(X.size, dtype=bool)
    mask[flat] = True
    mask = mask.reshape(X.shape)
    index = np.full(X.shape, -1)
    index[mask] = builder.add_nodes(X[mask], Y[mask], "sea", "sea", "sea")
    add_square_edges(builder, index, "sea")
    log.info("sea: %d nodes", int(mask.sum()))


def add_links(builder):
    """Join every node to its LINKS_PER_NODE nearest nodes of each other grid within reach."""
    X, Y, R, _ = builder.arrays()
    grid = np.concatenate(builder.grid)
    tree = shapely.STRtree(shapely.points(X, Y))
    u, v = tree.query(shapely.points(X, Y), predicate="dwithin", distance=LINK_RADIUS_M["sea"])
    other = grid[u] != grid[v]
    u, v = u[other], v[other]
    d = np.hypot(X[u] - X[v], Y[u] - Y[v])
    reach = np.where((R[u] == "sea") | (R[v] == "sea"), LINK_RADIUS_M["sea"], LINK_RADIUS_M["default"])
    u, v, d = u[d <= reach], v[d <= reach], d[d <= reach]
    key = np.array([f"{a}|{g}" for a, g in zip(u, grid[v])])
    order = np.lexsort((d, key))
    key, u, v = key[order], u[order], v[order]
    rank = np.arange(len(key)) - np.searchsorted(key, key)
    pairs = {(min(p, q), max(p, q)) for p, q in zip(u[rank < LINKS_PER_NODE], v[rank < LINKS_PER_NODE])}
    builder.edges.extend((int(p), int(q), "link", False) for p, q in pairs)
    log.info("%d link edges between grids", len(pairs))


# ---------------------------------------------------------------------------
# depths, berths, terminals


def node_depths(water, x, y, region, zone):
    depth, source = water.chart.sample(x, y)
    charted = np.isfinite(depth) & (((region == "river") & (source == 1))
                                    | ((region == "sea") & np.isin(source, [1, 2])))
    charted &= ~np.isin(zone, NOMINAL_ONLY_ZONES)
    nominal = np.array([NOMINAL_DEPTH_M.get(z, NOMINAL_DEPTH_M["antwerp_other"]) for z in zone])
    return np.where(charted, depth, nominal), charted


def check_edges(water, X, Y, charted, depth, edges, chunk=200_000):
    """Keep the edges whose sampled points are all water; depth = shallowest point."""
    kept = []
    f = np.linspace(0.0, 1.0, EDGE_SAMPLES)
    for start in range(0, len(edges), chunk):
        part = edges[start:start + chunk]
        u = np.array([e[0] for e in part])
        v = np.array([e[1] for e in part])
        exempt = np.array([e[3] for e in part])
        px = X[u, None] + (X[v] - X[u])[:, None] * f[None, :]
        py = Y[u, None] + (Y[v] - Y[u])[:, None] * f[None, :]
        wet, d, src = water.classify(px.ravel(), py.ravel())
        wet, d, src = wet.reshape(px.shape), d.reshape(px.shape), src.reshape(px.shape)
        ok = wet.all(axis=1) | exempt
        sea = np.array([e[2] == "sea" for e in part])
        usable = np.isfinite(d) & ((src == 1) | (sea[:, None] & (src == 2)))
        sampled = np.where(usable, d, np.inf).min(axis=1)
        both_charted = charted[u] & charted[v]
        edge_depth = np.minimum(depth[u], depth[v])
        edge_depth = np.where(both_charted, np.minimum(edge_depth, sampled), edge_depth)
        for i in np.flatnonzero(ok):
            kept.append((int(u[i]), int(v[i]), part[i][2], float(edge_depth[i])))
    return kept


def load_berths():
    berths = gpd.read_file(SLOT_DATA).to_crs(PROJECTED_CRS)
    berths["number"] = berths.LPL.str.extract(r"^[A-Z]?(\d+)")[0].astype(float)
    return berths


def antwerp_dock_zones(berths):
    numbered = berths[berths.number.notna()]
    tree = shapely.STRtree(numbered.geometry.centroid.values)
    zones = np.full(len(numbered), "antwerp_other", dtype=object)
    for lo, hi, zone in ANTWERP_DOCKS:
        zones[numbered.number.between(lo, hi).to_numpy()] = zone

    def assign(x, y):
        idx = tree.nearest(shapely.points(x, y))
        return zones[idx]

    return assign


def tag_berths(graph, berths, X, Y, ids):
    """Mark the nodes inside each berth polygon (or the nearest within BERTH_SNAP_M): is_berth, and
    berths = every berth id the node serves (slots overlap). Returns {berth id: [nodes]}."""
    for _, data in graph.nodes(data=True):
        data.update(is_berth=False, berths=[], terminal=None)
    tree = shapely.STRtree(shapely.points(X, Y))
    berth_nodes = {}
    for row in berths.itertuples():
        hit = tree.query(row.geometry.buffer(15.0), predicate="intersects")
        if not len(hit):
            near = tree.query_nearest(row.geometry, max_distance=BERTH_SNAP_M)
            hit = near[:1]
        if not len(hit):
            continue
        # some berth ids have several polygons: their nodes are combined
        nodes = sorted(set(berth_nodes.get(row.LPL_UN, [])) | {int(ids[i]) for i in hit})
        berth_nodes[row.LPL_UN] = nodes
        for n in nodes:
            data = graph.nodes[n]
            data["is_berth"] = True
            if row.LPL_UN not in data["berths"]:
                data["berths"].append(row.LPL_UN)
    return berth_nodes


def place_terminals(graph, berths, X, Y, ids):
    tree = shapely.STRtree(shapely.points(X, Y))
    placed = []
    for terminal in TERMINALS:
        polys = berths[berths.TERMINAL == terminal["code"]].geometry
        if polys.empty:
            log.warning("No berth polygons for terminal %s", terminal["name"])
            continue
        centre = shapely.union_all(polys.values).centroid
        nodes = set()
        for poly in polys:
            nodes.update(int(ids[i]) for i in tree.query(poly.buffer(15.0), predicate="intersects"))
        for n in nodes:
            graph.nodes[n]["terminal"] = terminal["name"]
        access = (min(nodes, key=lambda n: math.hypot(graph.nodes[n]["x"] - centre.x, graph.nodes[n]["y"] - centre.y))
                  if nodes else None)
        lon, lat = TO_LONLAT(centre.x, centre.y)
        placed.append({**{k: v for k, v in terminal.items()}, "longitude": float(lon), "latitude": float(lat),
                       "x": float(centre.x), "y": float(centre.y), "access_node": access, "n_nodes": len(nodes)})
    return placed


# ---------------------------------------------------------------------------
# locks


def _chambers(spec, lock_lines, water):
    lines = lock_lines.set_index("osm_id").geometry
    out = []
    for cname, osm_id, length, width, sill, source in spec["chambers"]:
        if isinstance(osm_id, list):
            line = LineString(zip(*TO_UTM(*zip(*osm_id))))
        elif osm_id not in lines.index:
            log.warning("No OSM centreline %s for lock chamber %s", osm_id, cname)
            continue
        else:
            line = lines[osm_id]
        if not isinstance(osm_id, list) and length and line.length > length + 60.0:
            # the OSM line runs on through the outer harbour: the chamber is at the end away from
            # the river (or in the middle when that cannot be told)
            keep = length + 40.0
            ends = shapely.get_coordinates(line)[[0, -1]]
            in_river = water.in_river(ends[:, 0], ends[:, 1])
            if in_river[0] and not in_river[1]:
                line = shapely.ops.substring(line, line.length - keep, line.length)
            elif in_river[1] and not in_river[0]:
                line = shapely.ops.substring(line, 0.0, keep)
            else:
                line = shapely.ops.substring(line, (line.length - keep) / 2, (line.length + keep) / 2)
        chamber = Chamber(cname, float(length or round(line.length)), float(width), float(sill),
                          sill_datum="TAW" if source == "regs" else "LAT (nominal)", source=source)
        out.append((chamber, line, line.buffer(width / 2, cap_style="flat")))
    return out


def _segment(graph, u, v):
    return LineString([(graph.nodes[u]["x"], graph.nodes[u]["y"]), (graph.nodes[v]["x"], graph.nodes[v]["y"])])


def insert_locks(graph, water, lock_lines):
    """Replace the water cells of every lock by one lock node joined to both sides by gate edges."""
    ids = np.array(list(graph.nodes))
    X = np.array([graph.nodes[n]["x"] for n in ids])
    Y = np.array([graph.nodes[n]["y"] for n in ids])
    tree = shapely.STRtree(shapely.points(X, Y))
    next_id = int(ids.max()) + 1
    f = np.linspace(0.0, 1.0, EDGE_SAMPLES)
    for name, spec in LOCKS.items():
        chambers = _chambers(spec, lock_lines, water)
        if not chambers:
            continue
        footprint = shapely.union_all([poly for *_, poly in chambers])
        # the grid cells inside the chambers go, and so does every edge across a chamber
        inside = {int(ids[i]) for i in tree.query(footprint.buffer(5.0), predicate="contains")}
        graph.remove_nodes_from(inside)
        near = [int(ids[i]) for i in tree.query(footprint.buffer(1500.0), predicate="contains") if int(ids[i]) in graph]
        crossing = [(u, v) for u in near for v in list(graph[u]) if _segment(graph, u, v).intersects(footprint)]
        graph.remove_edges_from(crossing)

        mids = np.array([shapely.get_coordinates(line.interpolate(0.5, normalized=True))[0] for _, line, _ in chambers])
        cx, cy = mids.mean(axis=0)
        first = shapely.get_coordinates(chambers[0][1])
        axis = (first[-1] - first[0]) / np.linalg.norm(first[-1] - first[0])
        gates = []
        for chamber, line, poly in chambers:
            ends = shapely.get_coordinates(line)[[0, -1]]
            if np.dot(ends[1] - ends[0], axis) < 0:
                ends = ends[::-1]       # every chamber's first end is on the lock's side "a"
            for (ex, ey), side in zip(ends, ("a", "b")):
                cand = [int(ids[i]) for i in tree.query(shapely.Point(ex, ey).buffer(GATE_REACH_M), predicate="contains")]
                cand = [n for n in cand if n in graph]
                cand.sort(key=lambda n: math.hypot(graph.nodes[n]["x"] - ex, graph.nodes[n]["y"] - ey))
                picked = 0
                for n in cand:
                    nx_, ny_ = graph.nodes[n]["x"], graph.nodes[n]["y"]
                    seg = LineString([(ex, ey), (nx_, ny_)])
                    if seg.intersection(poly.buffer(-1.0)).length > 1.0:
                        continue            # would run back through the chamber
                    px, py = ex + (nx_ - ex) * f, ey + (ny_ - ey) * f
                    outside = ~shapely.contains_xy(poly.buffer(2.0), px, py)
                    if not water.classify(px[outside], py[outside])[0].all():
                        continue
                    gates.append((n, chamber, side, line.length / 2 + seg.length))
                    picked += 1
                    if picked == GATE_LINKS_PER_END:
                        break
                if not picked:
                    log.warning("Lock %s, chamber %s: no water within %.0f m of its %s end",
                                name, chamber.name, GATE_REACH_M, side)
        if not gates:
            log.warning("Lock %s is not connected; left out", name)
            continue
        node = next_id
        next_id += 1
        lon, lat = TO_LONLAT(cx, cy)
        lock = Lock(name, [c for c, *_ in chambers], lock_type=spec.get("type", "B"),
                    preferred_min_beam_m=spec.get("preferred_min_beam_m"))
        graph.add_node(node, x=float(cx), y=float(cy), longitude=float(lon), latitude=float(lat), region="lock",
                       zone="lock", type="lock", name=name, depth_m=lock.max_sill_depth_m,
                       depth_source="lock_sill", drying=False, lock=lock)
        for n, chamber, side, length in gates:
            depth = chamber.sill_depth_m
            if graph.has_edge(node, n):        # two chambers reach the same node: keep the deepest
                depth = max(depth, graph.edges[node, n]["depth_m"])
            graph.add_edge(node, n, weight=float(length), depth_m=round(depth, 2), kind="lock_gate",
                           lock=name, chamber=chamber.name, side=side)
        log.info("lock %s: %d chambers, %d grid nodes and %d edges replaced, %d gate edges",
                 name, len(chambers), len(inside), len(crossing), len(gates))


def seal_locks(graph):
    """With every lock node taken out, the two sides of a lock must not be connected; whatever
    still joins them (a link across a dike, a 20 m-tolerance bridge over a thin quay) is cut:
    the minimum edge cut between the two sides is removed."""
    locks = [n for n, d in graph.nodes(data=True) if d["type"] == "lock"]
    rest = nx.Graph(graph.edges)
    rest.remove_nodes_from(locks)
    nx.set_edge_attributes(rest, 1, "capacity")      # the source/sink edges get none: unlimited
    for node in locks:
        sides = {s: {v for v in graph[node] if graph.edges[node, v]["side"] == s} for s in ("a", "b")}
        a, b = sides["a"], sides["b"] - sides["a"]
        if not a or not b:
            continue
        rest.add_edges_from(("source", v) for v in a)
        rest.add_edges_from(("sink", v) for v in b)
        cut = set()
        if nx.has_path(rest, "source", "sink"):
            _, (reach, _) = nx.minimum_cut(rest, "source", "sink")
            cut = {(u, v) for u in reach for v in rest[u] if v not in reach}
        rest.remove_nodes_from(["source", "sink"])
        if len(cut) > SEAL_MAX_CUT:
            log.warning("Lock %s: its two sides are joined by %d edges, left as is", graph.nodes[node]["name"], len(cut))
            continue
        if cut:
            where = sorted({(round(graph.nodes[u]["longitude"], 4), round(graph.nodes[u]["latitude"], 4)) for u, _ in cut})
            log.info("lock %s sealed: %d edges cut %s", graph.nodes[node]["name"], len(cut), where[:6])
            graph.remove_edges_from(cut)
            rest.remove_edges_from(cut)


def label_basins(graph):
    """Make zones follow the topology the locks create. With the lock nodes taken out, the water
    joined to the open sea is tidal: dock zones there (outer harbours, river margins) become river
    zones. Every other basin is enclosed by locks: river zones there become the basin's most common
    dock zone. Nominal depths follow the new zones."""
    rest = nx.Graph(graph.edges)
    rest.add_nodes_from(graph.nodes)
    rest.remove_nodes_from([n for n, d in graph.nodes(data=True) if d["type"] == "lock"])
    tidal_zones = set(TIDAL_ZONES) | {"sea"}
    changed, tidal_water = set(), set()
    for basin in nx.connected_components(rest):
        tidal = any(graph.nodes[n]["region"] == "sea" for n in basin)
        if tidal:
            tidal_water |= basin
        docks = collections.Counter(graph.nodes[n]["zone"] for n in basin if graph.nodes[n]["zone"] not in tidal_zones)
        for n in basin:
            graph.nodes[n]["basin"] = None if tidal else (docks.most_common(1)[0][0] if docks else graph.nodes[n]["zone"])
        if tidal:
            wrong = [n for n in basin if graph.nodes[n]["zone"] not in tidal_zones and graph.nodes[n]["region"] == "port"
                     and graph.nodes[n]["zone"].startswith("antwerp_")]
            new = river_zones(np.array([graph.nodes[n]["x"] for n in wrong]), np.array([graph.nodes[n]["y"] for n in wrong])) if wrong else []
        else:
            if not docks:
                continue
            wrong = [n for n in basin if graph.nodes[n]["zone"] in tidal_zones]
            new = [docks.most_common(1)[0][0]] * len(wrong)
        for n, zone in zip(wrong, new):
            data = graph.nodes[n]
            data["zone"] = zone
            data["depth_m"] = NOMINAL_DEPTH_M.get(zone, NOMINAL_DEPTH_M["antwerp_other"])
            data["depth_source"], data["drying"] = "nominal", False
            changed.add(n)
    for n in changed:
        for v in graph[n]:
            edge = graph.edges[n, v]
            if edge["kind"] != "lock_gate":
                edge["depth_m"] = round(min(graph.nodes[n]["depth_m"], graph.nodes[v]["depth_m"]), 2)
    log.info("%d nodes relabelled to the basin they are in (tidal or behind a lock)", len(changed))
    for node, data in graph.nodes(data=True):
        if data["type"] == "lock":
            for v in graph[node]:
                graph.edges[node, v]["tidal"] = v in tidal_water


def refresh_locks(graph):
    """Fill each lock's sides (zone, tidal, nodes) from its gate edges; call after relabelling."""
    graph.graph["locks"] = {}
    for node, data in graph.nodes(data=True):
        if data["type"] != "lock":
            continue
        lock = data["lock"]
        lock.sides = {}
        for side in ("a", "b"):
            nodes = sorted(v for v in graph[node] if graph.edges[node, v]["side"] == side)
            zones = collections.Counter(graph.nodes[v]["zone"] for v in nodes)
            lock.sides[side] = {
                "zone": zones.most_common(1)[0][0] if zones else None,
                "tidal": any(graph.edges[node, v].get("tidal", False) for v in nodes),
                "nodes": nodes,
            }
        graph.graph["locks"][lock.name] = node


# ---------------------------------------------------------------------------
# tide


def assign_tide(graph):
    """Give every tidal node the two gauges its water level is interpolated from, and every node
    its nearest gauge; turn the lock sills given below TAW into depths below LAT (tide.py)."""
    from fetch_tide_data import GAUGES
    import tide

    xy = {g: np.array(TO_UTM(lon, lat)) for g, (_, lon, lat) in GAUGES.items()}
    names = list(GAUGES)
    G = np.array([xy[g] for g in names])
    chain = [g for g in RIVER_GAUGES if g in xy]
    line = LineString([xy[g] for g in chain])
    marks = np.array([line.project(shapely.Point(*xy[g])) for g in chain])
    sea = [g for g in SEA_GAUGES if g in xy]
    for n, d in graph.nodes(data=True):
        p = np.array([d["x"], d["y"]])
        d["tide_gauge"] = names[int(np.argmin(np.hypot(*(G - p).T)))]
        if d["type"] == "lock" or d.get("basin"):
            d["tide"] = None
            continue
        if d["region"] == "sea":
            dist = sorted((math.hypot(*(xy[g] - p)), g) for g in sea)[:2]
            (da, a), (db, b) = dist
            d["tide"] = (a, b, round(da / (da + db), 3))
            continue
        s = line.project(shapely.Point(*p))
        i = int(np.clip(np.searchsorted(marks, s) - 1, 0, len(chain) - 2))
        w = float(np.clip((s - marks[i]) / (marks[i + 1] - marks[i]), 0.0, 1.0))
        d["tide"] = (chain[i], chain[i + 1], round(w, 3))
    if not tide.MODEL_FILE.is_file():
        log.warning("No tide model (%s): lock sills stay below TAW; run fit_tide.py and rebuild", tide.MODEL_FILE)
        return
    model = tide.TideModel.load()
    for node, d in graph.nodes(data=True):
        if d["type"] != "lock":
            continue
        for chamber in d["lock"].chambers:
            if chamber.sill_datum == "TAW":
                chamber.sill_depth_m = round(model.taw_to_lat_depth(chamber.sill_depth_m, d["tide_gauge"]), 2)
                chamber.sill_datum = "LAT (from TAW)"
        sill = {c.name: c.sill_depth_m for c in d["lock"].chambers}
        for v in graph[node]:
            graph.edges[node, v]["depth_m"] = sill[graph.edges[node, v]["chamber"]]
        d["depth_m"] = d["lock"].max_sill_depth_m
    graph.graph["tide"] = {"model": str(tide.MODEL_FILE.relative_to(PROJECT_ROOT)), "river_gauges": chain, "sea_gauges": sea}
    log.info("Tide gauges assigned; lock sills converted from TAW to LAT")


def assign_estuary_axis(graph, western, zeeschelde):
    """One axis from the mouth to Antwerp: the Western Scheldt centreline up to where the Zeeschelde
    centreline starts, then the Zeeschelde one. Tidal river and port nodes get their distance along
    it (chainage_m) and the local upstream direction (flow_dir)."""
    start = shapely.Point(zeeschelde.coords[0])
    cut = western.project(start)
    coords = list(shapely.ops.substring(western, 0.0, cut).coords) + list(zeeschelde.coords)
    axis = LineString(coords)
    nodes = [n for n, d in graph.nodes(data=True)
             if d["region"] in ("river", "port") and d.get("tide") is not None]
    pts = shapely.points([graph.nodes[n]["x"] for n in nodes], [graph.nodes[n]["y"] for n in nodes])
    s = shapely.line_locate_point(axis, pts)
    t = _tangents(axis, s, h=200.0)
    for n, si, (tx, ty) in zip(nodes, s, t):
        graph.nodes[n]["chainage_m"] = round(float(si), 1)
        graph.nodes[n]["flow_dir"] = (round(float(tx), 4), round(float(ty), 4))
    graph.graph["estuary_axis"] = [(round(x, 1), round(y, 1)) for x, y in axis.coords]
    log.info("Estuary axis %.1f km; %d nodes given a chainage", axis.length / 1000, len(nodes))


# ---------------------------------------------------------------------------
# build


def build_graph(refresh_osm: bool = False) -> nx.Graph:
    area = ais_area().buffer(AREA_MARGIN_M)
    osm_water, lock_lines, osm_river = fetch_osm_water(refresh_osm)
    water = Water(Chart(), osm_water, osm_river)
    traffic = scheldt_traffic()
    builder = Builder(water, area)

    lines = {}
    for name, spec in CHANNELS.items():
        lines[name] = fit_centreline(spec, traffic, water)
        channel_grid(builder, name, spec, lines[name])
    berths = load_berths()
    dock_zones = antwerp_dock_zones(berths)
    for name, bounds in PORTS.items():
        port_grid(builder, name, bounds, dock_zones)
    anchorages = gpd.read_file(CHARTS, layer="anchorages").to_crs(PROJECTED_CRS)
    sea_grid(builder, traffic, shapely.union_all(anchorages.geometry.values).buffer(ANCHORAGE_MARGIN_M))
    add_links(builder)

    X, Y, R, Z = builder.arrays()
    depth, charted = node_depths(water, X, Y, R, Z)
    log.info("Checking %d candidate edges against the water mask", len(builder.edges))
    edges = check_edges(water, X, Y, charted, depth, builder.edges)
    log.info("%d edges over water (%d dropped over land)", len(edges), len(builder.edges) - len(edges))

    lon, lat = TO_LONLAT(X, Y)
    graph = nx.Graph()
    for i in range(len(X)):
        graph.add_node(i, x=float(X[i]), y=float(Y[i]), longitude=float(lon[i]), latitude=float(lat[i]),
                       region=R[i], zone=Z[i], type="water", depth_m=round(float(depth[i]), 2),
                       depth_source="chart_LAT" if charted[i] else "nominal", drying=bool(depth[i] < 0))
    for u, v, kind, d in edges:
        if u != v:
            graph.add_edge(u, v, weight=float(math.hypot(X[u] - X[v], Y[u] - Y[v])), depth_m=round(d, 2), kind=kind)

    insert_locks(graph, water, lock_lines)
    seal_locks(graph)
    label_basins(graph)
    largest = max(nx.connected_components(graph), key=len)
    dropped = graph.number_of_nodes() - len(largest)
    graph = nx.convert_node_labels_to_integers(graph.subgraph(largest).copy())
    refresh_locks(graph)
    assign_tide(graph)
    assign_estuary_axis(graph, lines["western_scheldt"], lines["zeeschelde"])
    log.info("Kept the largest connected part: %d nodes (%d isolated nodes dropped)", graph.number_of_nodes(), dropped)

    ids = np.array([n for n, d in graph.nodes(data=True) if d["type"] != "lock"])
    GX = np.array([graph.nodes[n]["x"] for n in ids])
    GY = np.array([graph.nodes[n]["y"] for n in ids])
    berth_nodes = tag_berths(graph, berths, GX, GY, ids)
    terminals = place_terminals(graph, berths, GX, GY, ids)
    for t in terminals:
        if t["access_node"] is not None:
            graph.nodes[t["access_node"]]["type"] = "terminal"
            graph.nodes[t["access_node"]]["name"] = t["name"]
    unreached = sorted(set(berths.LPL_UN) - set(berth_nodes))
    log.info("Berth polygons without a node within %.0f m: %d %s", BERTH_SNAP_M, len(unreached), unreached)

    graph.graph.update({
        "crs": PROJECTED_CRS, "coordinate_crs": GEOGRAPHIC_CRS, "depth_datum": "LAT",
        "spacing_m": {"sea": [SEA_SPACING, SEA_SPACING], "river": [RIVER_ALONG, RIVER_ACROSS],
                      "canal": [RIVER_ALONG, RIVER_ACROSS], "port": [PORT_SPACING, PORT_SPACING]},
        "nominal_depth_m": NOMINAL_DEPTH_M, "terminals": terminals, "berth_nodes": berth_nodes,
        "sources": {"depth": str(DEPTH_RASTER.relative_to(PROJECT_ROOT)), "osm_water": list(OSM_AREAS),
                    "berths": str(SLOT_DATA.relative_to(PROJECT_ROOT)), "traffic": "data/ais via src/data/ais_pipeline.py"},
    })
    return graph


# ---------------------------------------------------------------------------
# routing


def nearest_node(graph: nx.Graph, longitude: float, latitude: float, min_depth_m: float | None = None) -> int:
    """The node closest to a position (optionally only among nodes at least min_depth_m deep)."""
    x, y = TO_UTM(longitude, latitude)
    nodes = [(n, d) for n, d in graph.nodes(data=True) if min_depth_m is None or d["depth_m"] >= min_depth_m]
    return min(nodes, key=lambda nd: (nd[1]["x"] - x) ** 2 + (nd[1]["y"] - y) ** 2)[0]


def find_route(graph: nx.Graph, source: int, target: int, draught_m: float, ukc_m: float = 0.0,
               loa_m: float = 0.0, beam_m: float = 0.0, lock_penalty_m: float = LOCK_PASSAGE_PENALTY_M,
               water_level=None) -> list[int]:
    """Shortest path (A*, straight-line heuristic) that never uses an edge shallower than
    draught_m + ukc_m, nor a lock with no chamber the ship (loa_m x beam_m) fits. Every lock
    passage costs lock_penalty_m extra, standing in for the time a lockage takes. Depths are
    below LAT; water_level(node) -> m above LAT (e.g. from tide.node_level) adds the water level,
    else LAT is assumed. For timing along the route use tide.tidal_window. Raises
    networkx.NetworkXNoPath if no route exists."""
    need = draught_m + ukc_m
    nodes = graph.nodes
    level = water_level or (lambda n: 0.0)

    def weight(u, v, data):
        if nodes[u]["type"] == "lock" or nodes[v]["type"] == "lock":
            lock_node, water_node = (u, v) if nodes[u]["type"] == "lock" else (v, u)
            lock, h = nodes[lock_node]["lock"], level(water_node)
            if not any(c.fits_size(loa_m, beam_m) and need <= c.sill_depth_m + h for c in lock.chambers):
                return None
            return data["weight"] + lock_penalty_m / 2      # in and out: two gate edges
        if data["depth_m"] + min(level(u), level(v)) < need:
            return None
        return data["weight"]

    def heuristic(u, v):
        return math.hypot(nodes[u]["x"] - nodes[v]["x"], nodes[u]["y"] - nodes[v]["y"])

    return nx.astar_path(graph, source, target, heuristic=heuristic, weight=weight)


# ---------------------------------------------------------------------------
# output


def save_graph(graph: nx.Graph, output: Path = DEFAULT_OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as file:
        pickle.dump({"graph": graph, "crs": PROJECTED_CRS}, file, protocol=pickle.HIGHEST_PROTOCOL)
    return output


def save_web_visualization(graph: nx.Graph, output: Path = DEFAULT_HTML) -> Path:
    regions = ["sea", "river", "canal", "port", "lock"]
    index = {n: i for i, n in enumerate(graph.nodes)}
    nodes = [[round(d["longitude"], 6), round(d["latitude"], 6), d["depth_m"], regions.index(d["region"]),
              1 if d["is_berth"] else 0] for _, d in graph.nodes(data=True)]
    edges = [[index[u], index[v]] for u, v in graph.edges]
    berths = []
    if SLOT_DATA.is_file():
        slot_data = json.loads(SLOT_DATA.read_text(encoding="utf-8"))
        berths = [f["geometry"]["coordinates"][0] for f in slot_data.get("features", [])
                  if f.get("geometry", {}).get("type") == "Polygon"]
    terminals = [{"name": t["name"], "position": [t["longitude"], t["latitude"]], "quay_m": t["quay_m"],
                  "draft_m": t["draft_m"], "capacity": t["capacity"]} for t in graph.graph.get("terminals", [])]
    terminals += [{"name": f"Sluis {d['name']}", "position": [d["longitude"], d["latitude"]],
                   "quay_m": " / ".join(f"{c.length_m:.0f}x{c.width_m:.0f}" for c in d["lock"].chambers),
                   "draft_m": d["depth_m"], "capacity": f"{len(d['lock'].chambers)} komory"}
                  for _, d in graph.nodes(data=True) if d["type"] == "lock"]
    payload = json.dumps({"nodes": nodes, "edges": edges, "berths": berths, "terminals": terminals,
                          "stats": {"nodes": graph.number_of_nodes(), "edges": graph.number_of_edges()}},
                         separators=(",", ":"), ensure_ascii=False)
    html = """<!doctype html>
<html lang="pl"><head><meta charset="utf-8">
<title>Graf portu Antwerpia i Skaldy</title>
<style>
html,body{margin:0;height:100%;overflow:hidden;background:#10141b;color:#e8eef5;font:14px system-ui}
canvas{display:block;width:100%;height:100%;cursor:grab} canvas.dragging{cursor:grabbing}
#info{position:fixed;left:12px;top:12px;background:#18212dcc;padding:10px 12px;border:1px solid #43546a;border-radius:6px;line-height:1.45}
#info b{color:#65d8ff}
</style></head><body><canvas id="map"></canvas><div id="info"></div>
<script>
const data=__PAYLOAD__, canvas=document.getElementById("map"), ctx=canvas.getContext("2d");
const colors=["#3a7bd5","#35c8e8","#7bd389","#ff6b5e","#ffd400"], all=data.nodes;
let scale=1, ox=0, oy=0, dragging=false, px=0, py=0;
let minLon=Infinity,maxLon=-Infinity,minLat=Infinity,maxLat=-Infinity;
for(const n of all){minLon=Math.min(minLon,n[0]);maxLon=Math.max(maxLon,n[0]);minLat=Math.min(minLat,n[1]);maxLat=Math.max(maxLat,n[1])}
const k=Math.cos((minLat+maxLat)/2*Math.PI/180);
function base(){return Math.min(innerWidth/((maxLon-minLon)*k),innerHeight/(maxLat-minLat))}
function project(x,y){const b=base()*scale;return [(x-minLon)*k*b+ox,(maxLat-y)*b+oy]}
function resize(){canvas.width=innerWidth*devicePixelRatio;canvas.height=innerHeight*devicePixelRatio;ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);draw()}
function draw(){ctx.clearRect(0,0,innerWidth,innerHeight);
 for(let r=0;r<5;r++){ctx.strokeStyle=colors[r]+"99";ctx.lineWidth=.5;ctx.beginPath();
  for(const e of data.edges){const a=all[e[0]],b=all[e[1]];if(a[3]!==r&&b[3]!==r)continue;const p=project(a[0],a[1]),q=project(b[0],b[1]);ctx.moveTo(p[0],p[1]);ctx.lineTo(q[0],q[1])}ctx.stroke()}
 if(scale>4){for(const n of all){const p=project(n[0],n[1]);ctx.fillStyle=n[4]?"#ffb347":(n[2]<0?"#e377c2":colors[n[3]]);ctx.fillRect(p[0]-1,p[1]-1,2,2)}}
 for(const ring of data.berths){ctx.strokeStyle="#ffad3d99";ctx.beginPath();ring.forEach((p,i)=>{const q=project(p[0],p[1]);i?ctx.lineTo(q[0],q[1]):ctx.moveTo(q[0],q[1])});ctx.closePath();ctx.stroke()}
 for(const t of data.terminals){const p=project(t.position[0],t.position[1]);ctx.fillStyle="#ff453a";ctx.beginPath();ctx.arc(p[0],p[1],5,0,Math.PI*2);ctx.fill();ctx.fillStyle="#fff";ctx.font="12px system-ui";ctx.fillText(t.name,p[0]+7,p[1]-9);ctx.font="10px system-ui";ctx.fillText(`Nabrzeże: ${t.quay_m} m | zanurzenie: ${t.draft_m} m`,p[0]+7,p[1]+4)}
}
canvas.onwheel=e=>{e.preventDefault();const f=e.deltaY<0?1.2:1/1.2;ox=e.offsetX-(e.offsetX-ox)*f;oy=e.offsetY-(e.offsetY-oy)*f;scale*=f;draw()};
canvas.onpointerdown=e=>{dragging=true;px=e.clientX;py=e.clientY;canvas.classList.add("dragging")};
canvas.onpointermove=e=>{if(dragging){ox+=e.clientX-px;oy+=e.clientY-py;px=e.clientX;py=e.clientY;draw()}};
canvas.onpointerup=canvas.onpointerleave=()=>{dragging=false;canvas.classList.remove("dragging")};
window.onresize=resize;resize();
document.getElementById("info").innerHTML="<b>Graf portu Antwerpia i Skaldy</b><br>"+
`Węzły: ${data.stats.nodes.toLocaleString()} | Krawędzie: ${data.stats.edges.toLocaleString()}<br>`+
"Niebieski: morze 250 m | turkus: rzeka 200x50 m | zielony: kanały | czerwony: port 50 m<br>"+
"Po powiększeniu: różowy = węzły osuszane, pomarańczowy = stanowiska<br>Przeciągnij, kółko myszy = powiększenie";
</script></body></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html.replace("__PAYLOAD__", payload), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--no-browser", action="store_true", help="Generate the HTML without opening a browser.")
    parser.add_argument("--refresh-osm", action="store_true", help=f"Download the OSM water again (else {OSM_WATER_FILE.name}).")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    graph = build_graph(args.refresh_osm)
    output = save_graph(graph, args.output)
    html_output = save_web_visualization(graph, args.html)
    print(f"Stworzono graf: |V| = {graph.number_of_nodes()}, |E| = {graph.number_of_edges()}. "
          f"Zapisano w {output}\nWizualizacja HTML: {html_output}")
    if not args.no_browser:
        webbrowser.open(html_output.resolve().as_uri())


if __name__ == "__main__":
    main()
