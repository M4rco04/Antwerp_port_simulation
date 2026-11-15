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

import math
from dataclasses import dataclass, field
from pathlib import Path

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
    small_loa_m: float = 135.0        # ships up to this long (inland craft) enter and leave faster, one behind
    small_entry_min: float = 2.0      # the other: 4 and 3 min each made an inland craft take 1.3 to 1.6 h to
    small_exit_min: float = 1.5       # pass Hansweert, Kreekrak and Terneuzen, where the AIS has 0.7 to 0.9 h
    free_passage_min: float = 10.0    # one ship passing an open tidal gate
    gap_long_m: float = 10.0          # clearance between ships in a chamber, lengthwise
    gap_side_m: float = 2.0           # ... and side by side


# assumed: how long a lockage waits to fill up (lockages carried one ship or none in three of four cycles). Set so
# that the time per passage stays near the AIS (0.97 h): 20 and 15 min carried more ships but took 1.5 h
BUNDLE_HOLD_MIN = 3.0               # 10 min, with 4 + 3 min to enter and leave, made an inland craft take 1.3 h
EMPTY_HOLD_MIN = 3.0                # to pass Hansweert where the AIS has 0.7 h; 5 min 0.82 h (MODEL.md §19)
SMALL_SHIP_LOA_M, SMALL_SHIP_BEAM_M = 80.0, 9.0
# a lockage with a ship of this priority or higher in it, or called for one, is never held (LOCK_HOLD_P): sea-going
# ships (priority 3, under pilotage and with tugs ordered) and tide-dependent ones (2). With the holds on every
# lockage the sea-going ships' passage times spread a fifth wider than in the AIS
HOLD_FREE_PRIORITY = 3
CALLED_HOLD_MAX_MIN = 12.0          # a loaded chamber waits this long for a ship it has called in (assumed)
# An inland craft goes into a chamber alongside a sea-going ship that is going in or made fast there: it needs no
# time of the chamber's own (the ship's entry, 12 min, holds it). One behind the other, each craft added its 2 min
# to a lockage that the ship had already made long
ALONGSIDE_ENTRY_MIN = 0.5
# A lock does not work without a break: a lockage is held now and then, for a ship announced and not there yet, a
# shift change, a bridge over the lock head, a fault. No source gives how often or how long; without it the lock
# times had the AIS median and too little spread (90th percentile of the inland craft at Hansweert 0.93 h against
# 1.50 h, at Kreekrak 1.07 against 1.44 h). With probability LOCK_HOLD_P (per lock) a loaded or called chamber
# waits before its gates close, for a time drawn from an exponential distribution of mean LOCK_HOLD_MEAN_MIN. Not
# for a tide-dependent ship or one that has the chamber to itself. Calibrated on those 90th percentiles (MODEL.md
# §19), lock by lock: at Zandvliet-Berendrecht, Boudewijn-Van Cauwelaert and Terneuzen the queues of the model
# already give the AIS spread or more, and a hold there (tried: 0.10 at every lock) put the 90th percentiles 20 to
# 45 % over; the locks not named have none
LOCK_HOLD_P = {"Hansweert": 0.20, "Kreekrak": 0.06, "Kallo": 0.25, "Kieldrecht": 0.16, "Zandvliet": 0.10,
               "Berendrecht": 0.10, "Boudewijn": 0.05, "Van Cauwelaert": 0.05, "Terneuzen": 0.08}
LOCK_HOLD_MEAN_MIN = 35.0


def hold_probability(lock_name):
    return LOCK_HOLD_P.get(lock_name, 0.0) if isinstance(LOCK_HOLD_P, dict) else float(LOCK_HOLD_P)
# operating time of a lockage (closing the gates, levelling, opening them), min, where Rijkswaterstaat gives it
# ("bedieningstijd schutproces", Capaciteit Zeeuwse sluizen, 2001, table 3). Half of it is levelling and a quarter
# each gate movement. The other chambers keep LockTimes (gates + base + per metre of level difference).
OPERATING_MIN = {"Kreekrak west": 11.0, "Kreekrak east": 11.0, "Hansweert west": 15.0, "Hansweert east": 15.0,
                 "Terneuzen east lock": 20.5, "Terneuzen west lock": 26.5}


def _antwerp_operating_min(path=Path(__file__).resolve().parents[2] / "data" / "equipment" / "locks.csv"):
    """The Antwerp locks' operating times from data/equipment/locks.csv. The file's figure is called operation
    time and passage time by its source. As the time of one whole passage (the ship sails in, the gates close,
    the level is made, they open, it sails out) the operating time would be that less a ship's entry and exit
    as modelled here; as the operating time alone it would be the figure itself. The AIS decides between them
    as far as it can (validation, MODEL.md §19): a sea-going ship takes 1.75 h from 1 km before Zandvliet or
    Berendrecht to 1 km beyond, 1.4 h at Kieldrecht and 1.3 h at Boudewijn and Van Cauwelaert; the first
    reading gave 1.35, 1.0 and 1.3 h, the second would give a third of an hour more at each. The operating
    time is set half-way: the figure less half the entry and exit of the ships the lock takes (LockTimes:
    12 + 8 min sea-going; 2 + 1.5 min at Royers and Kattendijk, which take inland craft).
    At Boudewijn and Van Cauwelaert (PASSAGE_TIME_LOCKS) the AIS decides for the passage time: half-way
    (30 and 35 min) inland craft took 2.1 h to pass where the AIS has 1.1 h, sea-going ships 1.9 h against
    1.3 h, Van Cauwelaert working all day. There the figure less the whole entry and exit is the operating time."""
    t, out = LockTimes(), {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8-sig").splitlines()[1:]:
        cells = [c.strip() for c in line.split(";")]
        if len(cells) >= 2 and cells[0] and cells[1]:
            ship = t.small_entry_min + t.small_exit_min if cells[0] in BARGE_LOCKS else t.entry_min + t.exit_min
            share = 1.0 if cells[0] in PASSAGE_TIME_LOCKS else 0.5
            out[cells[0]] = max(float(cells[1]) - ship * share, 4.0)
    return out


BARGE_LOCKS = ("Royers", "Kattendijk")
# the locks whose figure in data/equipment/locks.csv the AIS reads as the time of a whole passage (calibrated,
# MODEL.md §19)
PASSAGE_TIME_LOCKS = ("Boudewijn", "Van Cauwelaert")
OPERATING_MIN.update(_antwerp_operating_min())
# Operating times set on the AIS passage times instead (calibrated, MODEL.md §19), where the published figure cannot
# be right for today's lock. Timed from 1 km before the lock to 1 km beyond, an inland craft passes Hansweert in
# 36 min (median of 1,121 passages), less than Kreekrak's 45 min, although the 2001 table gives Hansweert the longer
# operating time (15 against 11 min): with 15 min the model took 47 min. Van Cauwelaert, which carries four in five
# inland craft of its complex, took 77 min with the 25 min left of its figure, where the AIS has 60 min; with
# 15 min inland craft took 55 min and the sea-going ships 67 min against 81 min. (Hansweert was 9 min before its
# lockages were held now and then, LOCK_HOLD_P: the holds add 4 min to the median)
CALIBRATED_OPERATING_MIN = {"Hansweert west": 6.0, "Hansweert east": 6.0, "Van Cauwelaert": 20.0}
OPERATING_MIN.update(CALIBRATED_OPERATING_MIN)


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
    entered_at: float = 0.0
    ready_at: float = 0.0             # the minute from which it can be at the gate (the engine sets it: a ship waits
                                      # away from the lock until its chamber is called, then sails in; inf until then)

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
    held: bool = False                # this lockage has had its draw for a hold (LOCK_HOLD_P)

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
    rng: object = None                # for the holds (LOCK_HOLD_P); None: a lock that never holds

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

    def request(self, ship: ShipRequest, now: float, level_m: float | None = None) -> Chamber:
        """Queue a ship (turn number in order of request) at the chamber that suits it best:
        big enough (and deep enough at level_m, the higher side level, when given), fewest
        waiting on its side, preferably already at its level."""
        options = [c for c in self.chambers if c.fits_size(ship.loa, ship.beam)]
        if level_m is not None:
            deep = [c for c in options if ship.draught + self.ukc_m <= c.sill_depth_m + level_m]
            options = deep or sorted(options, key=lambda c: -c.sill_depth_m)[:1]
        if not options:
            raise ValueError(f"{ship.ship_id} ({ship.loa} x {ship.beam} m) fits no chamber of {self.name}")
        ship.turn, ship.requested_at = self.next_turn, now
        self.next_turn += 1
        best = min(options, key=lambda c: self._chamber_order(c, ship))
        best.queue[ship.from_side].append(ship)
        best.queue[ship.from_side].sort(key=lambda s: (s.priority, s.turn))
        if ship.exclusive:
            self.reserve(ship.ship_id, now, best.name)
        return best

    def _chamber_order(self, c, ship):
        """First a chamber open at the ship's side and not taking ships out the other way, that it packs into with
        those in it and waiting there (it can go in at once); then fill a chamber before starting another, as a
        lock master does: a chamber whose group on the ship's side (waiting, or in it and loading) it still packs
        into, the biggest group first; else the fewest waiting, preferably at its level. Taking the chamber with
        the fewest waiting spread the traffic over the chambers: Terneuzen's three carried 1.2 ships a lockage
        where Rijkswaterstaat counted about 1.8 of the classes modelled (IVS90, 2014 and 2018). Filling first
        without the first rule sent a barge to wait for a chamber across the canal while another stood open at its
        side: inland craft took 1.4 h to pass Terneuzen and 1.05 h Hansweert where the AIS has 0.9 and 0.7 h
        (validation, MODEL.md §19)."""
        side = ship.from_side
        group = list(c.queue[side])
        if c.side == side and c.state == "open":
            group += [p.ship for p in c.ships if p.ship.from_side == side]
        free = not ship.exclusive and not any(s.exclusive for s in group) and not (c.reserved_for and c.reserved_for != ship.ship_id)
        joins = bool(group) and free and pack(c.length_m, c.width_m, group + [ship], self.times.gap_long_m,
                                              self.times.gap_side_m) is not None
        ready = (free and c.side == side and c.state == "open" and not any(p.ship.from_side != side for p in c.ships)
                 and (joins or not group))
        return (not ready, not joins, -len(group) if joins else len(c.queue[side]) + (c.side != side), c.width_m)

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
                # nothing to do now: on to the moment within this step at which a ship sailing in gets to the gate
                at_gate = min((s.ready_at for s in c.queue[c.side] if t + 1e-9 < s.ready_at < end - 1e-9), default=None)
                if at_gate is None:
                    break
                t = at_gate
        return events

    def _gate_min(self, c):
        op = OPERATING_MIN.get(c.name)
        return op / 4 if op else self.times.gate_min

    def minutes_to_open(self, c, levels=None):
        """Minutes until a chamber that has closed lies open at its other side (0 for one that is open)."""
        if c.state == "open":
            return 0.0
        gate, op = self._gate_min(c), OPERATING_MIN.get(c.name)
        dh = abs(levels.get("a", 0.0) - levels.get("b", 0.0)) if levels else 0.0
        level = op / 2 if op else self.times.level_base_min + self.times.level_min_per_m * dh
        return c.timer_min + {"closing": level + gate, "levelling": gate}.get(c.state, 0.0)

    def _event(self, kind, t, c, ship=None, **extra):
        return {"t": t, "lock": self.name, "chamber": c.name, "event": kind,
                "ship": ship.ship_id if ship else None, **extra}

    def _start_next(self, c, t, levels, events):
        """Pick the chamber's next task; False if it has nothing to do."""
        here, there = c.side, other_side(c.side)
        if c.state == "open":
            leaving = [p for p in c.ships if p.ship.from_side != here]
            # inland craft leave before the sea-going ships they shared the chamber with (they are away in a
            # minute or two; behind the big ships, 8 min each, they took a third longer than the AIS to pass
            # Zandvliet-Berendrecht and Terneuzen, validation, MODEL.md §19)
            leaving.sort(key=lambda p: p.ship.loa > self.times.small_loa_m)
            if leaving:
                small = leaving[0].ship.loa <= self.times.small_loa_m
                c.task, c.timer_min = ("exit", leaving[0]), self.times.small_exit_min if small else self.times.exit_min
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
                small = ship.loa <= self.times.small_loa_m
                beside = small and any(p.ship.loa > self.times.small_loa_m and p.ship.from_side == here for p in c.ships)
                c.task, c.timer_min = ("enter", ship), (ALONGSIDE_ENTRY_MIN if beside else self.times.small_entry_min
                                                        if small else self.times.entry_min)
                return True
            if self._hold_open(c, t):
                return False
            if (c.ships or c.queue[there]) and not c.held:
                c.held = True
                rng = getattr(self, "rng", None)
                quick = any(p.ship.exclusive or p.ship.priority <= HOLD_FREE_PRIORITY for p in c.ships) or any(
                    s.exclusive or s.priority <= HOLD_FREE_PRIORITY for s in c.queue[there])
                p_hold = hold_probability(self.name)
                if rng is not None and p_hold > 0 and not quick and rng.random() < p_hold:
                    c.task, c.timer_min = ("hold", None), float(rng.exponential(LOCK_HOLD_MEAN_MIN))
                    events.append(self._event("held", t, c, minutes=round(c.timer_min, 1)))
                    return True
            if c.ships or c.queue[there]:
                c.state, c.task, c.timer_min = "closing", None, self._gate_min(c)
                events.append(self._event("closing", t, c, side=here, ships=len(c.ships)))
                return True
            return False
        return False

    def _hold_open(self, c, t):
        """Keep the gates open a while so that a lockage carries more than one ship: for ships still coming
        once one is in (up to BUNDLE_HOLD_MIN from when the first went in, while there is room for another),
        and before sailing empty for a ship on the far side (EMPTY_HOLD_MIN from its request). Not for a
        ship with a tide to keep or one that has the chamber to itself."""
        there = other_side(c.side)
        called = [s for s in c.queue[c.side] if t < s.ready_at < math.inf]
        if called:
            # a ship called to this side is sailing in: the chamber does not leave empty, and with ships in it
            # waits for it up to CALLED_HOLD_MAX_MIN from when the first went in (a ship called in and then
            # left at the gate waited a whole cycle there: an hour at Terneuzen). For a sea-going ship it waits
            # until the ship is in: the lockage is planned around it (its tugs and pilot are ordered for it).
            # With the 12 min for them too, a sea-going ship coming in for half an hour or more missed the chamber
            # it was called to in a fifth to a third of its passages of the Antwerp sea locks and lay an hour at
            # the gate: 90th percentile 2.96 h at Zandvliet-Berendrecht against 2.25 h (MODEL.md §19)
            if (not c.ships or any(s.priority <= HOLD_FREE_PRIORITY for s in called)
                    or t - min(p.ship.entered_at for p in c.ships) < CALLED_HOLD_MAX_MIN):
                return True
        if c.ships:
            first = min(p.ship.entered_at for p in c.ships)
            if any(p.ship.exclusive or p.ship.priority <= 2 for p in c.ships) or t - first >= BUNDLE_HOLD_MIN:
                return False
            smallest = ShipRequest("room", SMALL_SHIP_LOA_M, SMALL_SHIP_BEAM_M, 0.0, c.side)
            return pack(c.length_m, c.width_m, [p.ship for p in c.ships] + [smallest],
                        self.times.gap_long_m, self.times.gap_side_m) is not None
        if c.queue[there]:
            first = c.queue[there][0]
            return first.priority > 2 and not first.exclusive and t - first.requested_at < EMPTY_HOLD_MIN
        return False

    def _next_to_enter(self, c, t, levels, events):
        if any(p.ship.exclusive for p in c.ships):
            return None
        water = c.water_over_sill(levels)
        # in turn (VTS priority first); among the ships of one priority the sea-going ones first, the inland craft
        # then go in beside them (ALONGSIDE_ENTRY_MIN)
        for ship in sorted(c.queue[c.side], key=lambda s: (s.priority, s.loa <= self.times.small_loa_m, s.turn)):
            if ship.ready_at > t + 1e-9:
                continue                # not at the gate yet (waiting away from the lock, or sailing in)
            if c.reserved_for and t >= c.reserved_from and ship.ship_id != c.reserved_for:
                continue
            if ship.exclusive and c.ships:
                continue
            if ship.draught + self.ukc_m > water:
                events.append(self._event("too_deep", t, c, ship, water_over_sill=round(water, 2)))
                continue
            # the room of a ship of higher priority that has been called and is sailing in is kept for it: the
            # lock master does not let the barges at the gate fill the chamber a sea-going ship is coming for (it
            # then missed the lockage it was called to and waited a whole cycle at the gate: Terneuzen's
            # sea-going passages 1.68 h at the 90th percentile against 1.33 h, MODEL.md §19)
            coming = [s for s in c.queue[c.side] if s is not ship and s.priority < ship.priority and t < s.ready_at < math.inf]
            if pack(c.length_m, c.width_m, [p.ship for p in c.ships] + coming + [ship],
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
                item.entered_at = t
                c.ships = pack(c.length_m, c.width_m, [p.ship for p in c.ships] + [item],
                               self.times.gap_long_m, self.times.gap_side_m)
                return [self._event("enter", t, c, item, side=c.side)]
            if kind == "pass":
                return [self._event("passed", t, c, item, side=other_side(item.from_side))]
            if kind == "hold":
                return []
        if c.state == "closing":
            dh = abs(levels.get("a", 0.0) - levels.get("b", 0.0))
            op = OPERATING_MIN.get(c.name)
            c.state, c.timer_min = "levelling", (op / 2 if op else self.times.level_base_min + self.times.level_min_per_m * dh)
            return [self._event("levelling", t, c, level_difference_m=round(dh, 2))]
        if c.state == "levelling":
            c.state, c.timer_min = "opening", self._gate_min(c)
            return []
        if c.state == "opening":
            c.state, c.side, c.held = "open", other_side(c.side), False
            return [self._event("open", t, c, side=c.side, ships=len(c.ships))]
        return []

    def summary(self):
        return {c.name: {"state": c.state, "side": c.side, "inside": [p.ship.ship_id for p in c.ships],
                         "waiting_a": [s.ship_id for s in c.queue["a"]],
                         "waiting_b": [s.ship_id for s in c.queue["b"]], "timer_min": round(c.timer_min, 1)}
                for c in self.chambers}


def in_next_lockage(lock, c, ship):
    """Will this waiting ship be in the chamber's next lockage from its side: does it pack into the chamber with the
    ships of its side already in it and those before it in the queue (a ship with the chamber to itself: alone)?"""
    side = ship.from_side
    inside = [p.ship for p in c.ships if p.ship.from_side == side] if c.side == side and c.state == "open" else []
    order = lambda s: (s.priority, s.loa <= lock.times.small_loa_m, s.turn)
    before = [s for s in c.queue[side] if s is not ship and order(s) < order(ship)]
    if ship.exclusive or any(s.exclusive for s in inside + before):
        return not inside and not before
    if c.reserved_for and c.reserved_for != ship.ship_id:
        return False
    return pack(c.length_m, c.width_m, inside + before + [ship], lock.times.gap_long_m, lock.times.gap_side_m) is not None


def expected_wait(lock, c, side):
    """Roughly the minutes until this chamber can take a ship waiting at this side: none when it lies open there,
    the rest of its way when it is coming, a whole crossing more when it lies open at the other side or has just
    left. For choosing between locks side by side (engine: a ship takes the one that is ready first)."""
    op = OPERATING_MIN.get(c.name) or (2 * lock.times.gate_min + lock.times.level_base_min)
    busy = 2.0 * len(c.queue[side]) + sum(lock.times.exit_min if p.ship.loa > lock.times.small_loa_m else lock.times.small_exit_min
                                           for p in c.ships if p.ship.from_side != side)
    if c.side == side:
        return busy if c.state == "open" else lock.minutes_to_open(c) + op + busy
    return (op if c.state == "open" else lock.minutes_to_open(c)) + busy


def lock_preference(locks, loa, beam, draught=0.0, level_m=0.0):
    """Order alternative locks for a ship: the ones it fits, wide ships (B >= 43 m) to the
    locks marked for them first (Berendrecht, PLAN.md §7), then by how many ships wait."""
    fitting = [lock for lock in locks if lock.fits(loa, beam, draught, level_m)]
    return sorted(fitting, key=lambda lock: (
        not (beam >= WIDE_BEAM_M and lock.preferred_min_beam_m and beam >= lock.preferred_min_beam_m),
        sum(c.waiting() for c in lock.chambers)))
