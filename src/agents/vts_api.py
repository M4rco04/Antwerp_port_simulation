"""The VTS strategy API: what a traffic-management strategy sees, decides and orders (docs/VTS_API.md).

A strategy is a subclass of Strategy. The engine owns the physics and the rules; the strategy owns the decisions
a VTS (with the lock planners, the pilot and tug dispatchers and the harbour master behind it) could make. It works
through three things it is given when the run starts (Strategy.bind):

    view      read-only queries about the port now (View, ShipView): who is waiting, what is free, the tide
    control   orders to the engine (Control): clear a ship, send it to anchor, set its speed, restrict a stretch.
              Every order is checked first; one that is not allowed is refused, returns Result(ok=False, reason)
              and is logged as a "vts_rejected" event (summary.json, "vts")
    hooks     methods of Strategy the engine calls when it has a choice to make (a berth, a chamber, which tugs).
              Each is offered the options and the engine's default; returning None keeps the default, returning an
              option that is not on offer is refused (the default is used and the refusal logged)

Every ship in the area is under the VTS: a ship asks (Strategy.on_request) before every voyage, from the pilot
station, an anchorage, a berth or a port, and sails only when the strategy has cleared it (Control.clear). Ships
that need a pilot are checked for route, weather, tide, pilots and destination; ships without one (inland craft,
small ships) for route and destination, as their masters sail on their own judgement of tide and weather.

What a strategy cannot change: the tide, the weather, the depths and under-keel clearance, the weather gates,
lockage times, handling times, collision avoidance and the encounter rules on the mesh. A strategy decides; the
engine refuses anything that breaks those, so no strategy can make the model unsafe or physically impossible.

Write a strategy as a module in src/strategies/ (strategies/template.py lists every hook) and run it with
Simulation(vts="<name>") or pipeline.py --vts <name>.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# the levers a strategy may declare (Strategy.levers): recorded in the run's summary, so results can be grouped by
# what a strategy was allowed to decide (the authority tiers of docs/VTS_API.md)
LEVERS = ("clearance", "arrival_time", "berth", "quay_position", "anchorage", "exit", "lock_route", "pilots",
          "tugs", "lock_chamber", "lock_priority", "lockage", "speed", "rank", "restriction")
MIN_SPEED_KN = 3.0                  # the slowest speed through the water the VTS may order (steerage way, assumed)
ARRIVAL_DELAY_MAX_MIN = 48 * 60.0   # the longest a ship may be held at sea before it enters the area
RESTRICTION_MAX_MIN = 24 * 60.0     # a restriction ends at most this long after it is made (it can be renewed)
KEEP_OPEN_MAX_MIN = 30.0            # a chamber kept open against the lock's own rule for longer than this closes
RESTRICTION_KINDS = ("closed", "one_way", "no_meet")
LOCK_PRIORITIES = (1, 2, 3, 4)      # 1 ordered ahead, 2 tide-dependent, 3 sea-going, 4 inland (locks.py)
UP, DOWN = 1, -1                    # directions on the river: inland / up-river, and towards the sea


@dataclass(frozen=True)
class Result:
    """What an order or a check came to. ok: done (or would pass); reason: why not ("no_route", "destination",
    "weather", "tide", "pilot", "infeasible", "pilot_lost" (cleared, but a pilot booked for it went to another ship
    this round: the ship is back in the queue, in its place), or a refusal: "not_waiting", "not_ready",
    "out_of_range", ...); route: the voyage's node ids when one was found;
    retry_at: for a ship without a pilot, when the engine would try it again by itself (the baseline's back-off);
    removed: the ship was taken out of the model (its voyage cannot be made at any tide); value: anything else."""
    ok: bool
    reason: str | None = None
    route: tuple | None = None
    retry_at: float | None = None
    removed: bool = False
    value: object = None

    def __bool__(self):
        return self.ok


@dataclass
class Restriction:
    """A VTS restriction on a stretch of water (Control.restrict): ships it applies to (who) may not enter its
    cells while it is in force, closed: at all; one_way: against `direction` (UP or DOWN); no_meet: while a ship
    it applies to is inside coming the other way. A ship already inside carries on."""
    id: int
    kind: str
    cells: frozenset
    start: float
    until: float
    direction: int = 0
    who: dict = field(default_factory=dict)
    name: str = ""

    def active(self, now):
        return self.start <= now < self.until

    def applies(self, ship):
        """Does it apply to this ship (a Ship or a ShipView)? who: min_loa, min_beam, min_draught (m), classes
        (list of ship classes), sea_going (bool), needs_pilot (bool); empty: every ship."""
        w = self.who
        if w.get("min_loa") is not None and ship.loa < w["min_loa"]:
            return False
        if w.get("min_beam") is not None and ship.beam < w["min_beam"]:
            return False
        if w.get("min_draught") is not None and ship.draught < w["min_draught"]:
            return False
        if w.get("classes") and ship.cls not in w["classes"]:
            return False
        if w.get("sea_going") is not None and bool(ship.sea_going) != bool(w["sea_going"]):
            return False
        if w.get("needs_pilot") is not None and bool(ship.needs_pilot) != bool(w["needs_pilot"]):
            return False
        return True


class ShipView:
    """A ship as the VTS sees it: what it is, where it is, what it asked for. Not its hidden speed spread
    (engine.SPEED_SPREAD), its future or its random draws; max_speed_kn is its own service speed, as a ship
    reports it."""
    __slots__ = ("_s", "_sim")

    def __init__(self, ship, sim):
        self._s, self._sim = ship, sim

    def __eq__(self, other):
        return isinstance(other, ShipView) and other._s is self._s

    def __hash__(self):
        return hash(self._s.id)

    def __repr__(self):
        return f"ShipView({self._s.id}, {self._s.cls}, {self._s.state.value})"

    # what it is
    id = property(lambda self: self._s.id)
    name = property(lambda self: self._s.name)
    cls = property(lambda self: self._s.cls)
    level = property(lambda self: self._s.level)          # 1 container ship of the schedule, 2 other traffic
    loa = property(lambda self: self._s.loa)
    beam = property(lambda self: self._s.beam)
    draught = property(lambda self: self._s.draught)
    teu = property(lambda self: self._s.teu)
    dg = property(lambda self: self._s.dg)                # dangerous-goods category (AIS A-D) or None
    sea_going = property(lambda self: self._s.sea_going)
    needs_pilot = property(lambda self: self._s.needs_pilot)
    tide_dependent = property(lambda self: self._s.tide_dependent)
    ulcv = property(lambda self: self._s.ulcv)
    distress = property(lambda self: self._s.distress)

    # where it is and where it goes
    state = property(lambda self: self._s.state.value)
    departing = property(lambda self: self._s.departing)
    terminal = property(lambda self: self._s.terminal)
    destination = property(lambda self: self._s.destination)
    exit = property(lambda self: self._s.exit)
    anchorage = property(lambda self: self._s.anchorage)
    lock = property(lambda self: self._s.lock)
    at = property(lambda self: self._s.at)                # node it lies at while off the mesh, else None
    target = property(lambda self: self._s.target)        # node its voyage ends at, once planned

    @property
    def node(self):
        """The node it is at: where it lies, or its bow's cell under way."""
        s = self._s
        return s.cells[-1] if s.cells else s.at

    @property
    def position(self):
        """(x, y) in the graph's metric projection (UTM 31N), or None."""
        n = self.node
        return None if n is None else (float(self._sim.fg.x[n]), float(self._sim.fg.y[n]))

    @property
    def berth(self):
        """The berth it holds or has booked: {"kind": "terminal"/"berth"/"place"/"exit", "id", "node", "zone",
        "terminal"}, or None."""
        b = self._s.berth
        if not b:
            return None
        return {"kind": b.get("kind"), "id": b.get("id") or b.get("name"), "node": b.get("node"),
                "zone": b.get("zone"), "terminal": self._s.terminal if b.get("kind") == "terminal" else None}

    @property
    def remaining_m(self):
        """Metres left of the route part it sails now (to the next lock or the end)."""
        return self._s.remaining_m

    # its request to the VTS
    waiting = property(lambda self: bool(getattr(self._s, "vts_req", False)))     # in the VTS queue now
    request_t = property(lambda self: self._s.request_t)                           # when it asked (this voyage)
    request_kind = property(lambda self: getattr(self._s, "vts_kind", None))       # go / unmoor / hop / resume
    wait_reason = property(lambda self: self._s.times.get("vts_wait_reason"))      # the last check it failed
    at_station = property(lambda self: bool(getattr(self._s, "at_station", False)))  # an arrival off the station

    @property
    def ready(self):
        """Can it be cleared now: not under way to its anchorage, not still lying out an anchor stay it entered
        the area with."""
        s = self._s
        return not (s.state.value == "to_anchorage" and s.at is None) and getattr(s, "anchor_until", 0.0) <= self._sim.t

    @property
    def waited_min(self):
        """Minutes since it asked for this voyage (0 when it is not waiting)."""
        return self._sim.t - self._s.request_t if self.waiting and self._s.request_t is not None else 0.0

    @property
    def scheduled_berth_min(self):
        """A container ship's berth time (the schedule and its delay, minutes from the start), else None."""
        return (self._s.schedule or {}).get("berth_min")

    # speed
    def max_speed_kn(self, leg="river"):
        """Its own speed through the water on a leg ("sea" or "river"): the most the VTS can ask of it."""
        import navigation_rules as NR
        return float(self._s.stw_kn(leg, NR.planning_speed_kn))

    def planning_speed_kn(self, leg="river"):
        """The planning speed of its class and draught on a leg (JA22), without its own spread."""
        import navigation_rules as NR
        s = self._s
        v = NR.planning_speed_kn(s.cls, s.draught, "departure" if s.departing else "arrival", leg)
        if not v:
            from ship import CLASS_SPEED_KN
            v = CLASS_SPEED_KN.get(s.cls, 12.0)
        return float(v)

    ordered_speed_kn = property(lambda self: getattr(self._s, "vts_speed_kn", None))
    rank = property(lambda self: self._s.clear_order)      # right of way under way: lower goes first

    # what it needs
    def tugs_needed(self, departing=None):
        return self._s.tugs_needed(self._s.departing if departing is None else departing)

    def pilots_needed(self, zone):
        return self._s.pilots_needed(zone)


class View:
    """Read-only queries for a strategy. Nothing here changes the model."""

    def __init__(self, sim, vts):
        self._sim, self._vts = sim, vts

    def _v(self, ship):
        return ShipView(ship, self._sim)

    # time
    @property
    def now(self):
        return self._sim.t

    step_min = property(lambda self: self._sim.dt_min)
    round_min = property(lambda self: self._sim.dt_min * self._vts.plan_every)      # minutes between on_tick calls
    container_sea_wait_max_min = property(lambda self: self._sim.container_sea_wait_max_min)

    @property
    def rng(self):
        """The strategy's own random stream (from the seed): draws here move no other part of the model."""
        return self._sim.streams["vts"]

    # ships
    def requests(self):
        """The ships waiting for clearance, in the order they asked."""
        return [self._v(s) for s in self._vts.requests]

    def ships(self):
        """Every ship in the area."""
        return [self._v(s) for s in self._sim.ships]

    def ship(self, ship_id):
        s = self._sim.by_id.get(ship_id)
        return self._v(s) if s is not None and s in self._sim.ships else None

    def at_sea(self):
        """Ships held at sea before they enter (arrival_delay): [(ShipView, minute it is to enter)]."""
        return [(self._v(s), s.spawn_t) for s in self._sim.at_sea]

    @staticmethod
    def default_priority(ship):
        """The baseline's order of clearance: distress, then tide-dependent ships, then first come first served."""
        return (0 if ship.distress else 1 if ship.tide_dependent else 3, ship.request_t or 0.0)

    # resources
    def pilots_free(self, zone):
        """Pilots of a zone ("sea", "river", "dock") free now (not on board, back from their last job)."""
        sim = self._sim
        return sum(1 for p in sim.pilots.pilots if p.zone == zone and p.ship is None and p.free_at <= sim.t)

    def pilots_total(self, zone):
        return self._sim.pilots.sizes.get(zone, 0)

    def pilot_boats_free(self):
        return self._sim.pilot_boats.available(self._sim.t)

    def tugs(self):
        """Every tug: {"id", "base", "x", "y", "free"} (x, y: where it is, or its base when it is on its way back)."""
        now = self._sim.t
        return [{"id": t.id, "base": t.base, "x": t.x, "y": t.y, "free": t.ship is None and t.free_at <= now}
                for t in self._sim.tugs.tugs]

    def locks(self):
        """Every lock: {name: {chamber: {"state", "side", "inside", "waiting_a", "waiting_b", "timer_min"}}}."""
        return {name: lock.summary() for name, (_, lock) in self._sim.locks.items()}

    def anchorages(self):
        """Every anchorage: {name: {"ships", "sea", "max_stay_h"}}."""
        return {name: {"ships": [x.ship_id for x in a.ships], "sea": bool(a.sea_anchorage), "max_stay_h": a.max_stay_h}
                for name, a in self._sim.anchorages.items()}

    def terminals(self):
        """Every container terminal: {name: {"quay_m", "ships": [(id, s0, s1, arrived, leaves)]}}."""
        return {name: {"quay_m": T.quay_length_m,
                       "ships": [(m.ship_id, m.s0, m.s1, m.arrived, m.leaves) for m in T.ships]}
                for name, T in self._sim.terminals.items()}

    def terminal_free(self, name, at=None):
        """Free stretches of quay [(a, b)] at a terminal, at minute `at` (planned departures counted)."""
        return list(self._sim.terminals[name].free_intervals(at))

    def berth_holder(self, berth_id):
        """The id of the ship holding a berth of the register, or None."""
        return self._sim.berth_ship.get(berth_id)

    def zone_berths(self, zone):
        """The register's berth ids of a berth zone."""
        return list((self._sim.destinations.get(zone) or {}).get("berths", []))

    # water and weather
    def travel_minutes(self, ship, route):
        """Minutes from the start of a route to each of its nodes at the ship's planning speed (speed limits and
        lock passages included): the clock the tide check uses."""
        import numpy as np
        return [float(x) for x in self._vts._times(self._vts._ship(ship), np.asarray(route, dtype=np.int64))]

    def approach_estimate(self, ship):
        """Planning-speed approach estimate for an entering ship; None for entries outside the sea approach."""
        return self._sim.approach_estimate(self._vts._ship(ship))

    def tide_ok(self, ship, route, start=None):
        """Would the route stay deep enough for the ship leaving at `start` (default now) and 60 min later?"""
        return self._vts.tide_ok(self._vts._ship(ship), route, self._sim.t if start is None else start)

    def high_waters(self):
        """Minutes from the start of every high water at Antwerp in the run (and its lookahead)."""
        return [float(x) for x in self._sim.high_waters]

    def water_level(self, node, minute=None):
        """Water level at a node (m above its datum: LAT at sea, the dock level behind the locks)."""
        t = self._sim.t if minute is None else minute
        return float(self._sim.level_along([node], [t])[0])

    def weather(self, minute=None):
        w = self._sim.weather.at(self._sim.now_ts(minute))
        return {"bft": int(w.bft), "visibility_m": float(w.visibility_m)}

    def stretches(self):
        """The regulated stretches of the regulations (regs §6), by name: usable in Control.restrict."""
        return sorted(self._vts.stretch_cells())

    def restrictions(self):
        """The restrictions in force or to come."""
        return [r for r in self._vts.restrictions.values() if r.until > self._sim.t]


class Control:
    """The orders a strategy gives. Each is checked; a refused order changes nothing and returns
    Result(ok=False, reason). Ships may be passed as ShipView, Ship or id."""

    def __init__(self, vts):
        self._vts = vts

    def clear(self, ship, book_ahead=True):
        """Clear a waiting ship to start its voyage now, if it passes the checks (pilot ships: route, weather,
        tide, pilots, destination, in that order; others: route and destination). On success the destination is
        reserved, the pilots taken and booked (book_ahead=False: only the first stretch's; the later ones are
        found on the way, or the ship waits for one off the fairway) and the ship boards, unmoors or sails. A
        ship that fails keeps its request; Result.reason names the first check it failed."""
        return self._vts.c_clear(ship, book_ahead=book_ahead)

    def check(self, ship):
        """The checks of clear() without clearing: Result(ok, reason, route). Like clear(), it chooses the ship's
        destination for this round (the berth the route goes to) but reserves nothing."""
        return self._vts.c_check(ship)

    def recheck(self, ship, at):
        """Call on_request for this waiting ship again at minute `at` (the next step at the earliest)."""
        return self._vts.c_recheck(ship, at)

    def wait_at_sea(self, ship, max_min):
        """An arrival at the pilot station that is not cleared waits off it, in the area but not at anchor (a
        ship told before it is there loses the time at sea), for up to max_min from when it first did so.
        Result.ok: it waits; False once max_min is over."""
        return self._vts.c_wait_at_sea(ship, max_min)

    def send_to_anchorage(self, ship):
        """Send an arrival waiting at the pilot station to an anchorage (Strategy.anchorage_order sets the order
        they are tried in). Result.ok False: none it may use has room or can be reached now; it waits where it is."""
        return self._vts.c_send_to_anchorage(ship)

    def set_speed(self, ship, kn):
        """Order a speed through the water (kn), between MIN_SPEED_KN and the ship's own maximum
        (ShipView.max_speed_kn). Speed limits and the current still apply on top. It holds until clear_speed or
        the ship's voyage ends (at a berth, an anchorage, the pilot station, a port or an exit; not at a lock)."""
        return self._vts.c_set_speed(ship, kn)

    def clear_speed(self, ship):
        return self._vts.c_set_speed(ship, None)

    def set_rank(self, ship, rank):
        """Right of way under way (movement.py: after distress and the regulated stretches, before the tie-break):
        lower goes first. The baseline gives each cleared pilot ship the next number; ships without a pilot rank
        last (10**9)."""
        return self._vts.c_set_rank(ship, rank)

    def set_avoid_locks(self, ship, names):
        """The locks this ship's routes keep off (a cost on them, not a ban: a ship that cannot go another way
        still passes them). Takes effect on its next route."""
        return self._vts.c_set_avoid_locks(ship, names)

    def restrict(self, kind, *, stretch=None, cells=None, direction=0, who=None, start=None, until=None, name=""):
        """Put a restriction on a stretch of water: a regulated stretch by name (View.stretches) or a set of
        cells. kind: "closed", "one_way" (direction UP or DOWN: the way ships may enter) or "no_meet". who: which
        ships it applies to (Restriction.applies). In force from start (default now) to until, at most
        RESTRICTION_MAX_MIN later. Result.value: its id."""
        return self._vts.c_restrict(kind, stretch=stretch, cells=cells, direction=direction, who=who or {},
                                    start=start, until=until, name=name)

    def lift(self, restriction_id):
        """End a restriction now."""
        return self._vts.c_lift(restriction_id)

    def note(self, ship, event, **extra):
        """Write an event into the ship's log (events.csv), to record a decision. ship None: a run-level event."""
        return self._vts.c_note(ship, event, **extra)


class Strategy:
    """Base class of a VTS strategy. Override what you decide; leave the rest to the defaults.

    name         how runs refer to it (Simulation(vts=name))
    description  one line for the summary
    levers       the levers it uses (LEVERS): recorded in the summary to group results by authority

    The engine calls the hooks; self.view and self.control are set before start(). Hooks that make a choice return
    None for the default or one of the options offered. Exceptions are not caught: a broken strategy stops the run.
    """
    name = "base"
    description = ""
    levers: tuple = ()

    def __init__(self, **options):
        self.options = options
        self.view: View | None = None
        self.control: Control | None = None

    def bind(self, view, control):
        self.view, self.control = view, control

    def start(self):
        """Called once before the first step."""

    # ---------------------------------------------------------------- clearance
    def on_request(self, ship):
        """A ship asked for clearance, or a recheck it was given came due. It may be cleared at once (control.clear)
        or left waiting for on_tick. Called for every ship, with and without a pilot."""

    def on_tick(self, now):
        """The planning round, every View.round_min minutes (15)."""

    # ---------------------------------------------------------------- choices (None: the default)
    def arrival_delay(self, ship, default_min):
        """Minutes to hold a ship at sea (slowing down) before it enters the area: 0 to ARRIVAL_DELAY_MAX_MIN.
        The default is the virtual arrival of container ships with a berth time (engine.slow_down_min)."""
        return None

    def choose_berth(self, ship, options, default):
        """The register's berth for a ship bound to a berth zone: one of options (free berth ids that take it).
        The default is drawn by the AIS calls of each berth (engine.draw_berth)."""
        return None

    def choose_quay_position(self, ship, terminal, options, default):
        """Where along a container terminal's quay a ship is to lie: a metre s0 with [s0, s0 + loa] inside one of
        options (free, suitable stretches [(a, b)] at its planned arrival). The default is the best fit."""
        return None

    def anchorage_order(self, ship, options):
        """The anchorages to try, in order, for a ship sent to anchor: names from options (those it may use with
        room, sea anchorages first then nearest). Leaving one out keeps the ship off it; an empty list keeps it
        waiting where it is."""
        return None

    def exit_order(self, ship, options):
        """The sea exits to try, in order, for a departing ship: names from options. Exits left out are tried
        after them (a ship is never left without a way out)."""
        return None

    def avoid_locks(self, ship, default):
        """The locks this ship keeps off when it has a choice (twin locks, the lock complexes of one dock system).
        The default is drawn once per ship by the AIS shares (engine.locks_avoided). A cost, not a ban."""
        return None

    def assign_pilots(self, ship, zone, n, free, default):
        """Which n pilots of a zone go to this ship: pilot ids from free. The default takes its own booked pilots
        first, then the others in order."""
        return None

    def assign_tugs(self, ship, n, free, default):
        """Which n tugs assist this ship: tug ids from free (every free tug, nearest first). The default takes
        the n nearest."""
        return None

    def choose_chamber(self, ship, lock, options, default):
        """The chamber of a lock a ship queues at: a chamber name from options (those it fits at this water).
        The default fills a chamber before starting another (locks.Lock._chamber_order)."""
        return None

    def lock_priority(self, ship, lock, default):
        """The ship's priority in the lock's queues (1 ordered ahead, 2 tide-dependent, 3 sea-going, 4 inland).
        Priority 3 and higher also keep the lockage from being held (locks.HOLD_FREE_PRIORITY)."""
        return None

    def keep_lock_open(self, lock, chamber, default):
        """An open chamber with nothing to load or unload now: True keeps its gates open (wait for more ships),
        False closes them and starts the lockage (or crosses empty to fetch the ships waiting on the other side).
        The default waits a little for ships coming (locks.Lock._hold_open). Kept open against the default for
        longer than KEEP_OPEN_MAX_MIN, the chamber closes."""
        return None


def lever_hooks():
    """Hook name -> lever, for the summary."""
    return {"on_request": "clearance", "on_tick": "clearance", "arrival_delay": "arrival_time",
            "choose_berth": "berth", "choose_quay_position": "quay_position", "anchorage_order": "anchorage",
            "exit_order": "exit", "avoid_locks": "lock_route", "assign_pilots": "pilots", "assign_tugs": "tugs",
            "choose_chamber": "lock_chamber", "lock_priority": "lock_priority", "keep_lock_open": "lockage"}


def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
