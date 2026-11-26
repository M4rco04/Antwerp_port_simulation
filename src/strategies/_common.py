"""Shared building blocks of the port strategies (docs/strategies/port_management_strategies.md §3).

Not a strategy (the leading underscore keeps strategies.available() off it). What is here:

- arrival times at a ship's next lock (B2) and the ships coming to each lock side within a horizon;
- a lock-wait estimator from what view.locks() shows (B1), with a cycle time per lock taken as a prior;
- the fuel a ship burns sailing at a speed or waiting, from the emissions module's own formulas (B4), so that a
  strategy decides on the same fuel model the run is judged by;
- the twin locks and lock complexes a ship may be sent through (the lock_route lever).

Everything reads only the strategy's view (and static infrastructure), as docs/VTS_API.md §6 asks.
"""

from __future__ import annotations

import math
from collections import defaultdict

KNOT_M_MIN = 1852.0 / 60.0
APPROACH_M, APPROACH_KN = 1500.0, 3.6              # the last approach to a lock is sailed slowly (movement.py)

# one lockage, one way: the ships going in and out plus closing, levelling and opening (MODEL.md §14). A prior from
# the operating times there and two or three ships' entry and exit; to be checked against the events of a baseline
# run (check B1 of the strategies document)
CYCLE_MIN = {"Zandvliet": 50.0, "Berendrecht": 45.0, "Kieldrecht": 40.0, "Kallo": 40.0, "Boudewijn": 35.0,
             "Van Cauwelaert": 32.0, "Royers": 21.0, "Kattendijk": 48.0, "Kreekrak": 23.0, "Hansweert": 25.0,
             "Terneuzen": 37.0}
DEFAULT_CYCLE_MIN = 35.0
GAP_LONG_M, GAP_SIDE_M = 10.0, 2.0                 # spacing in a chamber (locks.LockTimes)

# the lock alternatives of the lock_route lever (engine.TWIN_LOCKS, engine.LOCK_COMPLEXES)
TWINS = (("Zandvliet", "Berendrecht"), ("Boudewijn", "Van Cauwelaert"))
COMPLEXES = ((("Zandvliet", "Berendrecht"), ("Boudewijn", "Van Cauwelaert")), (("Kieldrecht",), ("Kallo",)))
WIDE_BEAM_M = 43.0                                 # these ships keep to Berendrecht (regs §8.9): not moved
# sill depths (MODEL.md §14): a ship is only moved to a lock whose sill has a metre to spare under its draught
SILL_M = {"Berendrecht": 13.6, "Zandvliet": 13.6, "Kieldrecht": 17.8, "Kallo": 12.58, "Boudewijn": 10.33,
          "Van Cauwelaert": 9.83}

# value of time by class, kg of fuel-equivalent per minute of delay (assumed; varied in the sensitivity runs)
VOT_KG_MIN = {"container": 4000 / 60, "tanker": 2000 / 60, "bulk_general": 1500 / 60, "passenger": 2000 / 60,
              "inland_cargo": 300 / 60, "inland_tanker": 300 / 60}
INLAND_SFC_G_KWH = 220.0 * 1.13                    # assumed for decisions only: a craft's engines and auxiliaries


def cycle_min(lock):
    return CYCLE_MIN.get(lock, DEFAULT_CYCLE_MIN)


def other_side(side):
    return "b" if side == "a" else "a"


def vot(ship):
    return VOT_KG_MIN.get(ship.cls, 1500 / 60)


def speed_kn(ship):
    """The speed it sails at now: the one the VTS ordered, else its planning speed on the river."""
    return ship.ordered_speed_kn or ship.planning_speed_kn("river")


def eta_min(ship, kn=None):
    """Minutes until it reaches the end of its route part (its next lock, when it has one) at a speed."""
    kn = max(kn or speed_kn(ship), 1.0)
    d = ship.remaining_m
    slow = min(d, APPROACH_M)
    return (d - slow) / (kn * KNOT_M_MIN) + slow / (min(kn, APPROACH_KN) * KNOT_M_MIN)


def capacity(chamber, loa, beam):
    """Ships of this size one lockage of a chamber takes (a grid: lanes across times rows along)."""
    across = int((chamber["width_m"] + GAP_SIDE_M) // (beam + GAP_SIDE_M))
    along = int((chamber["length_m"] + GAP_LONG_M) // (loa + GAP_LONG_M))
    return max(across, 0) * max(along, 0)


def fits(chamber, loa, beam):
    return loa <= chamber["length_m"] and beam <= chamber["width_m"]


class LockModel:
    """A snapshot of the locks (view.locks()) with the estimates built on it. Make one per round or step."""

    def __init__(self, view):
        self.view = view
        self.locks = view.locks()

    def chambers(self, lock):
        return self.locks.get(lock, {})

    def queued(self, lock, side):
        """Ship ids waiting at a lock's side, over its chambers."""
        return [i for c in self.chambers(lock).values() for i in c["waiting_" + side]]

    def time_to_open(self, lock, chamber, side):
        """Minutes until a chamber lies open at a side."""
        c = self.chambers(lock)[chamber]
        tc = cycle_min(lock)
        if c["state"] == "open":
            return 0.0 if c["side"] == side else tc
        # closing, levelling or opening: c["side"] is the side it is leaving
        rest = c["timer_min"] + tc / 3.0
        return rest if other_side(c["side"]) == side else rest + tc

    def entry_min(self, lock, side, loa, beam, ahead=0, chamber=None):
        """Minutes from now until a ship of this size at a side could go into a chamber (the best one, or the one
        named): the time until it opens there plus a return trip per lockage of ships queued before it. `ahead`
        adds ships known to be coming before it. None if no chamber takes it."""
        best = None
        for name, c in self.chambers(lock).items():
            if (chamber is not None and name != chamber) or not fits(c, loa, beam):
                continue
            cap = max(capacity(c, loa, beam), 1)
            q = len(c["waiting_" + side]) + ahead
            t = self.time_to_open(lock, name, side) + (q // cap) * 2.0 * cycle_min(lock)
            best = t if best is None else min(best, t)
        return best

    def load(self, lock):
        """A side-blind measure of how busy a lock is: minutes of lockages queued per chamber."""
        cs = self.chambers(lock)
        if not cs:
            return math.inf
        n = sum(len(c["waiting_a"]) + len(c["waiting_b"]) + len(c["inside"]) for c in cs.values())
        return n / len(cs) * cycle_min(lock) / 3.0

    def room_left(self, lock, chamber, loa, beam):
        """Does a ship of this size still fit beside those inside (an area test with the spacing, conservative)?"""
        c = self.chambers(lock)[chamber]
        used = 0.0
        for sid in c["inside"]:
            s = self.view.ship(sid)
            if s is not None:
                used += (s.loa + GAP_LONG_M) * (s.beam + GAP_SIDE_M)
        return used + (loa + GAP_LONG_M) * (beam + GAP_SIDE_M) <= 0.8 * c["length_m"] * c["width_m"] and fits(c, loa, beam)


def coming(view, horizon_min):
    """Ships sailing towards a lock and not yet queued: {(lock, side): [(eta_min, ShipView)]}, nearest first."""
    out = defaultdict(list)
    for s in view.ships():
        if s.state != "sailing" or s.lock:
            continue
        lock = s.next_lock
        if lock is None:
            continue
        t = eta_min(s)
        if t <= horizon_min:
            out[(lock, s.next_lock_side)].append((t, s))
    for v in out.values():
        v.sort(key=lambda x: x[0])
    return out


def lock_alternatives(ship, model=None):
    """The avoid-sets this ship may be given instead of its own (the other twin, the other complex): a list of
    (avoid tuple, locks it then uses). Empty when its own set is not drawn yet or it may not be moved."""
    own = ship.avoid_locks
    if own is None or ship.beam >= WIDE_BEAM_M:
        return []
    own = tuple(own)
    out = []

    def usable(locks):
        return all(ship.draught + 1.0 <= SILL_M.get(l, 99.0) for l in locks)

    for a, b in TWINS:
        if a in own and b not in own and usable((a,)):
            out.append((tuple(x for x in own if x != a) + (b,), (a,)))
        elif b in own and a not in own and usable((b,)):
            out.append((tuple(x for x in own if x != b) + (a,), (b,)))
    if ship.sea_going:
        for first, second in COMPLEXES:
            uses_first = not any(l in own for l in first)
            uses_second = not any(l in own for l in second)
            if uses_first == uses_second:
                continue
            to, frm = (second, first) if uses_first else (first, second)
            if not usable(to):
                continue
            avoid = tuple(x for x in own if x not in to) + tuple(frm)
            out.append((avoid, to))
    return out


def using(ship, avoid, pair):
    """Which locks of a pair/complex a ship with this avoid-set takes."""
    return tuple(l for l in pair if l not in avoid)


class _Hull:
    """What emissions.Profile reads of a ship, from a ShipView."""
    __slots__ = ("sea_going", "cls", "loa", "beam", "draught", "arrival_draught", "teu", "dg")

    def __init__(self, s):
        self.sea_going, self.cls, self.loa, self.beam = s.sea_going, s.cls, s.loa, s.beam
        self.draught = self.arrival_draught = s.draught
        self.teu, self.dg = s.teu, s.dg


class FuelModel:
    """kg of fuel a minute for a ship sailing at a speed through the water, or lying waiting (the emissions module's
    formulas: IMO Admiralty power and SFC for sea-going ships, Bolt's resistance in deep water for inland craft)."""

    def __init__(self):
        self._prof = {}

    def _profile(self, s):
        p = self._prof.get(s.id)
        if p is None:
            import emissions as EM
            p = self._prof[s.id] = EM.Profile(_Hull(s))
        return p

    def sail(self, s, kn):
        import emissions as EM
        p = self._profile(s)
        if not p.sea:
            kw = min(EM.bolt_kw(s.loa, s.beam, s.draught, kn * 1852.0 / 3600.0), p.installed)
            g_h = kw * INLAND_SFC_G_KWH + (p.hotel[2] * EM.SFC_BASE["AE"] if p.hotel is not None else 0.0)
            return g_h / 60000.0
        kw = EM.admiralty_kw(p, kn, s.draught)
        load = kw / p.mcr if p.mcr else 0.0
        ae, boiler = p.aux_kw("sea" if kn > 5.0 else "manoeuvring")
        g_h = kw * EM.sfc_main(p, max(load, 0.01)) + ae * EM.SFC_BASE["AE"] + boiler * EM.SFC_BASE["boiler"]
        return g_h / 60000.0

    def wait(self, s):
        import emissions as EM
        p = self._profile(s)
        if not p.sea:
            return (p.hotel[1] * EM.SFC_BASE["AE"] / 60000.0) if p.hotel is not None else 0.0
        ae, boiler = p.aux_kw("anchored")
        return (ae * EM.SFC_BASE["AE"] + boiler * EM.SFC_BASE["boiler"] + EM.STANDBY_ME_SHARE * p.mcr * EM.SFC_BASE[p.engine]) / 60000.0


def jit_speed(ship, wait_min, margin_min=10.0, floor_share=0.6, floor_kn=4.0):
    """The speed that brings a ship to its next lock about margin_min before it can go in, when it would otherwise
    wait there wait_min; None when slowing is not worth it. Never below floor_share of its planning speed or floor_kn
    (a main engine at very low load burns more a kWh: SFC_ME(l), MODEL.md §17.1)."""
    kn = speed_kn(ship)
    t = eta_min(ship, kn)
    target = t + wait_min - margin_min
    if wait_min < 20.0 or target <= t + 5.0:
        return None
    lo = max(floor_share * ship.planning_speed_kn("river"), floor_kn, 3.0)
    hi = ship.max_speed_kn("river")
    d = max(ship.remaining_m - APPROACH_M, 0.0)
    slow = target - min(ship.remaining_m, APPROACH_M) / (APPROACH_KN * KNOT_M_MIN)
    if d <= 0 or slow <= 0:
        return None
    v = d / (slow * KNOT_M_MIN)
    v = min(max(v, lo), hi)
    return v if v < kn - 0.5 else None
