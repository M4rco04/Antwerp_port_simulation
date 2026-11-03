"""Pilots, pilot boats, tugs and boatmen (PLAN.md §6): pools of light agents with a state.

Fleet sizes come from the repo:
    tugs        data/equipment/tugs.csv (the 42 Antwerp harbour tugs), spread over the Antwerp tug
                bases seen in AIS (src/data/port_infrastructure.py TUG_BASES) in proportion to the
                vessels seen there; the other bases (Vlissingen, Terneuzen, ...) get the tugs AIS saw there
    pilot boats data/equipment/pilots_mdk.csv (the 8 LRD/MDK pilot tenders): one is busy for
                PILOT_BOAT_MIN for every boarding / landing at sea and at Vlissingen
    boatmen     data/equipment/pilots_brabo.csv (the Brabo boats, Antwerp's boatmen): one crew per
                mooring / unmooring at or behind the locks (regs §2, HPV 8.4.2)
    pilots      the repo has no count of pilots, so each zone gets PILOT_PEAK_FACTOR x the most ships
                that needed a pilot there at once in the AIS (port_infrastructure.PILOT_DEMAND), times
                (1 + return time / time on board) since AIS sees only the pilots on board

A pilot works in one zone (sea: pilot station - Vlissingen; river: Vlissingen - Antwerp; dock:
behind the locks) and after a job is away for its zone's return time (PILOT_RETURN_MIN). The VTS books
the pilots for the later stretches of a voyage when it clears the ship (book): a booked pilot still
takes other jobs that end (time on board + return) before its booking.
A tug sails from its base to the ship (TUG_SPEED_KN, straight line x DETOUR), assists, and sails back.
"""

from __future__ import annotations

import csv
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EQUIPMENT = ROOT / "data" / "equipment"
PILOT_PEAK_FACTOR = 1.25
PILOT_RETURN_MIN = {"sea": 120.0, "river": 90.0, "dock": 30.0}      # assumed
PILOT_LEG_MIN = {"sea": 150.0, "river": 180.0, "dock": 60.0}        # assumed typical time on board
PILOT_BOAT_MIN = 30.0                                                # assumed, one transfer
BOOKING_EXPIRY_MIN = 360.0          # a pilot booking not taken up 6 h after its time lapses
TUG_SPEED_KN = 8.0
DETOUR = 1.3
KNOT_M_MIN = 1852.0 / 60.0


def _rows(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter=";"))


def _infrastructure():
    sys.path.insert(0, str(ROOT / "src" / "data"))
    import port_infrastructure
    return port_infrastructure


@dataclass
class Pilot:
    id: str
    zone: str
    ship: str | None = None
    free_at: float = 0.0
    since: float = 0.0                 # when it went on board its current ship
    bookings: dict = field(default_factory=dict)   # ship id -> time it is booked from (later stretches)


class PilotPool:
    def __init__(self, sizes=None):
        if sizes is None:
            demand = _infrastructure().PILOT_DEMAND
            # AIS shows the pilots on board; each is also away for the return trip afterwards
            sizes = {z: math.ceil(PILOT_PEAK_FACTOR * d["max"] * (1 + PILOT_RETURN_MIN[z] / PILOT_LEG_MIN[z]))
                     for z, d in demand.items()}
        self.sizes = sizes
        self.pilots = [Pilot(f"{z}_{i + 1}", z) for z, n in sizes.items() for i in range(n)]

    def _job_min(self, zone):
        return PILOT_LEG_MIN[zone] + PILOT_RETURN_MIN[zone]

    def _expire(self, now):
        for p in self.pilots:                       # a booking not used long after its time lapses
            for k in [k for k, t in p.bookings.items() if now > t + BOOKING_EXPIRY_MIN]:
                del p.bookings[k]

    def _clash(self, p, start, end, ship_id=None):
        """Another ship's booking of p would fall inside [start, end) or begin within one job of it."""
        job = self._job_min(p.zone)
        return any(k != ship_id and start - job < t < end for k, t in p.bookings.items())

    def free(self, zone, now, ship_id=None):
        """Pilots of the zone free now for ship_id: not on board, back from their last job, booked by
        this ship or with no other ship's booking before this job (time on board + return) ends."""
        self._expire(now)
        job = self._job_min(zone)
        return [p for p in self.pilots if p.zone == zone and p.ship is None and p.free_at <= now
                and (ship_id in p.bookings or not self._clash(p, now, now + job, ship_id))]

    def available(self, zone, n, now, ship_id=None):
        return len(self.free(zone, now, ship_id)) >= n

    def take(self, zone, n, ship_id, now):
        free = self.free(zone, now, ship_id)
        free.sort(key=lambda p: ship_id not in p.bookings)       # its own booked pilots first
        if len(free) < n:
            return None
        for p in free[:n]:
            p.ship, p.since = ship_id, now
            p.bookings.pop(ship_id, None)
        return free[:n]

    def release(self, pilots, now):
        for p in pilots:
            p.ship, p.free_at = None, now + PILOT_RETURN_MIN[p.zone]

    def expected_free(self, p, now):
        """When a pilot will be free again: on board, after its usual time on board and the return."""
        if p.ship is not None:
            return max(now, p.since + PILOT_LEG_MIN[p.zone]) + PILOT_RETURN_MIN[p.zone]
        return max(now, p.free_at)

    def _bookable(self, zone, at, now, ship_id=None):
        """Pilots that will be back by `at` and have no other booking within one job of it."""
        job = self._job_min(zone)
        return sorted((p for p in self.pilots if p.zone == zone and self.expected_free(p, now) <= at
                       and not self._clash(p, at, at + job, ship_id)), key=lambda p: self.expected_free(p, now))

    def can_book(self, zone, n, at, now):
        self._expire(now)
        return len(self._bookable(zone, at, now)) >= n

    def book(self, zone, n, ship_id, at, now):
        """Book n pilots of the zone for ship_id from time `at`; False (nothing booked) if not enough."""
        self._expire(now)
        got = self._bookable(zone, at, now, ship_id)
        if len(got) < n:
            return False
        for p in got[:n]:
            p.bookings[ship_id] = at
        return True

    def cancel(self, ship_id):
        for p in self.pilots:
            p.bookings.pop(ship_id, None)

    def booked(self, zone, now):
        return sum(len(p.bookings) for p in self.pilots if p.zone == zone)

    def busy(self, zone, now):
        return sum(1 for p in self.pilots if p.zone == zone and (p.ship or p.free_at > now))


class CounterPool:
    """Identical units busy until a time (pilot boats, boatmen crews)."""

    def __init__(self, n, name):
        self.n, self.name, self.busy_until = n, name, [0.0] * n

    def available(self, now):
        return sum(1 for t in self.busy_until if t <= now)

    def take(self, now, minutes):
        for i, t in enumerate(self.busy_until):
            if t <= now:
                self.busy_until[i] = now + minutes
                return True
        return False

    def hold(self, now):
        """Take a unit until release() (open-ended)."""
        return self.take(now, math.inf)

    def release(self, now):
        for i, t in enumerate(self.busy_until):
            if t == math.inf:
                self.busy_until[i] = now
                return


def pilot_boats():
    return CounterPool(len(_rows(EQUIPMENT / "pilots_mdk.csv")), "pilot boats")


def boatmen():
    names = {r["Name"].replace(" ", "").upper() for r in _rows(EQUIPMENT / "pilots_brabo.csv")}
    return CounterPool(len(names), "boatmen")


@dataclass
class Tug:
    id: str
    name: str
    bollard_pull_t: float | None
    base: str
    x: float
    y: float
    ship: str | None = None
    free_at: float = 0.0


class TugPool:
    def __init__(self, places):
        """places: graph.graph["places"] with the tug bases; positions via the graph nodes."""
        self.places = places
        infra = _infrastructure()
        rows = _rows(EQUIPMENT / "tugs.csv")
        bases = [b for b in infra.TUG_BASES if b["name"] in places]
        antwerp = [b for b in bases if b["area"] == "antwerp_port"]
        total = sum(b["vessels"] for b in antwerp)
        share = [b["vessels"] / total * len(rows) for b in antwerp]
        counts = [int(v) for v in share]
        for i in sorted(range(len(antwerp)), key=lambda i: -(share[i] - counts[i]))[:len(rows) - sum(counts)]:
            counts[i] += 1
        self.tugs = []
        it = iter(rows)
        for b, n in zip(antwerp, counts):
            for _ in range(n):
                r = next(it)
                bp = r.get("Bollard pull (t)", "").split(" ")[0].replace(",", ".")
                self.tugs.append(Tug(r["Tug name"], r["Tug name"], float(bp) if bp.replace(".", "").isdigit() else None,
                                     b["name"], 0.0, 0.0))
        for b in bases:
            if b["area"] != "antwerp_port":
                self.tugs += [Tug(f"{b['name']}_{i + 1}", f"tug at {b['area']}", None, b["name"], 0.0, 0.0)
                              for i in range(b["vessels"])]
        self.base_xy = {}

    def bind(self, xy_of_node):
        for name, p in self.places.items():
            if p["kind"] == "tug_base":
                self.base_xy[name] = xy_of_node(p["node"])
        for t in self.tugs:
            t.x, t.y = self.base_xy[t.base]

    def request(self, n, x, y, ship_id, now):
        """The n nearest free tugs; returns (tugs, ready time) or (None, None)."""
        free = [t for t in self.tugs if t.ship is None and t.free_at <= now]
        if len(free) < n:
            return None, None
        free.sort(key=lambda t: math.hypot(t.x - x, t.y - y))
        chosen = free[:n]
        ready = now
        for t in chosen:
            t.ship = ship_id
            ready = max(ready, now + DETOUR * math.hypot(t.x - x, t.y - y) / (TUG_SPEED_KN * KNOT_M_MIN))
        return chosen, ready

    def release(self, tugs, x, y, now):
        """Done at (x, y): each tug sails back to its base."""
        for t in tugs:
            bx, by = self.base_xy[t.base]
            t.ship, t.free_at = None, now + DETOUR * math.hypot(bx - x, by - y) / (TUG_SPEED_KN * KNOT_M_MIN)
            t.x, t.y = bx, by

    def busy(self, now):
        return sum(1 for t in self.tugs if t.ship or t.free_at > now)
