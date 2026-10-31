"""Anchorages of the Scheldt simulation (PLAN.md §4, regs §11): the data and the process of one anchorage.

Every anchorage is a single node of the navigation graph (type "anchorage") whose "anchorage"
attribute is an Anchorage object:

    kind          "area" (ships fit by swing circle) or "anchor berth" (one ship, official radius)
    cells         the graph cells inside it a ship can lie at: (node, x, y, depth below LAT)
    ships         the ships at anchor, with their cell, swing radius, arrival and pilot request
    has_room()    is there a free spot for this ship (depth, swing circle, packing)?
    arrive()      anchor a ship at the free cell farthest from the ships already there
    request_pilot()  the ship asks for a pilot: it enters the departure queue
    next_departure()   the ship to leave first: priority class, then pilot request time
    step()        events: ships over the maximum stay (24 h in the Western Scheldt)

Departure priority (PLAN.md §4): 1 distress, 2 tide- or current-dependent, 3 ordered ahead by
the authority, 4 first come first served; within a class by pilot request time.

choose_anchorage() orders the anchorages a ship may use by the rules of regs §11.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

DISTRESS, TIDE_DEPENDENT, ORDERED_AHEAD, FCFS = 1, 2, 3, 4
CHAIN_PER_DEPTH = 5.0           # anchor chain paid out ~5 x the water depth
PACKING = 0.55                  # share of an anchorage area swing circles may cover (the first ship always fits)
UKC_AT_ANCHOR_M = 1.0


@dataclass
class AnchoredShip:
    ship_id: str
    loa: float
    draught: float
    priority: int
    arrived: float              # minutes
    cell: int                   # graph node it lies at
    x: float
    y: float
    radius_m: float
    pilot_requested: float | None = None
    over_stay_reported: bool = False


@dataclass
class Anchorage:
    name: str
    kind: str                                   # "area" or "anchor berth"
    area_m2: float
    cells: list = field(default_factory=list)   # (node, x, y, depth_m)
    berth_radius_m: float | None = None         # anchor berths: the official swing radius
    max_stay_h: float | None = 24.0
    sea_anchorage: bool = False
    approximate: bool = False                   # outline approximate (GB 01-2019 buoys, single point, ...)
    off_graph: bool = False                     # outside the AIS area, joined by a virtual edge
    ships: list = field(default_factory=list)

    @property
    def depth_m(self):
        """Median depth below LAT of its cells."""
        d = sorted(c[3] for c in self.cells)
        return d[len(d) // 2] if d else 0.0

    def swing_radius(self, loa, depth=None):
        return loa + CHAIN_PER_DEPTH * max(depth if depth is not None else self.depth_m, 5.0)

    def _free_cells(self, ship_loa, draught, level_m):
        radius = self.swing_radius(ship_loa)
        out = []
        for node, x, y, depth in self.cells:
            if depth + level_m < draught + UKC_AT_ANCHOR_M:
                continue
            gap = min((math.hypot(x - s.x, y - s.y) - s.radius_m - radius for s in self.ships), default=math.inf)
            if gap >= 0:
                out.append((gap, node, x, y))
        return out

    def has_room(self, loa, draught, level_m=0.0):
        """A free spot for a ship this long and deep (level_m: tide above LAT now)."""
        if self.kind == "anchor berth":
            return not self.ships and self.swing_radius(loa) <= (self.berth_radius_m or 0) \
                and any(d + level_m >= draught + UKC_AT_ANCHOR_M for *_, d in self.cells)
        used = sum(math.pi * s.radius_m ** 2 for s in self.ships)
        if self.ships and used + math.pi * self.swing_radius(loa) ** 2 > PACKING * self.area_m2:
            return False
        return bool(self._free_cells(loa, draught, level_m))

    def arrive(self, ship_id, loa, draught, now, priority=FCFS, level_m=0.0):
        """Anchor a ship; returns its AnchoredShip, or None (and the caller logs it) if full."""
        if not self.has_room(loa, draught, level_m):
            return None
        free = self._free_cells(loa, draught, level_m) if self.kind == "area" else \
            [(0.0, n, x, y) for n, x, y, d in self.cells if d + level_m >= draught + UKC_AT_ANCHOR_M]
        _, node, x, y = max(free)                       # as far as possible from the others
        ship = AnchoredShip(ship_id, loa, draught, priority, now, node, x, y, self.swing_radius(loa))
        self.ships.append(ship)
        return ship

    def request_pilot(self, ship_id, now, priority=None):
        ship = self.ship(ship_id)
        ship.pilot_requested = now
        if priority is not None:
            ship.priority = priority

    def ship(self, ship_id):
        return next(s for s in self.ships if s.ship_id == ship_id)

    def departure_queue(self):
        """Ships with a pilot ordered, in departure order."""
        return sorted((s for s in self.ships if s.pilot_requested is not None),
                      key=lambda s: (s.priority, s.pilot_requested, s.arrived))

    def next_departure(self):
        q = self.departure_queue()
        return q[0] if q else None

    def leave(self, ship_id, now):
        ship = self.ship(ship_id)
        self.ships.remove(ship)
        return {"t": now, "anchorage": self.name, "event": "left", "ship": ship_id,
                "hours": round((now - ship.arrived) / 60, 2)}

    def step(self, now):
        """Events for this step: ships over the maximum stay (once per ship)."""
        events = []
        if self.max_stay_h is None:
            return events
        for s in self.ships:
            if not s.over_stay_reported and now - s.arrived > self.max_stay_h * 60:
                s.over_stay_reported = True
                events.append({"t": now, "anchorage": self.name, "event": "max_stay_exceeded", "ship": s.ship_id,
                               "hours": round((now - s.arrived) / 60, 2)})
        return events

    def summary(self):
        return {"ships": len(self.ships), "waiting_for_pilot": len(self.departure_queue()),
                "area_used": round(sum(math.pi * s.radius_m ** 2 for s in self.ships) / max(self.area_m2, 1), 3)}


def choose_anchorage(anchorages, loa, draught, dangerous_signals=False, srw_annex1=False, dangerous=False,
                     difficulty=False, tide_dependent=False, lng_zeebrugge_no_pilot=False, level_m=0.0):
    """Anchorages a ship may use, in order of preference (regs §11.3), keeping those with room.
    anchorages: {name: Anchorage}."""
    if dangerous_signals:
        names = ["Wielingen Noord"]
    elif srw_annex1:
        names = ["Schouwenbank", "Westhinder", "Wielingen Noord"]
    elif dangerous and loa <= 110 and difficulty:
        names = ["Rede Vlissingen (oostelijk deel)"]
    elif tide_dependent and draught >= 14.0:
        names = ["Wielingen Zuid"]
    elif lng_zeebrugge_no_pilot:
        names = ["Westhinder"]
    else:
        names = ["Rede Vlissingen", "Rede Vlissingen (oostelijk deel)", "Westhinder", "Oostdyck",
                 "Everingen A", "Everingen B", "Everingen C", "Everingen D", "Everingen E",
                 "Put van Terneuzen A", "Put van Terneuzen B", "Springergeul", "Zuid Everingen", "Marlemon",
                 "Schaar van Ouden Doel"]
    return [anchorages[n] for n in names if n in anchorages and anchorages[n].has_room(loa, draught, level_m)]
