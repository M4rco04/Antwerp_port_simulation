"""Locks of the Scheldt simulation (PLAN.md §7): the data and the process of one lock.

Every lock is a single node of the navigation graph (type "lock"). Its "lock" attribute is a
Lock object holding everything the plan needs:

    chambers      length x width, sill depth, and per chamber: its state, the side whose
                  water level it is at, the ships inside (with their packed positions) and a
                  queue of waiting ships for each side
    sides         the two sides the lock joins ("a", "b"): their zone, whether they are tidal,
                  and the graph nodes on that side (the ends of the lock's gate edges)
    request()     queue a ship at the chamber that suits it best (it gets a turn number)
    reserve()     keep a chamber empty for one ship from a given time (ULCV, regs §8.9)
    step()        advance every chamber by one simulation step and report what happened

Type B (level-changing) chamber cycle, as countdown timers in minutes (PLAN.md §0):

    open at side S: the ships for S leave one by one, then ships waiting at S enter one by
    one while they still pack into the chamber -> closing -> levelling (time grows with the
    level difference) -> opening -> open at the other side

Packing is 2-D (LOA x beam), greedy first fit with the biggest ship at the front; ships are
taken in turn order (VTS priority first), and a later, smaller ship may fill a gap. A
container ship of 350 m or more gets an empty chamber. A type A lock ("tidal gate") lets
ships straight through while the levels on both sides differ by less than tidal_gate_eps_m,
and works as type B otherwise. The durations in LockTimes are first guesses to calibrate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ULCV_LOA_M = 350.0          # container ships this long get an empty chamber (regs §8.9)
WIDE_BEAM_M = 43.0          # ships this wide prefer the lock(s) marked for them (Berendrecht)
SIDES = ("a", "b")


def other_side(side):
    return "b" if side == "a" else "a"


@dataclass
class LockTimes:
    gate_min: float = 5.0             # closing or opening the gates
    level_base_min: float = 5.0       # levelling takes this long ...
    level_min_per_m: float = 3.0      # ... plus this per metre of level difference
    entry_min: float = 12.0           # one ship entering and making fast
    exit_min: float = 8.0             # one ship leaving
    free_passage_min: float = 10.0    # one ship passing an open tidal gate
    gap_long_m: float = 10.0          # clearance between ships in a chamber, lengthwise
    gap_side_m: float = 2.0           # ... and side by side


@dataclass
class ShipRequest:
    ship_id: str
    loa: float
    beam: float
    draught: float
    from_side: str
    priority: int = 4                 # VTS priority class, 1 = highest (regs §11)
    container: bool = False
    turn: int = 0                     # queue number, given by Lock.request
    requested_at: float = 0.0

    @property
    def exclusive(self):
        return self.container and self.loa >= ULCV_LOA_M


@dataclass
class Placement:
    ship: ShipRequest
    x: float                          # from the front gate (direction of travel), m
    y: float                          # from the chamber wall, m


def pack(length, width, ships, gap_long=10.0, gap_side=2.0):
    """Greedy first-fit 2-D packing, biggest ship at the front. Placements, or None if the ships
    do not all fit."""
    placed, corners = [], [(0.0, 0.0)]
    for ship in sorted(ships, key=lambda s: (-s.loa, -s.beam, s.turn)):
        for x, y in sorted(corners):
            x1, y1 = x + ship.loa, y + ship.beam
            if x1 > length or y1 > width:
                continue
            if any(x < p.x + p.ship.loa + gap_long and p.x < x1 + gap_long
                   and y < p.y + p.ship.beam + gap_side and p.y < y1 + gap_side for p in placed):
                continue
            placed.append(Placement(ship, x, y))
            corners += [(x1 + gap_long, y), (x, y1 + gap_side)]
            break
        else:
            return None
    return placed


@dataclass
class Chamber:
    name: str
    length_m: float
    width_m: float
    sill_depth_m: float               # sill below the datum, m
    sill_datum: str = "TAW"
    source: str = "regs"              # where the dimensions come from
    side: str = "a"                   # the side whose level the chamber is at
    state: str = "open"               # open / closing / levelling / opening
    timer_min: float = 0.0
    task: tuple | None = None         # what finishes when the timer runs out
    ships: list = field(default_factory=list)        # Placements inside
    queue: dict = field(default_factory=lambda: {"a": [], "b": []})
    reserved_for: str | None = None
    reserved_from: float = 0.0

    def fits_size(self, loa, beam):
        return loa <= self.length_m and beam <= self.width_m

    def water_over_sill(self, levels):
        """Least water over the sill during a passage: the lower of the two levels (m above datum)."""
        return self.sill_depth_m + min(levels.get("a", 0.0), levels.get("b", 0.0))

    def waiting(self):
        return len(self.queue["a"]) + len(self.queue["b"])


@dataclass
class Lock:
    name: str
    chambers: list
    sides: dict = field(default_factory=dict)     # "a"/"b" -> {"zone", "tidal", "nodes"}
    lock_type: str = "B"                          # "B" level-changing, "A" tidal gate
    tidal_gate_eps_m: float = 0.10
    preferred_min_beam_m: float | None = None     # ships at least this wide prefer this lock
    ukc_m: float = 0.5
    times: LockTimes = field(default_factory=LockTimes)
    next_turn: int = 1

    # -- static checks (routing) ----------------------------------------------------------

    @property
    def max_sill_depth_m(self):
        return max(c.sill_depth_m for c in self.chambers)

    def chamber(self, name):
        return next(c for c in self.chambers if c.name == name)

    def fits(self, loa=0.0, beam=0.0, draught=0.0, level_m=0.0):
        """Can a ship of this size pass any chamber at this water level (m above datum)?"""
        return any(c.fits_size(loa, beam) and draught + self.ukc_m <= c.sill_depth_m + level_m
                   for c in self.chambers)

    def side_of(self, node):
        return next((s for s, d in self.sides.items() if node in d["nodes"]), None)

    # -- requests ---------------------------------------------------------------------------

    def request(self, ship: ShipRequest, now: float) -> Chamber:
        """Queue a ship (turn number in order of request) at the chamber that suits it best:
        big enough, fewest waiting on its side, preferably already at its level."""
        options = [c for c in self.chambers if c.fits_size(ship.loa, ship.beam)]
        if not options:
            raise ValueError(f"{ship.ship_id} ({ship.loa} x {ship.beam} m) fits no chamber of {self.name}")
        ship.turn, ship.requested_at = self.next_turn, now
        self.next_turn += 1
        best = min(options, key=lambda c: (len(c.queue[ship.from_side]) + (c.side != ship.from_side),
                                           c.width_m))
        best.queue[ship.from_side].append(ship)
        best.queue[ship.from_side].sort(key=lambda s: (s.priority, s.turn))
        if ship.exclusive:
            self.reserve(ship.ship_id, now, best.name)
        return best

    def reserve(self, ship_id, from_min, chamber_name=None):
        """Keep a chamber for one ship only, from a given time (ULCV, regs §8.9)."""
        chamber = self.chamber(chamber_name) if chamber_name else max(self.chambers, key=lambda c: c.length_m)
        chamber.reserved_for, chamber.reserved_from = ship_id, from_min
        return chamber

    # -- process ----------------------------------------------------------------------------

    def step(self, now: float, dt: float, levels: dict) -> list:
        """Advance all chambers from now to now + dt (minutes). levels: water level above the
        datum on each side, {"a": m, "b": m}. Returns events as dicts."""
        events = []
        for chamber in self.chambers:
            events += self._advance(chamber, now, dt, levels)
        return events

    def _advance(self, c, now, dt, levels):
        events, t, end = [], now, now + dt
        while t < end - 1e-9:
            if c.timer_min > 1e-9:
                use = min(end - t, c.timer_min)
                c.timer_min -= use
                t += use
                if c.timer_min > 1e-9:
                    break
                events += self._finish(c, t, levels)
                continue
            if not self._start_next(c, t, levels, events):
                break
        return events

    def _event(self, kind, t, c, ship=None, **extra):
        return {"t": t, "lock": self.name, "chamber": c.name, "event": kind,
                "ship": ship.ship_id if ship else None, **extra}

    def _start_next(self, c, t, levels, events):
        """Pick the chamber's next task; False if it has nothing to do."""
        here, there = c.side, other_side(c.side)
        if c.state == "open":
            leaving = [p for p in c.ships if p.ship.from_side != here]
            if leaving:
                c.task, c.timer_min = ("exit", leaving[0]), self.times.exit_min
                return True
            if self.lock_type == "A" and abs(levels.get("a", 0.0) - levels.get("b", 0.0)) < self.tidal_gate_eps_m:
                for side in (here, there):
                    if c.queue[side]:
                        ship = c.queue[side].pop(0)
                        c.task, c.timer_min = ("pass", ship), self.times.free_passage_min
                        return True
            ship = self._next_to_enter(c, t, levels, events)
            if ship is not None:
                c.queue[here].remove(ship)
                c.task, c.timer_min = ("enter", ship), self.times.entry_min
                return True
            if c.ships or c.queue[there]:
                c.state, c.task, c.timer_min = "closing", None, self.times.gate_min
                events.append(self._event("closing", t, c, side=here, ships=len(c.ships)))
                return True
            return False
        return False

    def _next_to_enter(self, c, t, levels, events):
        if any(p.ship.exclusive for p in c.ships):
            return None
        water = c.water_over_sill(levels)
        for ship in c.queue[c.side]:
            if c.reserved_for and t >= c.reserved_from and ship.ship_id != c.reserved_for:
                continue
            if ship.exclusive and c.ships:
                continue
            if ship.draught + self.ukc_m > water:
                events.append(self._event("too_deep", t, c, ship, water_over_sill=round(water, 2)))
                continue
            if pack(c.length_m, c.width_m, [p.ship for p in c.ships] + [ship],
                    self.times.gap_long_m, self.times.gap_side_m) is not None:
                return ship
        return None

    def _finish(self, c, t, levels):
        task, c.task = c.task, None
        if c.state == "open" and task:
            kind, item = task
            if kind == "exit":
                c.ships.remove(item)
                if c.reserved_for == item.ship.ship_id:
                    c.reserved_for = None
                return [self._event("exit", t, c, item.ship, side=c.side)]
            if kind == "enter":
                c.ships = pack(c.length_m, c.width_m, [p.ship for p in c.ships] + [item],
                               self.times.gap_long_m, self.times.gap_side_m)
                return [self._event("enter", t, c, item, side=c.side)]
            if kind == "pass":
                return [self._event("passed", t, c, item, side=other_side(item.from_side))]
        if c.state == "closing":
            dh = abs(levels.get("a", 0.0) - levels.get("b", 0.0))
            c.state, c.timer_min = "levelling", self.times.level_base_min + self.times.level_min_per_m * dh
            return [self._event("levelling", t, c, level_difference_m=round(dh, 2))]
        if c.state == "levelling":
            c.state, c.timer_min = "opening", self.times.gate_min
            return []
        if c.state == "opening":
            c.state, c.side = "open", other_side(c.side)
            return [self._event("open", t, c, side=c.side, ships=len(c.ships))]
        return []

    def summary(self):
        return {c.name: {"state": c.state, "side": c.side, "inside": [p.ship.ship_id for p in c.ships],
                         "waiting_a": [s.ship_id for s in c.queue["a"]],
                         "waiting_b": [s.ship_id for s in c.queue["b"]], "timer_min": round(c.timer_min, 1)}
                for c in self.chambers}


def lock_preference(locks, loa, beam, draught=0.0, level_m=0.0):
    """Order alternative locks for a ship: the ones it fits, wide ships (B >= 43 m) to the
    locks marked for them first (Berendrecht, PLAN.md §7), then by how many ships wait."""
    fitting = [lock for lock in locks if lock.fits(loa, beam, draught, level_m)]
    return sorted(fitting, key=lambda lock: (
        not (beam >= WIDE_BEAM_M and lock.preferred_min_beam_m and beam >= lock.preferred_min_beam_m),
        sum(c.waiting() for c in lock.chambers)))
