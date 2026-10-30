"""Shared AIS processing for the fit_*.py scripts: snapshots -> visits -> entries and stops.

    load_snapshots   all snapshots in data/ais/ as one table of positions
    prepare          positions split into visits per MMSI, ships classified (PLAN.md §1-2),
                     every visit's entry source, and whether it enters the Scheldt
    find_stops       periods a ship lies still: at a berth, at an anchorage or elsewhere
    visit_exits      where a visit left the area (sea gate, canal, ...)

A visit starts the first time a ship is seen, or when it is back somewhere else after
NEW_VISIT_GAP_H. Ships first seen in the WARMUP_MIN after a collector (re)start were
already there, so those visits have no observed entry.
"""
import json
import logging
import math
import pprint
import re
import warnings
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from scipy import optimize, stats
from shapely.geometry import LineString, Point, Polygon

REPO_ROOT = Path(__file__).resolve().parents[2]
AIS_DIR = REPO_ROOT / "data" / "ais"
SCHEDULE = REPO_ROOT / "data" / "schedules" / "2026_Oct20-Nov22.csv"
CHARTS = REPO_ROOT / "data" / "charts" / "scheldt_navigation.gpkg"
BERTHS = REPO_ROOT / "slots_cords" / "paczka_final.json"

log = logging.getLogger("ais")

# two collectors sometimes write the same 5-min snapshot a few seconds apart
DUPLICATE_SNAPSHOT_S = 60
# a longer pause between snapshots means the collector was down
MAX_SNAPSHOT_GAP_MIN = 12
# after a restart the tracker starts empty: ships first seen this soon after it were already there
WARMUP_MIN = 20
# an entry needs this much data after it, to see whether the ship anchors / reaches the Scheldt
FOLLOW_UP_H = 4
# a ship missing this long (while the collector ran) and seen again elsewhere is a new visit
NEW_VISIT_GAP_H = 6
NEW_VISIT_MIN_MOVE_KM = 3
# "lying still" at an anchorage, and how long (in 5-min fixes) counts as having anchored
STATIONARY_KN = 1.0
ANCHORED_MIN_FIXES = 6
ANCHORAGE_BUFFER_KM = 1.5
# a stop: lying still this long within this radius (anchored ships swing round)
STOP_MIN_H = 0.5
STOP_RADIUS_KM = 1.0
# the start/end of a stop is only known if the ship is seen this close before/after it
STOP_CONTINUITY_MIN = 30
# allowed range of the lognormal sigma when fitting durations
LOGNORMAL_SIGMA = (0.05, 3.0)
# zones with locks: a shorter stop there is a lock passage/wait, not a berth call
LOCK_STOP_MAX_H = 3.0
# a stop in the Antwerp port zone within this distance of a charted berth is at that berth
BERTH_MATCH_KM = 0.25
# west of this the water is open sea, east of it the Western Scheldt estuary
OPEN_SEA_MAX_LON = 3.45
# a visit enters the Scheldt with a fix in a Scheldt port/channel zone, or east of the
# Vlissingen-Breskens line and south of the Oosterschelde (so not just the Oostgat / Wielingen)
SCHELDT_MIN_LON, SCHELDT_MAX_LAT = 3.58, 51.52
# ... or is still waiting at sea when the data ends, with a Scheldt port as its AIS destination
SCHELDT_DESTINATION = re.compile(
    r"\b(BE ?ANR|BE ?ANT|ANTW|ANR|NL ?VLI|VLISS|FLUSHING|NL ?TNZ|TERNEUZEN|BE ?GNE|GENT|GHENT|SLUISKIL|BORSSELE)"
)

# ---------------------------------------------------------------------------
# geometry: a local metric frame (km), good enough over 150 km
LAT0, LON0 = 51.45, 3.5
KX, KY = 111.32 * math.cos(math.radians(LAT0)), 110.57


def to_km(lon, lat):
    return (np.asarray(lon) - LON0) * KX, (np.asarray(lat) - LAT0) * KY


def geom_to_km(geom):
    return shapely.transform(geom, lambda c: np.column_stack(to_km(c[:, 0], c[:, 1])))


# Ports and channels, as (lon_min, lat_min, lon_max, lat_max) boxes. Checked in this
# order, first match wins, so the small zones at the edge of Antwerp go first.
PORT_ZONES = {
    "albert_canal": ((4.385, 51.212, 4.45, 51.250), "port_channel",
                     "Albert Canal / Royerssluis, east edge of the area"),
    "upper_sea_scheldt": ((4.28, 51.17, 4.45, 51.212), "port_channel",
                          "Upper Sea Scheldt south of Antwerp (Rupel, Brussels, Ghent via the Scheldt)"),
    "antwerp_port": ((4.17, 51.212, 4.45, 51.372), "port_channel",
                     "Antwerp docks, locks, Deurganckdok and river quays"),
    "schelde_rijn_canal": ((4.20, 51.41, 4.27, 51.50), "port_channel",
                           "Schelde-Rijn canal (Kreekrak locks) to Rotterdam and the Rhine"),
    "zuid_beveland_canal": ((3.96, 51.43, 4.08, 51.52), "port_channel",
                            "Kanaal door Zuid-Beveland (Hansweert locks)"),
    "terneuzen": ((3.78, 51.315, 3.90, 51.345), "port_channel",
                  "Terneuzen port and locks"),
    "ghent_terneuzen_canal": ((3.76, 51.18, 3.90, 51.315), "port_channel",
                              "Ghent-Terneuzen canal (Sluiskil, Zelzate, Ghent)"),
    "vlissingen": ((3.54, 51.43, 3.76, 51.52), "port_channel",
                   "Vlissingen, Vlissingen-Oost/Sloehaven, Walcheren canal"),
    "breskens": ((3.53, 51.385, 3.59, 51.41), "port_channel",
                 "Breskens harbour"),
    "zeebrugge": ((3.10, 51.29, 3.27, 51.37), "non_scheldt",
                  "Zeebrugge (not on the Scheldt, shares only the pilots)"),
    "oosterschelde": ((3.54, 51.52, 4.30, 51.75), "non_scheldt",
                      "Oosterschelde and Veerse Meer, north of Walcheren / Zuid-Beveland"),
}

# The Antwerp port zone split by quay number (slots_cords LPL), for destinations and dwell times.
ANTWERP_BERTH_ZONES = [
    (1, 799, "antwerp_right_bank_docks", "right-bank docks behind the locks (quays 1-799)"),
    (800, 999, "antwerp_river_quays", "tidal river quays S8xx/S9xx (Europa, Noordzee terminals)"),
    (1100, 1699, "antwerp_left_bank_docks", "left-bank Waaslandhaven behind Kallo/Kieldrecht (quays 1100-1699)"),
    (1700, 1799, "antwerp_deurganckdok", "Deurganckdok, tidal (quays 1700-1799)"),
]
ANTWERP_OTHER = "antwerp_other"
ANTWERP_OTHER_DESCRIPTION = "Antwerp port zone away from a charted berth (lock approaches, yards, small quays)"

LOCK_ZONES = ("terneuzen", "schelde_rijn_canal", "zuid_beveland_canal", ANTWERP_OTHER)

SEA_GATES = {
    "sea_west": "open sea, crossing the west edge (Westhinder, Noordhinder TSS)",
    "sea_north": "open sea, crossing the north edge (from Rotterdam / the north)",
    "sea_southwest": "open sea, crossing the south-west edge (Ostend, Dunkirk, Channel coast)",
}

ANCHORAGE_OTHER = "anchorage_other"
UNRESOLVED = "unresolved"

# ---------------------------------------------------------------------------
# ship classes

CLASS_DESCRIPTIONS = {
    "container": "container ship (name in the schedule CSV, a container line's name, or cargo >= 250 m)",
    "bulk_general": "sea-going cargo that is not container: bulk, general cargo, ro-ro, car carriers, reefers",
    "tanker": "sea-going tanker (AIS 80-89 with an IMO number)",
    "inland_cargo": "inland barge, dry cargo (no IMO number, LOA >= 50 m)",
    "inland_tanker": "inland tanker barge (AIS 80-89, no IMO number)",
    "passenger": "passenger, cruise and river cruise (AIS 60-69)",
    "service": "tugs, pilots, dredgers, fishing, pleasure, small craft (left out of the simulation)",
    "unknown": "no static data received (left out of the simulation)",
}
SIMULATED_CLASSES = ["container", "bulk_general", "tanker", "inland_cargo", "inland_tanker", "passenger"]

CONTAINER_NAME = re.compile(
    r"^(MSC|MAERSK|CMA ?CGM|COSCO|OOCL|EVER|ONE|HMM|HYUNDAI|YM|ZIM|APL|X-PRESS|SEASPAN|CSCL|HAPAG|"
    r"MOL|NYK|WAN HAI|ARKAS)\b|\bEXPRESS$"
)


def valid_imo(imo):
    """IMO numbers carry a check digit; inland barges usually send none or an ENI number."""
    if imo is None or (isinstance(imo, float) and math.isnan(imo)):
        return False
    digits = str(int(imo))
    if len(digits) != 7:
        return False
    return sum(int(d) * w for d, w in zip(digits[:6], range(7, 1, -1))) % 10 == int(digits[6])


def normalise_name(name):
    return re.sub(r"[^A-Z0-9]", "", str(name).upper())


def classify(ship, scheduled_names):
    stype, length, imo_ok = ship.ship_type, ship.length, valid_imo(ship.imo)
    group = -1 if pd.isna(stype) else int(stype) // 10
    cargo_like = group in (-1, 0, 7, 9)
    if group == -1 and pd.isna(length):
        return "unknown"
    if normalise_name(ship.name) in scheduled_names and cargo_like and (imo_ok or group == -1):
        return "container"
    if group in (1, 3, 4, 5):
        return "service"
    if group == 6:
        return "passenger"
    if imo_ok:
        if group == 8:
            return "tanker"
        if group == 7 or (group in (-1, 0) and length >= 80):
            name = str(ship.name or "").upper()
            if CONTAINER_NAME.search(name) or length >= 250:
                return "container"
            return "bulk_general"
        return "service"
    if group in (-1, 0, 2, 7, 8, 9) and length >= 50:
        return "inland_tanker" if group == 8 else "inland_cargo"
    return "service"


def dangerous_goods(ship_type):
    """IMO hazard category A-D from the AIS ship type (x1-x4 for cargo and tankers), else None."""
    if pd.isna(ship_type) or int(ship_type) // 10 not in (7, 8) or not 1 <= int(ship_type) % 10 <= 4:
        return None
    return "ABCD"[int(ship_type) % 10 - 1]


# ---------------------------------------------------------------------------
# loading


def load_snapshots(ais_dir):
    rows, area, times = [], None, []
    for path in sorted(ais_dir.glob("20*/*.json")):
        snap = json.loads(path.read_text(encoding="utf-8"))
        taken = pd.Timestamp(snap["taken_at_utc"])
        if times and (taken - times[-1]).total_seconds() < DUPLICATE_SNAPSHOT_S:
            continue
        times.append(taken)
        area = snap["area"]
        for s in snap["ships"]:
            rows.append((taken, s["mmsi"], s.get("name"), s["lat"], s["lon"], s.get("sog"), s.get("cog"),
                         s.get("nav_status"), s.get("ship_type"), s.get("imo"), s.get("length"),
                         s.get("width"), s.get("draught"), s.get("destination")))
    cols = ["t", "mmsi", "name", "lat", "lon", "sog", "cog", "nav_status", "ship_type", "imo", "length",
            "width", "draught", "destination"]
    df = pd.DataFrame(rows, columns=cols)
    df["sog"] = df.sog.astype(float)
    df["cog"] = df.cog.astype(float)
    log.info("Loaded %d positions of %d ships from %d snapshots", len(df), df.mmsi.nunique(), len(times))
    return df, pd.Series(times), area


def observation_windows(times):
    """Exposure intervals (collector up, past its warm-up, with follow-up data) and the restarts."""
    gaps = times.diff().dt.total_seconds().div(60)
    restarts = times[gaps.isna() | (gaps > MAX_SNAPSHOT_GAP_MIN)].reset_index(drop=True)
    data_end = times.iloc[-1] - pd.Timedelta(hours=FOLLOW_UP_H)
    windows = []
    for start, nxt in zip(restarts, list(restarts[1:]) + [None]):
        seg = times[(times >= start) & ((times < nxt) if nxt is not None else True)]
        lo, hi = start + pd.Timedelta(minutes=WARMUP_MIN), min(seg.iloc[-1], data_end)
        if hi > lo:
            windows.append((lo, hi))
    return windows, restarts


def static_per_ship(df):
    def mode(s):
        s = s.dropna()
        return s.mode().iloc[0] if len(s) else np.nan

    return df.groupby("mmsi").agg(
        name=("name", mode), ship_type=("ship_type", mode), imo=("imo", mode), length=("length", mode),
        width=("width", mode), draught=("draught", "max"),
    )


# ---------------------------------------------------------------------------
# zones


def port_zone(lon, lat):
    """Name of the port/channel zone of every position ('' outside them)."""
    out = np.full(len(lon), "", dtype=object)
    for name, ((lon0, lat0, lon1, lat1), _, _) in reversed(PORT_ZONES.items()):
        out[(lon >= lon0) & (lon <= lon1) & (lat >= lat0) & (lat <= lat1)] = name
    return out


class EntryZones:
    def __init__(self, area, anchorages_path):
        lat, lon = zip(*area)
        x, y = to_km(lon, lat)
        corners = list(zip(x, y))  # SW, NW, NE, SE as written by the collector
        self.area = Polygon(corners)
        self.edges = {
            "sea_west": LineString([corners[0], corners[1]]),
            "sea_north": LineString([corners[1], corners[2]]),
            "sea_southwest": LineString([corners[3], corners[0]]),
        }
        anchorages = gpd.read_file(anchorages_path, layer="anchorages")
        self.anchorages = {}
        for _, row in anchorages.iterrows():
            key = "anchorage_" + re.sub(r"[^a-z0-9]+", "_", row["name"].lower()).strip("_")
            geom = geom_to_km(row.geometry).buffer(ANCHORAGE_BUFFER_KM)
            self.anchorages[key] = (geom, row["name"])

    def anchorage(self, lon, lat):
        """Name of the (buffered) anchorage of every position ('' outside them)."""
        x, y = to_km(lon, lat)
        out = np.full(len(x), "", dtype=object)
        for key, (geom, _) in reversed(self.anchorages.items()):
            out[shapely.contains_xy(geom, x, y)] = key
        return out

    def sea_gate(self, x, y, cog, moving, backwards=True):
        """Edge a ship at sea crossed: along its course (back for an entry, ahead for an exit)
        if moving, else the nearest edge."""
        if moving and not math.isnan(cog):
            heading = math.radians(cog + 180 if backwards else cog)
            ray = LineString([(x, y), (x + 300 * math.sin(heading), y + 300 * math.cos(heading))])
            hits = {gate: ray.intersection(edge) for gate, edge in self.edges.items()}
            hits = {gate: hit for gate, hit in hits.items() if not hit.is_empty}
            if hits:
                return min(hits, key=lambda g: math.hypot(hits[g].centroid.x - x, hits[g].centroid.y - y))
        p = Point(x, y)
        return min(self.edges, key=lambda g: self.edges[g].distance(p))

    def first_seen(self, fix):
        """Where the first fix of a visit lies: port zone, anchorage, sea gate or unresolved."""
        if fix.port_zone:
            return fix.port_zone
        sog = 0.0 if math.isnan(fix.sog) else fix.sog
        stationary = sog < STATIONARY_KN or fix.nav_status == 1
        if stationary and fix.anchorage:
            return fix.anchorage
        if stationary and fix.nav_status == 1:
            return ANCHORAGE_OTHER
        if fix.lon < OPEN_SEA_MAX_LON:
            x, y = to_km(fix.lon, fix.lat)
            return self.sea_gate(float(x), float(y), fix.cog, not stationary)
        return UNRESOLVED

    def catalogue(self):
        out = {}
        for gate, desc in SEA_GATES.items():
            out[gate] = {"category": "sea", "description": desc}
        for key, (_, name) in self.anchorages.items():
            out[key] = {"category": "anchorage", "description": f"anchorage {name}"}
        out[ANCHORAGE_OTHER] = {"category": "anchorage",
                                "description": "anchored (nav status 1) outside the charted anchorages"}
        for name, (_, category, desc) in PORT_ZONES.items():
            out[name] = {"category": category, "description": desc}
        out[UNRESOLVED] = {"category": "unresolved",
                           "description": "first seen under way inside the Western Scheldt (AIS coverage gap)"}
        return out


class Berths:
    """Charted Antwerp berths (slots_cords), to split the Antwerp port zone by quay."""

    def __init__(self, path):
        with warnings.catch_warnings():
            # the layer has a few duplicate feature ids, which pyogrio renumbers
            warnings.simplefilter("ignore", RuntimeWarning)
            berths = gpd.read_file(path)
        number = pd.to_numeric(berths.LPL.str.extract(r"^[A-Z]?(\d+)")[0])
        zone = pd.Series(ANTWERP_OTHER, index=berths.index)
        for lo, hi, name, _ in ANTWERP_BERTH_ZONES:
            zone[number.between(lo, hi)] = name
        self.zone = zone.to_numpy()
        self.tree = shapely.STRtree([geom_to_km(g) for g in berths.geometry])

    def antwerp_zone(self, lon, lat):
        x, y = to_km(lon, lat)
        out = np.full(len(x), ANTWERP_OTHER, dtype=object)
        point_idx, berth_idx = self.tree.query_nearest(shapely.points(x, y), max_distance=BERTH_MATCH_KM)
        out[point_idx] = self.zone[berth_idx]
        return out


def destination_zones():
    """Every zone a ship can stop at in the Scheldt, with a description."""
    out = {name: desc for _, _, name, desc in ANTWERP_BERTH_ZONES}
    out[ANTWERP_OTHER] = ANTWERP_OTHER_DESCRIPTION
    for name, (_, _, desc) in PORT_ZONES.items():
        if name != "antwerp_port":
            out[name] = desc
    return out


# ---------------------------------------------------------------------------
# visits


def split_visits(df, restarts):
    """Number the visits: a new one starts at a ship's first fix, or when it is back somewhere
    else after NEW_VISIT_GAP_H. A gap that spans a collector restart is never a new visit."""
    df = df.sort_values(["mmsi", "t"]).reset_index(drop=True)
    same = df.mmsi.eq(df.mmsi.shift())
    gap_h = df.t.diff().dt.total_seconds().div(3600)
    r = restarts.to_numpy()
    across_restart = np.searchsorted(r, df.t.shift().to_numpy(), "right") != np.searchsorted(r, df.t.to_numpy(),
                                                                                             "right")
    px, py = to_km(df.lon.to_numpy(), df.lat.to_numpy())
    moved = np.hypot(np.diff(px, prepend=np.nan), np.diff(py, prepend=np.nan))
    new = ~same | ((gap_h > NEW_VISIT_GAP_H) & (moved > NEW_VISIT_MIN_MOVE_KM) & ~across_restart)
    df["visit"] = np.cumsum(new.to_numpy())
    return df


def annotate(df, zones, berths):
    """Add the zone columns used everywhere: port zone (Antwerp split by quay), anchorage, ..."""
    lon, lat = df.lon.to_numpy(), df.lat.to_numpy()
    df["port_zone"] = port_zone(lon, lat)
    in_antwerp = (df.port_zone == "antwerp_port").to_numpy()
    df["berth_zone"] = df.port_zone
    df.loc[in_antwerp, "berth_zone"] = berths.antwerp_zone(lon[in_antwerp], lat[in_antwerp])
    df["anchorage"] = zones.anchorage(lon, lat)
    scheldt_ports = [name for name, (_, category, _) in PORT_ZONES.items() if category == "port_channel"]
    df["in_scheldt"] = (((df.lon >= SCHELDT_MIN_LON) & (df.lat <= SCHELDT_MAX_LAT))
                        | df.port_zone.isin(scheldt_ports)).to_numpy()
    df["stationary"] = ((df.sog < STATIONARY_KN) | (df.sog.isna() & df.nav_status.isin([1, 5]))).to_numpy()
    return df


def scheldt_destination(destinations):
    """Is the first destination of the visit a Scheldt port? 'DEHAM>BEANR' means bound for BEANR."""
    if destinations.empty:
        return False
    return bool(SCHELDT_DESTINATION.search(destinations.iloc[0].upper().split(">")[-1]))


def summarise_visits(df, times):
    """One row per visit: start/end, whether its end was seen, whether it is Scheldt traffic."""
    g = df.groupby("visit")
    visits = pd.DataFrame({
        "mmsi": g.mmsi.first(), "start": g.t.first(), "end": g.t.last(),
        "reaches_scheldt": g.in_scheldt.any(),
        "scheldt_destination": g.destination.agg(lambda s: scheldt_destination(s.dropna())),
    })
    # the end of a visit is seen only if the collector kept running after the ship's last fix
    snap, end = times.dt.tz_convert(None).to_numpy(), visits.end.dt.tz_convert(None).to_numpy()
    idx = np.searchsorted(snap, end, "right")
    gap_min = (snap[np.minimum(idx, len(snap) - 1)] - end) / np.timedelta64(1, "m")
    visits["end_observed"] = (idx < len(snap)) & (gap_min <= MAX_SNAPSHOT_GAP_MIN)
    ongoing = (visits.end >= times.iloc[-1] - pd.Timedelta(minutes=MAX_SNAPSHOT_GAP_MIN)).to_numpy()
    # still heading/waiting for the Scheldt when the data ends counts as Scheldt traffic
    visits["scheldt_bound"] = visits.reaches_scheldt | (ongoing & visits.scheldt_destination)
    return visits


def find_entries(df, windows, zones):
    """One row per visit that started inside an observed window, with its entry source."""
    starts = df.groupby("visit").head(1)
    observed = np.zeros(len(starts), dtype=bool)
    for lo, hi in windows:
        observed |= ((starts.t > lo) & (starts.t <= hi)).to_numpy()
    log.info("%d visits, %d start inside the observed windows (the rest were already in the area)",
             len(starts), observed.sum())

    fixes = df[df.visit.isin(starts.visit[observed])]
    anchored = (fixes.anchorage != "") & ((fixes.sog.fillna(0) < STATIONARY_KN) | (fixes.nav_status == 1))
    rows = []
    for visit, fx in fixes.groupby("visit", sort=False):
        first = next(fx.itertuples())
        seen = zones.first_seen(first)
        source = seen
        if seen in SEA_GATES:
            # came in from sea: did it anchor before it reached a port?
            in_port = (fx.port_zone != "").to_numpy()
            before_port = fx[: int(np.argmax(in_port)) if in_port.any() else len(fx)]
            counts = before_port.anchorage[anchored.loc[before_port.index]].value_counts()
            counts = counts[counts >= ANCHORED_MIN_FIXES]
            if len(counts):
                source = before_port.anchorage[before_port.anchorage.isin(counts.index)].iloc[0]
        rows.append({"visit": visit, "mmsi": first.mmsi, "t": first.t, "lat": first.lat, "lon": first.lon,
                     "first_seen": seen, "source": source})
    return pd.DataFrame(rows)


def find_stops(df):
    """Every period a ship lies still for STOP_MIN_H within STOP_RADIUS_KM.

    kind is 'berth' (in a port zone; zone = berth zone), 'anchorage' (zone = anchorage) or
    'other'. start_observed / end_observed say whether the ship was seen under way just
    before / after; a stop that runs into the first or last fix of its visit is censored.
    """
    t = df.t.dt.tz_convert(None).to_numpy().astype("datetime64[s]").astype(np.int64)
    x, y = to_km(df.lon.to_numpy(), df.lat.to_numpy())
    still = df.stationary.to_numpy()
    visit = df.visit.to_numpy()
    bounds = np.flatnonzero(np.r_[True, visit[1:] != visit[:-1], True])
    cont = STOP_CONTINUITY_MIN * 60
    spans = []
    for i0, i1 in zip(bounds[:-1], bounds[1:]):
        j = i0
        while j < i1:
            if not still[j]:
                j += 1
                continue
            k = j
            while k + 1 < i1 and still[k + 1] and math.hypot(x[k + 1] - x[j], y[k + 1] - y[j]) <= STOP_RADIUS_KM:
                k += 1
            if t[k] - t[j] >= STOP_MIN_H * 3600:
                spans.append((j, k, j > i0 and t[j] - t[j - 1] <= cont, k + 1 < i1 and t[k + 1] - t[k] <= cont,
                              j == i0))
            j = k + 1

    lat, lon, mmsi = df.lat.to_numpy(), df.lon.to_numpy(), df.mmsi.to_numpy()
    port, berth, anchorage, when = (df.port_zone.to_numpy(), df.berth_zone.to_numpy(), df.anchorage.to_numpy(),
                                    df.t.to_numpy())
    rows = []
    for j, k, start_obs, end_obs, at_visit_start in spans:
        mid = (j + k) // 2
        if port[mid]:
            kind, zone = "berth", berth[mid]
        elif anchorage[mid]:
            kind, zone = "anchorage", anchorage[mid]
        else:
            kind, zone = "other", ""
        rows.append({"visit": visit[mid], "mmsi": mmsi[mid], "kind": kind, "zone": zone,
                     "lat": float(np.median(lat[j:k + 1])), "lon": float(np.median(lon[j:k + 1])),
                     "start": when[j], "end": when[k], "hours": (t[k] - t[j]) / 3600,
                     "start_observed": bool(start_obs), "end_observed": bool(end_obs),
                     "at_visit_start": bool(at_visit_start)})
    stops = pd.DataFrame(rows)
    log.info("%d stops: %s", len(stops), stops.kind.value_counts().to_dict())
    return stops


def berth_calls(stops):
    """Berth stops that are calls, not lock passages, each with the shortest a call there can be
    (truncated_at), which the duration fits need."""
    berth = stops[stops.kind == "berth"].copy()
    berth["truncated_at"] = np.where(berth.zone.isin(LOCK_ZONES), LOCK_STOP_MAX_H, STOP_MIN_H)
    return berth[berth.hours >= berth.truncated_at]


def visit_exits(df, visits, zones):
    """Where each visit with a seen end left the area. Visits whose AIS went quiet while lying
    still (switched off at a berth) or under way inside Antwerp have no exit."""
    last = df.groupby("visit").tail(1).set_index("visit")
    exits = {}
    for visit in visits.index[visits.end_observed]:
        fix = last.loc[visit]
        if fix.stationary or fix.port_zone == "antwerp_port":
            continue
        if fix.port_zone:
            exits[visit] = fix.port_zone
        elif fix.lon < OPEN_SEA_MAX_LON:
            x, y = to_km(fix.lon, fix.lat)
            exits[visit] = zones.sea_gate(float(x), float(y), fix.cog, True, backwards=False)
        else:
            exits[visit] = UNRESOLVED
    return pd.Series(exits, dtype=object)


def prepare(ais_dir=AIS_DIR, schedule=SCHEDULE, charts=CHARTS, berths=BERTHS):
    """Run the whole pipeline; returns a namespace with df, times, windows, ships, zones,
    visits and entries (each entry with its class and whether it is Scheldt traffic)."""
    df, times, area = load_snapshots(ais_dir)
    windows, restarts = observation_windows(times)
    log.info("Collector (re)started %d times; %d observed windows", len(restarts), len(windows))

    scheduled = pd.read_csv(schedule, sep=";")
    scheduled_names = set(scheduled.Vessel.map(normalise_name))
    ships = static_per_ship(df)
    ships["class"] = [classify(s, scheduled_names) for s in ships.itertuples()]
    log.info("Ships per class: %s", ships["class"].value_counts().to_dict())

    zones = EntryZones(area, charts)
    df = annotate(split_visits(df, restarts), zones, Berths(berths))
    visits = summarise_visits(df, times)
    visits["class"] = visits.mmsi.map(ships["class"])
    entries = find_entries(df, windows, zones)
    entries["class"] = entries.mmsi.map(ships["class"])
    entries["reaches_scheldt"] = entries.visit.map(visits.reaches_scheldt)
    entries["scheldt_bound"] = entries.visit.map(visits.scheldt_bound)
    return SimpleNamespace(df=df, times=times, windows=windows, restarts=restarts, schedule=scheduled,
                           ships=ships, zones=zones, visits=visits, entries=entries)


# ---------------------------------------------------------------------------
# fitting and output helpers


def normalise(counts):
    total = sum(counts.values())
    return {k: round(v / total, 4) for k, v in counts.items() if v} if total else {}


def fit_lognormal(hours, observed, truncated_at=STOP_MIN_H):
    """Lognormal MLE for durations with right censoring (observed=False: lasted at least that
    long) and left truncation (only durations >= truncated_at are ever recorded; a number,
    or one per duration)."""
    x, ev = np.asarray(hours, dtype=float), np.asarray(observed, dtype=bool)
    if ev.sum() < 3:
        return None
    logx = np.log(x)
    logt = np.log(np.broadcast_to(np.asarray(truncated_at, dtype=float), x.shape))

    def nll(p):
        mu, sigma = p[0], math.exp(p[1])
        z = (logx - mu) / sigma
        ll = np.where(ev, stats.norm.logpdf(z) - math.log(sigma) - logx, stats.norm.logsf(z))
        return -(ll - stats.norm.logsf((logt - mu) / sigma)).sum()

    # bounded: with mostly censored stays the likelihood can keep rising towards huge sigma
    bounds = [(float(logt.min()) - 3, math.log(24 * 60)), (math.log(LOGNORMAL_SIGMA[0]), math.log(LOGNORMAL_SIGMA[1]))]
    start = [min(max(logx.mean(), bounds[0][0]), bounds[0][1]), math.log(min(max(logx.std(), 0.2), 2.0))]
    res = optimize.minimize(nll, start, method="L-BFGS-B", bounds=bounds)
    mu, sigma = float(res.x[0]), float(math.exp(res.x[1]))
    at_bound = any(abs(v - b) < 1e-3 for v, pair in zip(res.x, bounds) for b in pair)
    return {"mu": round(mu, 4), "sigma": round(sigma, 4), "median_h": round(math.exp(mu), 2),
            "mean_h": round(math.exp(mu + sigma ** 2 / 2), 2), "n_complete": int(ev.sum()),
            "n_censored": int((~ev).sum()), "longest_seen_h": round(float(x.max()), 2), "at_bound": at_bound}


def write_module(path, docstring, tables, functions=""):
    """Write a generated module: a docstring, one constant per table, then helper functions."""
    lines = ['"""' + docstring.strip("\n"), '"""', ""]
    for key, value in tables.items():
        lines += [f"{key} = {pprint.pformat(value, width=110, sort_dicts=False, compact=True)}", ""]
    path.write_text("\n".join(lines).rstrip() + "\n" + functions, encoding="utf-8")
    log.info("Wrote %s", path)
