"""Container terminals and the berth catalogue (PLAN.md §7, alokacja_przestrzenna_w_terminalach.md,
sprzet_ladunkowy.md, regs §8.10-8.11, §10).

A terminal is a resource like a lock or an anchorage: graph.graph["terminals"][i]["resource"] is a
Terminal object.

    quay_line      the quay as a polyline (projected metres), built from the quay-side edges of the
                   terminal's berth polygons; positions along it are "quay metres" (s)
    berths         the charted berth slots on it: their quay range (s0, s1) and graph nodes
    find_position  best fit along the quay (the shortest free stretch that takes it): a ship needs LOA plus the mooring gap to each neighbour
                   (20-25 m, Antwerp); None if it does not fit (the ship waits at anchor)
    moor / unmoor  occupy / free a stretch of quay
    cranes         STS cranes: at most floor(LOA / 45 m) per ship (crane density), MPET at most 9,
                   never more than the terminal has free
    handling_hours moves / (cranes x moves per hour)
    berthing_allowed  the tidal berthing windows (regs §8.10)
    head_out       Deurganckdok: ships over 210 m moor bow to the river (regs §10.6)

build_berth_catalogue() makes graph.graph["berths"]: every charted berth slot with its size, quay
edge, graph nodes, depth, zone, tidal or behind a lock, and the AIS use (calls per class, tanker berth).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import LineString

log = logging.getLogger("terminals")

MOVE_TO_TEU = 1.55
STS_CYCLE_S = (95.0, 5.0)                # normal (mean, sd) seconds per move
STS_BUFFER_CAPACITY = 4                  # containers under a crane before it blocks
YARD_DELAY_S = (240.0, 30.0)             # normal (mean, sd): a straddle carrier clears one container
CRANE_SPACING_M = 45.0                   # one STS per 45 m of ship (crane density limit)
# Berth slots of one quay drawn with a gap between them are one stretch of quay: PSA Europa's slots leave 50 m
# at quay metre 883 and PSA Noordzee's 50 m at 820, on quays that are straight and unbroken, and a ship of 340 m
# found no place across them. A slot that does not take the ship (an inland berth, a shallower one) still splits.
QUAY_JOIN_M = 60.0
MIN_CRANE_GAP_M = 15.0                   # two cranes on one ship keep one bay free between them
MOORING_GAP_M = (20.0, 25.0)             # between moored ships, Antwerp

# documented data per terminal (alokacja_przestrzenna_w_terminalach.md, sprzet_ladunkowy.md, regs §8.10/§10.6)
TERMINAL_SPECS = {
    "MPET": {"sts": 41, "moves_per_crane_h": 37.0, "max_cranes_per_ship": 9, "head_out_over_m": 210.0,
             "yard": "straddle carriers (~200)"},
    "DP World Antwerp Gateway": {"sts": 13, "moves_per_crane_h": 40.0, "max_cranes_per_ship": None,
                                 "head_out_over_m": 210.0, "yard": "ASC (34) + hybrid straddle carriers (~70)",
                                 "barge_quay_m": 200.0},
    "PSA Noordzee Terminal": {"sts": 14, "moves_per_crane_h": 37.0, "max_cranes_per_ship": None, "head_out_over_m": None,
                              "yard": "straddle carriers (~100)",
                              # S901/S903 (overlap S905), ships > 300 m: (un)berth only on the rising tide up to HW + 1 h
                              "tide_windows": [{"berths": ("ANTW_S901", "ANTW_S903", "ANTW_S905"), "min_loa_m": 300.0,
                                                "rising": True, "until_after_hw_h": 1.0}]},
    "PSA Europa Terminal": {"sts": 10, "moves_per_crane_h": 33.5, "max_cranes_per_ship": None, "head_out_over_m": None,
                            "yard": "straddle carriers, moving to ASC (Emerald project)"},
}


@dataclass
class Moored:
    ship_id: str
    loa: float
    s0: float
    s1: float
    since: float
    cranes: int = 0
    head_out: bool = False
    arrived: bool = True                  # False: quay booked for a ship still on its way
    leaves: float | None = None           # minute its quay is planned to be free again (None: not known)


@dataclass
class Terminal:
    name: str
    code: str
    quay_line: list                       # [(x, y), ...]
    quay_length_m: float                  # measured along quay_line
    documented_quay_m: float
    max_draft_m: float
    sts: int
    moves_per_crane_h: float
    max_cranes_per_ship: int | None = None
    head_out_over_m: float | None = None
    tide_windows: list = field(default_factory=list)
    berths: dict = field(default_factory=dict)   # berth id -> {"s0", "s1", "nodes"}
    ships: list = field(default_factory=list)
    gap_m: float = sum(MOORING_GAP_M) / 2

    # --- quay ---------------------------------------------------------------
    def free_intervals(self, at=None):
        """Stretches of quay [a, b] where a new ship's hull may lie (gaps to the moored ships kept). at: for
        a ship that gets there at this minute, so the quay of a ship planned to have left by then counts as
        free (berth planning: the next ship sails in while the one before it is still working)."""
        busy = sorted((s.s0 - self.gap_m, s.s1 + self.gap_m) for s in self.ships
                      if at is None or s.leaves is None or s.leaves > at)
        out, a = [], 0.0
        for b0, b1 in busy:
            if b0 > a:
                out.append((a, b0))
            a = max(a, b1)
        if a < self.quay_length_m:
            out.append((a, self.quay_length_m))
        return out

    def suitable_intervals(self, draught=None, sea_going=True):
        """Stretches of quay whose berth slots take this ship: sea-going slots (harbour master's
        category) allowing its draught; slots without data count as suitable."""
        spans = sorted((r["s0"], r["s1"]) for r in self.berths.values()
                       if (draught is None or r.get("max_draught") is None or r["max_draught"] >= draught)
                       and (not sea_going or r.get("category") in (None, "zeevaart")))
        out = []
        for a, b in spans:
            if out and a <= out[-1][1] + QUAY_JOIN_M:
                out[-1] = (out[-1][0], max(out[-1][1], b))
            else:
                out.append((a, b))
        return out

    def find_position(self, loa, near_s=None, draught=None, sea_going=True, at=None):
        """Quay metre where a ship of this length can lie (first fit, or the fit nearest near_s):
        free quay (at minute `at`, see free_intervals) that is also suitable for its draught and kind
        (suitable_intervals)."""
        free = self.free_intervals(at)
        if draught is not None or sea_going:
            ok = self.suitable_intervals(draught, sea_going)
            free = [(max(a, c), min(b, d)) for a, b in free for c, d in ok if min(b, d) > max(a, c)]
        fits = [(a, b) for a, b in free if b - a >= loa]
        if not fits:
            return None
        if near_s is None:
            # best fit: the shortest free stretch that takes the ship, so long (and deep) stretches stay
            # free for the long ships that need them; first fit let small ships fragment them
            return min(fits, key=lambda ab: (ab[1] - ab[0], ab[0]))[0]
        return min((min(max(near_s, a), b - loa) for a, b in fits), key=lambda s: abs(s - near_s))

    def free_quay_m(self):
        return sum(b - a for a, b in self.free_intervals())

    def moor(self, ship_id, loa, now, s0=None, cranes=0, at=None, arrived=True):
        """Moor a ship (at s0, or the first fit), or book its quay for minute `at` (arrived=False); returns
        its Moored, or None if it does not fit."""
        if s0 is None:
            s0 = self.find_position(loa, at=at)
        elif not any(a <= s0 and s0 + loa <= b for a, b in self.free_intervals(at)):
            s0 = None
        if s0 is None:
            return None
        ship = Moored(ship_id, loa, s0, s0 + loa, now, head_out=self.head_out(loa), arrived=arrived)
        self.ships.append(ship)
        if cranes:
            self.assign_cranes(ship_id, cranes)
        return ship

    def unmoor(self, ship_id, now):
        ship = self.ship(ship_id)
        self.ships.remove(ship)
        return {"t": now, "terminal": self.name, "event": "unmoored", "ship": ship_id,
                "hours": round((now - ship.since) / 60, 2), "cranes": ship.cranes}

    def ship(self, ship_id):
        return next(s for s in self.ships if s.ship_id == ship_id)

    def quay_clear(self, ship_id):
        """Has every other ship left the quay this ship is booked on (gaps kept)?"""
        me = self.ship(ship_id)
        return not any(s.arrived and s is not me and s.s0 - self.gap_m < me.s1 and s.s1 + self.gap_m > me.s0
                       for s in self.ships)

    def berths_at(self, s0, s1):
        """Charted berth slots overlapping quay metres s0..s1."""
        return [b for b, r in self.berths.items() if r["s0"] < s1 and r["s1"] > s0]

    def nodes_at(self, s0, s1):
        return sorted({n for b in self.berths_at(s0, s1) for n in self.berths[b]["nodes"]})

    # --- cranes -------------------------------------------------------------
    def max_cranes(self, loa):
        """Crane density limit: floor(LOA / 45 m), the terminal's cap per ship, its fleet."""
        n = int(loa // CRANE_SPACING_M)
        if self.max_cranes_per_ship:
            n = min(n, self.max_cranes_per_ship)
        return min(n, self.sts)

    def free_cranes(self):
        return self.sts - sum(s.cranes for s in self.ships)

    def assign_cranes(self, ship_id, n):
        """Give a moored ship n cranes (capped by density and what is free); returns the number given."""
        ship = self.ship(ship_id)
        n = max(0, min(n, self.max_cranes(ship.loa), self.free_cranes() + ship.cranes))
        ship.cranes = n
        return n

    def handling_hours(self, moves, cranes):
        return moves / (max(cranes, 1) * self.moves_per_crane_h)

    # --- rules --------------------------------------------------------------
    def head_out(self, loa):
        return self.head_out_over_m is not None and loa > self.head_out_over_m

    def berthing_allowed(self, loa, s0, rising, hours_after_hw):
        """Tidal berthing windows (regs §8.10): rising = the tide is rising now; hours_after_hw =
        time since the last high water (h)."""
        for w in self.tide_windows:
            if loa <= w["min_loa_m"] or not set(self.berths_at(s0, s0 + loa)) & set(w["berths"]):
                continue
            if not (rising or hours_after_hw <= w["until_after_hw_h"]):
                return False
        return True

    def departure_allowed(self, ship_id, rising, hours_after_hw):
        """Deurganckdok: a ship not moored head-out leaves only on the rising tide up to HW (regs §8.10)."""
        ship = self.ship(ship_id)
        if self.head_out_over_m is not None and not ship.head_out:
            return rising
        return self.berthing_allowed(ship.loa, ship.s0, rising, hours_after_hw)

    def summary(self):
        return {"ships": len(self.ships), "free_quay_m": round(self.free_quay_m()), "free_cranes": self.free_cranes()}


# ---------------------------------------------------------------------------
# building


def _rect_sides(poly):
    """The two long sides of a berth polygon's minimum rotated rectangle, and its length and width."""
    c = shapely.get_coordinates(poly.minimum_rotated_rectangle)[:4]
    sides = [(c[i], c[(i + 1) % 4]) for i in range(4)]
    lengths = [math.hypot(*(b - a)) for a, b in sides]
    i = int(np.argmax(lengths))
    return (sides[i], sides[(i + 2) % 4]), max(lengths), min(lengths)


def quay_edge(poly, water_tree, probe_m=60.0, radius_m=40.0):
    """The long side of a berth polygon against the quay: the one with less water (graph nodes)
    beyond it."""
    sides, length, width = _rect_sides(poly)
    centre = np.array(poly.centroid.coords[0])
    best = None
    for p, q in sides:
        mid = (p + q) / 2
        out = mid - centre
        out /= max(np.hypot(*out), 1e-9)
        probe = shapely.Point(*(mid + out * probe_m))
        n = len(water_tree.query(probe, predicate="dwithin", distance=radius_m))
        if best is None or n < best[0]:
            best = (n, p, q)
    return (best[1], best[2]), length, width


HARBOUR_MASTER_FIELDS = ("max_draught_m", "sounded_depth_taw_m", "design_depth_taw_m", "min_ukc_m", "max_loa_m",
                         "max_beam_m", "max_moored_width_m", "max_moored_length_m", "mooring_side", "swing_min",
                         "berth_length_m", "category", "quay_type", "berth_type")


# company plot activities (havenmeester map layer 20) that make the berths in front of them tanker berths, and the
# ones that say nothing about the cargo. Checked against the berths with the harbour master's berth type: the plot
# gives the same answer for 90 % of them (natte bulk 82 %, raffinage 90 %, chemie 60 %), the AIS calls for 78 %.
TANKER_PLOT_ACTIVITIES = ("natte bulk", "raffinage", "chemie")
SILENT_PLOT_ACTIVITIES = ("dienstverlening", "niet gekend", "niet van toepassing", "logistieke infrastructuur")


def plot_tanker(activity):
    """Tanker berth by the company plot behind it: True / False, or None if the plot does not tell."""
    if not activity or activity in SILENT_PLOT_ACTIVITIES:
        return None
    return activity in TANKER_PLOT_ACTIVITIES


def _value(v):
    if v is None or (isinstance(v, float) and v != v):
        return None
    return v.item() if hasattr(v, "item") else v


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def build_berth_catalogue(graph, berths, berth_nodes, zone_of, use=None):
    """graph.graph["berths"]: every charted berth slot (see the module docstring).
    berths: GeoDataFrame in the graph CRS with LPL_UN, LPL, TYPE, TERMINAL, HOEK, number;
    zone_of(number) -> berth zone name; use: port_infrastructure.BERTH_USE or None."""
    from pyproj import Transformer

    to_lonlat = Transformer.from_crs(graph.graph["crs"], "EPSG:4326", always_xy=True).transform
    water = [n for n, d in graph.nodes(data=True) if d["type"] not in ("lock", "anchorage", "approach")]
    tree = shapely.STRtree(shapely.points([graph.nodes[n]["x"] for n in water], [graph.nodes[n]["y"] for n in water]))
    use = use or {}
    out = {}
    for row in berths.itertuples():
        if row.LPL_UN in out and _rect_sides(row.geometry)[1] <= out[row.LPL_UN]["length_m"]:
            continue                               # a few ids have several polygons: keep the longest
        (p, q), length, width = quay_edge(row.geometry, tree)
        nodes = berth_nodes.get(row.LPL_UN, [])
        depths = [graph.nodes[n]["depth_m"] for n in nodes]
        basins = {graph.nodes[n].get("basin") for n in nodes}
        lon, lat = to_lonlat(row.geometry.centroid.x, row.geometry.centroid.y)
        u = use.get(row.LPL_UN)
        hm = {k: _value(getattr(row, k, None)) for k in HARBOUR_MASTER_FIELDS}
        quay, kind = hm["quay_type"], hm["berth_type"] or ""
        official_tanker = (None if quay is None and not kind
                           else quay == "Tanker" or any(w in kind for w in ("Tank", "Gas", "LNG", "Biofuel")))
        activity = _value(getattr(row, "plot_activity", None))
        by_plot = plot_tanker(activity)
        # tanker berth: the harbour master's berth type, else the company plot behind it, else the AIS calls
        tanker, tanker_source = ((official_tanker, "harbour master") if official_tanker is not None
                                 else (by_plot, "company plot") if by_plot is not None
                                 else (u["tanker_berth"], "AIS") if u and u.get("tanker_berth") is not None
                                 else (None, None))
        out[row.LPL_UN] = {
            "lpl": _value(row.LPL), "number": None if row.number != row.number else int(row.number),
            "type_code": _int(row.TYPE),
            "size_class": "seagoing" if width >= 40 else "inland" if width >= 20 else "small_craft",
            "length_m": round(length, 1), "width_m": round(width, 1), "heading_deg": float(row.HOEK) if _value(row.HOEK) is not None else None,
            "terminal_code": row.TERMINAL if isinstance(row.TERMINAL, str) else None,
            "zone": zone_of(row.number), "longitude": round(float(lon), 6), "latitude": round(float(lat), 6),
            "quay_edge": [(round(float(p[0]), 1), round(float(p[1]), 1)), (round(float(q[0]), 1), round(float(q[1]), 1))],
            "nodes": nodes, "depth_m": round(float(np.median(depths)), 2) if depths else None,
            "tidal": None if not nodes else basins == {None}, "basin": next(iter(basins - {None}), None),
            "calls": u["calls"] if u else {}, "max_loa_seen_m": u["max_loa_m"] if u else None,
            # the harbour master's data (None where it gives none)
            **hm, "tanker_official": official_tanker,
            "plot_activity": activity, "plot_company": _value(getattr(row, "plot_company", None)),
            "tanker_berth": tanker, "tanker_source": tanker_source,
        }
    graph.graph["berths"] = out
    log.info("berth catalogue: %d berths (%d with nodes, %d with an allowed draught, %d tanker berths: %d official, "
             "%d by company plot, %d by AIS; %d not known)", len(out), sum(bool(b["nodes"]) for b in out.values()),
             sum(b["max_draught_m"] is not None for b in out.values()), sum(bool(b["tanker_berth"]) for b in out.values()),
             sum(bool(b["tanker_official"]) for b in out.values()),
             sum(bool(b["tanker_berth"]) and b["tanker_source"] == "company plot" for b in out.values()),
             sum(bool(b["tanker_berth"]) and b["tanker_source"] == "AIS" for b in out.values()),
             sum(b["tanker_berth"] is None for b in out.values()))
    return out


def _quay_line(edges):
    """Order the quay edges along their main direction and join them into one polyline."""
    pts = np.array([pt for e in edges for pt in e], dtype=float)
    centre = pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts - centre)
    axis = vt[0]
    ordered = sorted((sorted(e, key=lambda pt: float(np.dot(np.array(pt) - centre, axis))) for e in edges),
                     key=lambda e: float(np.dot(np.array(e[0]) - centre, axis)))
    line = [ordered[0][0]]
    for a, b in ordered:
        if float(np.dot(np.array(b) - np.array(line[-1]), axis)) > 0:
            if float(np.dot(np.array(a) - np.array(line[-1]), axis)) > 0:
                line.append(a)
            line.append(b)
    return LineString(line)


def build_terminals(graph, specs=TERMINAL_SPECS):
    """A Terminal for each entry of graph.graph["terminals"] (needs graph.graph["berths"])."""
    catalogue = graph.graph["berths"]
    for t in graph.graph["terminals"]:
        ids = [b for b, r in catalogue.items() if r["terminal_code"] == t["code"]]
        if not ids:
            continue
        line = _quay_line([catalogue[b]["quay_edge"] for b in ids])
        spec = specs.get(t["name"], {})
        berths = {}
        for b in ids:
            s = sorted(line.project(shapely.Point(pt)) for pt in catalogue[b]["quay_edge"])
            berths[b] = {"s0": round(s[0], 1), "s1": round(s[1], 1), "nodes": catalogue[b]["nodes"],
                         "max_draught": catalogue[b].get("max_draught_m"), "category": catalogue[b].get("category")}
        term = Terminal(t["name"], t["code"], [(round(x, 1), round(y, 1)) for x, y in line.coords], round(line.length, 1),
                        t["quay_m"], t["draft_m"], spec.get("sts", 0), spec.get("moves_per_crane_h", 37.0),
                        spec.get("max_cranes_per_ship"), spec.get("head_out_over_m"), spec.get("tide_windows", []), berths)
        t.update(resource=term, quay_line=term.quay_line, quay_length_measured_m=term.quay_length_m,
                 sts=term.sts, yard=spec.get("yard"))
        log.info("terminal %-26s quay %5.0f m measured (%5.0f documented), %2d berth slots, %2d STS", t["name"],
                 term.quay_length_m, t["quay_m"], len(berths), term.sts)
