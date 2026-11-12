"""Ship agents (PLAN.md §1, §3): one class for both levels.

Level 1 (container ships from the schedule) and level 2 (background traffic from the AIS fits)
share the agent; level 2 skips the terminal model (a random dwell instead of handling).

A ship carries its dimensions, the derived flags of regs §2 (flags()), where it goes (a list of
legs), its position on the route it sails now (head distance along the route, in m) and a state:

    SPAWNED -> TO_STATION -> WAIT_CLEARANCE -> (TO_ANCHORAGE -> ANCHORED ->) BOARDING -> SAILING
    SAILING -> LOCK_QUEUE -> IN_LOCK -> SAILING -> MOORING -> AT_BERTH -> WAIT_CLEARANCE (departure)
    -> UNMOORING -> SAILING -> EXITED                       (plus PILOT_CHANGE, WAIT_PILOT on the way)

Short processes (boarding, pilot change, mooring, handling) are countdown timers in minutes.
times[] records when each phase started, for the KPIs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

SEA_GOING = ("container", "bulk_general", "tanker", "passenger")
INLAND = ("inland_cargo", "inland_tanker")
TANKERS = ("tanker", "inland_tanker")

# speed through the water (kn) for classes JA22 gives no planning speed for: assumed
CLASS_SPEED_KN = {"inland_cargo": 8.0, "inland_tanker": 8.0, "passenger": 12.0}
DOCK_SPEED_KN = 5.0                 # manoeuvring in docks / approaching a berth when no limit applies
UKC_FRACTION = 0.10                 # under-keel clearance: 10 % of the draught for sea-going ships ...
UKC_INLAND_M = 0.3                  # ... and this for inland craft
RIVER_CRUISE_MAX_DRAUGHT_M = 4.5
UKC_DOCK_M = 0.6                    # in the docks (fixed level, sounded berths) the berth register's minimum

# tugs for berthing / unberthing (regs §2 tanker rules, §8.11 ULCV; the rest an assumed size table,
# the master decides there, HPV 8.6.2 §9): (min LOA, tugs arriving, tugs leaving)
TUGS_BY_LOA = ((350.0, 3, 2), (250.0, 2, 2), (150.0, 1, 1), (0.0, 0, 0))


class State(str, Enum):
    SPAWNED = "spawned"
    TO_STATION = "to_station"               # sailing to the pilot station
    WAIT_CLEARANCE = "wait_clearance"       # asked the VTS (arrival at the station, or departure)
    TO_ANCHORAGE = "to_anchorage"
    ANCHORED = "anchored"
    BOARDING = "boarding"                   # pilot boarding (timer)
    SAILING = "sailing"
    PILOT_CHANGE = "pilot_change"           # timer
    WAIT_PILOT = "wait_pilot"               # no pilot free for the next zone
    LOCK_QUEUE = "lock_queue"
    IN_LOCK = "in_lock"
    MOORING = "mooring"                     # waiting for tugs / boatmen, then the timer
    AT_BERTH = "at_berth"                   # handling (containers) or dwell (timer)
    UNMOORING = "unmooring"
    DWELL_PORT = "dwell_port"               # at a port outside Antwerp (Vlissingen, Terneuzen): no berth model
    EXITED = "exited"


@dataclass(eq=False)          # identity: ships are compared as agents, not by value
class Ship:
    id: str
    cls: str
    loa: float
    beam: float
    draught: float
    level: int                              # 1 container (schedule), 2 background
    source: str
    destination: str                        # berth zone, place, or exit_<place>
    spawn_t: float                          # minutes since the start
    dg: str | None = None                   # dangerous-goods category (AIS A-D)
    teu: float | None = None
    name: str | None = None
    terminal: str | None = None             # level 1: Terminal name, or None (a berth in a dock zone)
    berth_zone: str | None = None
    schedule: dict = field(default_factory=dict)   # level 1: scheduled berth arrival / departure
    moves: int = 0                          # level 1: call size (container moves), set when handling starts
    stay_h: float | None = None             # level 1: the scheduled stay at the berth (h)
    cranes_wanted: int = 0                  # level 1: cranes the terminal would give a ship this size
    dwell_h: float = 0.0                    # level 2: time at the berth
    exit: str | None = None                 # where it leaves after the berth
    distress: bool = False
    arrival_draught: float | None = None    # the draught it came in at (draught changes at the berth)

    state: State = State.SPAWNED
    timer: float = 0.0
    # where it sails now
    full_route: list = field(default_factory=list) # the whole voyage now sailed (node ids)
    seg_start: int = 0                             # index in full_route where route starts
    route: list = field(default_factory=list)      # node ids of the part up to the next lock
    s: object = None                               # cumulative distance along route (numpy array)
    head: float = 0.0                              # distance of the bow along route
    goal: str = ""                                 # what reaching the end of the route means
    cells: list = field(default_factory=list)      # route cells under its centre line (bow last)
    hull: list = field(default_factory=list)       # every cell its hull (beam + clearance) covers
    blocked_steps: int = 0
    reroutes: int = 0
    side: int = 1                                  # side of its lane it keeps: +1 starboard, -1 port (overtaking)
    lateral_m: float = 0.0                         # how far it stands off the route's centre line (+ starboard)
    lock_voyage: bool = False                      # the voyage it is cleared for passes a lock
    infeasible: str | None = None                  # why its voyage cannot be made (it is removed)
    encounter_hold: int = 0
    # services
    pilots: list = field(default_factory=list)
    pilot_zone: str | None = None
    tugs: list = field(default_factory=list)
    tugs_ready_at: float | None = None
    boatmen: int = 0
    berth: dict | None = None                      # {"kind": "terminal"/"berth"/"place", ...}
    anchorage: str | None = None
    lock: str | None = None
    lock_index: int = -1                           # index of the lock node in route
    request_t: float | None = None                 # when it asked the VTS
    clear_order: int = 10**9                       # rank given by the VTS (movement priority)
    departing: bool = False
    at: int | None = None                          # node it lies at while off the mesh
    target: int | None = None                      # node the current voyage ends at
    times: dict = field(default_factory=dict)
    durations: dict = field(default_factory=dict)  # minutes spent in each state
    since: float | None = None
    log: list = field(default_factory=list)

    # ------------------------------------------------------------------ flags (regs §2)
    @property
    def sea_going(self):
        """River cruise ships (class passenger, this shallow) are inland vessels: no compulsory pilot (regs §2)."""
        return self.cls in SEA_GOING and not (self.cls == "passenger" and self.draught < RIVER_CRUISE_MAX_DRAUGHT_M)

    @property
    def needs_pilot(self):
        """Compulsory pilotage: LOA > 80 m, not inland (NtM 1/16-1/17); tankers that are not gas-free
        always (taken as every sea-going tanker)."""
        return self.sea_going and (self.loa > 80 or self.cls == "tanker")

    @property
    def ulcv(self):
        return self.cls == "container" and (self.loa >= 350 or self.beam >= 51)

    @property
    def marginal(self):
        """Needs a GNA permit (JA22 art. 1); the draught limit taken at its lowest common value."""
        return self.sea_going and (self.loa >= 300 or self.beam >= 45 or self.draught >= 12.0)

    @property
    def marginal_visibility(self):
        """Ships that need 1000 m visibility at the start of the voyage (JA22, GB24)."""
        return self.sea_going and (self.loa >= 300 or self.beam >= 45 or self.draught >= 12.5)

    @property
    def tide_dependent(self):
        return self.draught > 13.10

    @property
    def imo2_gas(self):
        """Taken as a sea-going tanker in AIS hazard category A (no cargo data in AIS)."""
        return self.cls == "tanker" and self.dg == "A"

    @property
    def needs_boatmen(self):
        return self.sea_going and self.loa >= 80

    @property
    def ukc_m(self):
        return UKC_INLAND_M if not self.sea_going else UKC_FRACTION * self.draught

    @property
    def need_m(self):
        return self.draught + self.ukc_m

    @property
    def need_dock_m(self):
        """Water needed behind the locks: 10 % of the draught there made ships the register allows
        (15.5 m at a berth of 16.1 m of water) unable ever to sail."""
        return self.draught + min(self.ukc_m, UKC_DOCK_M)

    def oversized(self, zone="river"):
        """Oversized for a zone (regs §2): sea / Western Scheldt / below Doel-Lillo LOA >= 210 m or
        T >= 10 m; Oostgat-Sardijngeul 170 m / 7 m; above Doel-Lillo 170 m / 8 m; docks 200 m, B 27 m, T 10 m."""
        if zone == "dock":
            return self.loa >= 200 and self.beam >= 27 and self.draught >= 10
        loa, t = {"oostgat": (170, 7.0), "upstream": (170, 8.0)}.get(zone, (210, 10.0))
        return self.loa >= loa or self.draught >= t

    def tugs_needed(self, departing=False):
        if not self.sea_going:
            return 0
        n = next(dep if departing else arr for lo, arr, dep in TUGS_BY_LOA if self.loa >= lo)
        if self.cls == "tanker" and self.loa > 120:
            n = max(n, 1)
        return n

    def pilots_needed(self, zone):
        """Two river pilots (at least one of the highest category) for LOA >= 340 m or B >= 51 m,
        and for LOA >= 300 m or B >= 45 m on a voyage to or from the locks (regs §8.8)."""
        if zone != "river":
            return 1
        if self.loa >= 340 or self.beam >= 51:
            return 2
        if self.lock_voyage and (self.loa >= 300 or self.beam >= 45):
            return 2
        return 1

    def rule_flags(self, zone="river"):
        """The flags the encounter rules look at (navigation_rules)."""
        return {"loa": self.loa, "beam": self.beam, "ulcv": self.ulcv, "imo2_gas": self.imo2_gas,
                "oversized": self.oversized(zone), "special_transport": False}

    @property
    def rule_relevant(self):
        """Could any encounter or spacing rule (regs §6) apply to this ship?"""
        return self.loa >= 80 and (self.ulcv or self.imo2_gas or self.loa >= 170 or self.draught >= 7.0)

    def vts_priority(self):
        """Distress, then tide-dependent ships, then the rest (PLAN.md §4); FCFS within."""
        return (0 if self.distress else 1 if self.tide_dependent else 3, self.request_t or 0.0)

    def stw_kn(self, leg, planning_speed):
        """Speed through the water: JA22 planning speeds where they exist (container / bulk / tanker),
        else the class speed."""
        v = planning_speed(self.cls, self.draught, "departure" if self.departing else "arrival", leg)
        return v or CLASS_SPEED_KN.get(self.cls, 12.0)

    # ------------------------------------------------------------------ bookkeeping
    def mark(self, what, t):
        self.times.setdefault(what, t)

    def note(self, t, event, **extra):
        self.log.append({"t": t, "ship": self.id, "event": event, **extra})

    def set_state(self, state, t, **extra):
        if self.since is not None:
            self.durations[self.state.value] = self.durations.get(self.state.value, 0.0) + t - self.since
        self.since = t
        self.state = state
        self.mark(state.value, t)
        self.note(t, state.value, **extra)

    @property
    def remaining_m(self):
        return float(self.s[-1] - self.head) if self.s is not None and len(self.s) else 0.0


def cranes_for(teu):
    """Cranes a terminal gives a ship of this size (sprzet_ladunkowy.md §3), before the density limit."""
    for top, n in ((3000, 2), (5000, 3), (10000, 5), (14000, 6), (math.inf, 8)):
        if teu < top:
            return n
