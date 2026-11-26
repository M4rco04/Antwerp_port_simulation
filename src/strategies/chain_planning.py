"""Strategy 2, rolling-horizon chain planning ("VTS 3, with buffers"): docs/strategies/port_management_strategies.md §5.

Every planning round the waiting pilot ships are planned in priority order (distress, tide-dependent, container ships by
berth time, then first come first served). Each gets the earliest start, in 15-min steps up to the horizon, at which
its whole voyage fits the reservation tables with buffers:

    pilots       per zone and 15-min bin, each job holding a pilot for the zone's time on board plus its return;
                 capacity is the pilots free now plus those on a job coming back as their jobs end
    pilot boats  one for 30 min for a boarding at sea
    locks        lockages per lock side, a window of one return trip each, for the ships queued and planned there
    quay         a container ship's terminal must have room for it when it arrives, after the ships planned before it

A ship whose start is now is cleared (the engine's own checks still decide); one planned later keeps its slot, which the
ships after it plan around, and waits off the station (or at its berth). Locks, chambers and speeds are run as in
strategy 1 (look-ahead lockages, earliest-entry chamber, JIT for inland craft), on top of the plan.

Robustness (the reading's warning about tightly coupled plans): buffers on every slot; the plan is rebuilt every round
from what is real now; and when more than 30 % of the slots due in the last hour were missed, the strategy falls back
to strategy 1's local rules for two hours (degraded mode). Tier 3: it also chooses where along the quay a container ship
lies (the stretch that leaves the longest free quay for the ships after it).

Options: those of local_lookahead, plus horizon_h 6, buffer_pilot_min 15, buffer_lock_min 10, buffer_quay_min 30,
missed_share 0.3, degraded_h 2, quay True (tier 3; False gives the tier-2 variant).
"""

from __future__ import annotations

import math

import numpy as np

from strategies import _common as C
from strategies.local_lookahead import LocalLookahead

BIN_MIN = 15.0
JOB_MIN = {"sea": 150.0 + 120.0, "river": 180.0 + 90.0, "dock": 60.0 + 30.0}   # on board + return (MODEL.md §9)
BOAT_MIN = 30.0


class ChainPlanning(LocalLookahead):
    name = "chain_planning"
    description = "S2: a rolling 6-h plan of time slots (pilots, pilot boats, lockages, quay) with buffers and a degraded mode"
    levers = ("clearance", "anchorage", "speed", "lock_route", "lock_chamber", "lockage", "quay_position")

    def start(self):
        super().start()
        o = self.options
        self.horizon_min = float(o.get("horizon_h", 6.0)) * 60.0
        self.buf_pilot = float(o.get("buffer_pilot_min", 15.0))
        self.buf_lock = float(o.get("buffer_lock_min", 10.0))
        self.buf_quay = float(o.get("buffer_quay_min", 30.0))
        self.missed_share = float(o.get("missed_share", 0.3))
        self.degraded_min = float(o.get("degraded_h", 2.0)) * 60.0
        self.use_quay = bool(o.get("quay", True))
        if not self.use_quay:
            self.levers = tuple(l for l in self.levers if l != "quay_position")
        self.planned = {}                      # ship id -> planned start (minute)
        self.due_log = []                      # (minute, missed?) for slots that came due
        self.degraded_until = -math.inf

    # ------------------------------------------------------------------ tables
    def tables(self):
        view = self.view
        n = int(self.horizon_min // BIN_MIN) + int(max(JOB_MIN.values()) // BIN_MIN) + 8
        t = np.arange(n) * BIN_MIN
        cap = {}
        for z, job in JOB_MIN.items():
            free, total = view.pilots_free(z), view.pilots_total(z)
            cap[z] = free + (total - free) * np.minimum(1.0, t / job)
        boats_free = view.pilot_boats_free()
        boats_total = max(boats_free, 8)
        cap["boat"] = boats_free + (boats_total - boats_free) * np.minimum(1.0, t / BOAT_MIN)
        load = {k: np.zeros(n) for k in cap}
        return {"cap": cap, "load": load, "n": n, "locks": {}, "quay": {}}

    def bin(self, minute):
        return int(max(minute - self.view.now, 0.0) // BIN_MIN)

    def lock_windows(self, tab, model, lock, side, ship):
        key = (lock, side)
        if key not in tab["locks"]:
            chambers = model.chambers(lock)
            cap = sum(max(C.capacity(c, ship.loa, ship.beam), 1) for c in chambers.values() if C.fits(c, ship.loa, ship.beam))
            w = 2.0 * C.cycle_min(lock)
            load = np.zeros(int(self.horizon_min // w) + 20)
            q = len(model.queued(lock, side))
            k = 0
            while q > 0 and cap > 0 and k < len(load):         # the ships queued now fill the first windows
                take = min(q, cap)
                load[k] += take
                q -= take
                k += 1
            tab["locks"][key] = {"cap": max(cap, 1), "w": w, "load": load}
        return tab["locks"][key]

    # ------------------------------------------------------------------ one ship's chain
    def chain(self, ship, route):
        view = self.view
        tm = view.travel_minutes(ship, route)
        zones = [(z, tm[i]) for z, i in view.pilot_zones(route)]
        locks = [(name, tm[i], i) for name, i in view.route_locks(route)]
        return {"tm": tm, "zones": zones, "locks": locks, "end": tm[-1] if tm else 0.0,
                "boat": bool(ship.at_station and not ship.departing)}

    def fits_at(self, tab, model, ship, ch, t0, route, reserve=False):
        view = self.view
        cap, load = tab["cap"], tab["load"]
        for k, (z, dt) in enumerate(ch["zones"]):
            if z not in cap:
                continue
            need = ship.pilots_needed(z)
            a = self.bin(t0 + dt - (self.buf_pilot if k else 0.0))
            b = min(self.bin(t0 + dt + JOB_MIN[z] + self.buf_pilot), tab["n"] - 1)
            if a >= tab["n"]:
                continue                                  # beyond the tables: not planned this far
            if not reserve and np.any(load[z][a:b + 1] + need > cap[z][a:b + 1] + 1e-9):
                return False
            if reserve:
                load[z][a:b + 1] += need
        if ch["boat"]:
            a = self.bin(t0)
            b = min(self.bin(t0 + BOAT_MIN), tab["n"] - 1)
            if not reserve and np.any(load["boat"][a:b + 1] + 1 > cap["boat"][a:b + 1] + 1e-9):
                return False
            if reserve:
                load["boat"][a:b + 1] += 1
        for name, dt, _ in ch["locks"]:
            side = None
            node_side = view.ship(ship.id)
            # the side a ship comes to a lock from is only known for its next lock; the others count on both sides
            if node_side is not None and node_side.next_lock == name:
                side = node_side.next_lock_side
            for s in ((side,) if side else ("a", "b")):
                lw = self.lock_windows(tab, model, name, s, ship)
                k = int((t0 + dt - view.now + self.buf_lock) // lw["w"])
                if k >= len(lw["load"]):
                    continue
                if not reserve and lw["load"][k] + 1 > lw["cap"]:
                    return False
                if reserve:
                    lw["load"][k] += 1 / (1 if side else 2)
        if self.use_quay and ship.terminal and not ship.departing:
            at = t0 + ch["end"] + self.buf_quay
            planned = tab["quay"].setdefault(ship.terminal, [])
            taken = sum(l for t, l in planned if abs(t - at) < 12 * 60)
            longest = max((b - a for a, b in view.terminal_free(ship.terminal, at)), default=0.0)
            if not reserve and longest < ship.loa + taken:
                return False
            if reserve:
                planned.append((at, ship.loa))
        if t0 > view.now and not reserve and not view.tide_ok(ship, route, t0):
            return False
        return True

    def plan_start(self, tab, model, ship, route):
        ch = self.chain(ship, route)
        now = self.view.now
        for k in range(int(self.horizon_min // BIN_MIN) + 1):
            t0 = now + k * BIN_MIN
            if self.fits_at(tab, model, ship, ch, t0, route):
                self.fits_at(tab, model, ship, ch, t0, route, reserve=True)
                return t0
        return None

    # ------------------------------------------------------------------ the round
    def priority(self, ship):
        base = self.view.default_priority(ship)
        berth = ship.scheduled_berth_min if (ship.cls == "container" and not ship.departing) else None
        return (base[0], 0 if berth is not None else 1, berth if berth is not None else base[1], base[1])

    def degraded(self):
        now = self.view.now
        self.due_log = [(t, m) for t, m in self.due_log if now - t <= 60.0]
        if len(self.due_log) >= 5 and sum(m for _, m in self.due_log) / len(self.due_log) > self.missed_share:
            if self.degraded_until < now:
                self.control.note(None, "chain_planning_degraded", until=now + self.degraded_min,
                                  missed=sum(m for _, m in self.due_log), due=len(self.due_log))
            self.degraded_until = now + self.degraded_min
            self.due_log = []
        return now < self.degraded_until

    def on_tick(self, now):
        if self.degraded():
            return super().on_tick(now)                   # strategy 1's local rules until the plan can be trusted
        view, control = self.view, self.control
        model, _ = self.snapshot()
        tab = self.tables()
        waiting = [s for s in view.requests() if s.needs_pilot and s.ready]
        for ship in sorted(waiting, key=self.priority):
            due = self.planned.pop(ship.id, None)
            self.rebalance(ship)
            check = control.check(ship)
            if check.removed:
                continue
            if not check.ok:
                if due is not None and due <= now:
                    self.due_log.append((now, True))
                if check.reason == "pilot_lost":
                    continue
                self.not_cleared(ship, check)
                continue
            t0 = self.plan_start(tab, model, ship, check.route)
            if t0 is not None and t0 <= now:
                result = control.clear(ship)
                if due is not None and due <= now:
                    self.due_log.append((now, not result.ok))
                if result.ok or result.removed or result.reason == "pilot_lost":
                    continue
                self.not_cleared(ship, result)
            elif t0 is not None:
                self.planned[ship.id] = t0               # its slot: the ships after it plan around it
                if not ship.departing and ship.state == "wait_clearance" and ship.at_station:
                    if not control.wait_at_sea(ship, self.sea_wait_max + (t0 - now)).ok:
                        control.send_to_anchorage(ship)
            else:
                from vts_api import Result
                self.not_cleared(ship, Result(False, "pilot"))
        if self.on["jit"]:
            self.pace()

    # ------------------------------------------------------------------ quay (tier 3)
    def choose_quay_position(self, ship, terminal, options, default):
        if not self.use_quay or not options:
            return None
        best, best_key = None, None
        for a, b in options:
            for s0 in {a, b - ship.loa}:
                if s0 < a - 1e-6 or s0 + ship.loa > b + 1e-6:
                    continue
                left = max(s0 - a, b - (s0 + ship.loa))
                # the longest stretch left free in this interval; ties: the default's side
                key = (left, -abs(s0 - default))
                if best_key is None or key > best_key:
                    best, best_key = s0, key
        if best is None or abs(best - default) < 1e-6:
            return None
        return float(best)
