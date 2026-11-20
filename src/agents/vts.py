"""The VTS (PLAN.md §4, §8; MODEL.md §9; docs/VTS_API.md): the engine's side of the strategy API.

The VTS holds the queue of ships waiting for clearance, runs the checks, carries out the orders of the strategy and
offers it the choices the engine makes. What is decided lives in a Strategy (src/strategies/, agents/vts_api.py);
what is checked and done lives here and in the engine. The baseline strategy (strategies/baseline.py) is the
simple first-come-first-served VTS the model was calibrated with.

Every ship asks before every voyage (request): an arrival at the pilot station or at anchor, a ship ready to leave
its berth, a ship at the end of a stay in a port, an inland craft moving on to its next call or weighing anchor.
Kinds of request: "go" (a voyage from where it lies), "unmoor" (from its berth, with tugs and boatmen), "hop" (an
inland craft to its next call in the port), "resume" (an inland craft weighing anchor on its way).

A ship that needs a pilot is cleared (Control.clear) when all of these hold:

    route        a route exists for its draught (+ UKC), size and the locks it needs (engine.voyage_route:
                 valid at the run's lowest water if possible, else the deep channel, which needs the tide;
                 to a sea exit only as far as the pilot station, then open sea)
    weather      the gates of regs §9 (agents/weather_gates.py): visibility, wind, storm
    tide         the arrival windows of bulk carriers and tankers at CP (regs §8.6), and the whole route (up to
                 the pilot station on the way out) stays deep enough when it leaves now AND 60 min later, sailing
                 at its planning speed, the speed limits in the docks and the time of a lock passage (regs §8:
                 the window at the start must be at least 60 min)
    pilot        a pilot (two for the largest ships) is free for its first pilot stretch, pilots can
                 be booked for every later stretch of the voyage for when it gets there (never for a
                 time before now), and a pilot boat for a boarding at sea / at Vlissingen
    destination  its terminal has quay room, or its berth is free (the one the route goes to: the
                 destination is chosen once per round)

A ship without a pilot (inland craft, small ships) is cleared when its route and destination exist; its master
keeps to the tide and the weather (under way the mesh still stops it for the water, movement._depth_limit).
"""

from __future__ import annotations

import math

import numpy as np

import navigation_rules as NR
from vts_api import (ARRIVAL_DELAY_MAX_MIN, KEEP_OPEN_MAX_MIN, LOCK_PRIORITIES, MIN_SPEED_KN, RESTRICTION_KINDS,
                     RESTRICTION_MAX_MIN, Control, Restriction, Result, ShipView, Strategy, View, is_number,
                     lever_hooks)

PLAN_EVERY = 3
WINDOW_MIN = 60.0
LOCK_TRANSIT_MIN = 60.0
KNOT_M_MIN = 1852.0 / 60.0


class VTS:
    def __init__(self, sim, strategy):
        self.sim = sim
        self.plan_every = PLAN_EVERY
        self.requests = []                     # ships waiting for clearance, in the order they asked
        self.cleared = 0                       # pilot ships cleared (their rank, Ship.clear_order)
        self.cleared_free = 0                  # ships without a pilot cleared
        self.restrictions = {}                 # id -> Restriction
        self._next_restriction = 1
        self._stretch_cells = None
        self._open_against = {}                # (lock, chamber) -> minute it was first kept open against the default
        self.rejected = {}                     # lever -> refused orders and choices
        self.overrides = {}                    # lever -> choices the strategy made other than the default
        self.strategy = strategy
        self.view = View(sim, self)
        self.control = Control(self)
        base = {name for name, f in vars(Strategy).items() if callable(f)}
        self._hooks = {name for name in base if getattr(type(strategy), name, None) is not getattr(Strategy, name, None)}
        strategy.bind(self.view, self.control)

    def start(self):
        self.strategy.start()

    # ------------------------------------------------------------------ the queue
    def request(self, ship, now, kind=None):
        """A ship asks for clearance. Returns True if the strategy cleared it at once."""
        # the time of this voyage's request: a departure is queued from when it is ready to leave, not
        # from when it asked to come in (that put every departure ahead of every waiting arrival); a ship
        # put back after losing its pilot keeps its place
        if ship.request_t is None or getattr(ship, "request_leg", None) != ship.departing:
            ship.request_t = now
            ship.request_leg = ship.departing
        if kind is not None:
            ship.vts_kind = kind
        elif getattr(ship, "vts_kind", None) is None:
            ship.vts_kind = "go"
        ship.vts_recheck = None
        new = ship not in self.requests
        if new:
            self.requests.append(ship)
            ship.vts_req = True
            if ship.needs_pilot:
                ship.note(now, "vts_request", departing=ship.departing)
        ship.vts_tried = False                 # set by any clearance order for it (clear, recheck, ...)
        self.strategy.on_request(ShipView(ship, self.sim))
        waiting = getattr(ship, "vts_req", False)
        if waiting and not ship.needs_pilot:
            # left waiting by the strategy: it waits where it lies, for clearance (the baseline tries a ship without a
            # pilot at once, and the engine already put one that could not go into WAIT_CLEARANCE)
            from ship import State
            if new and not ship.vts_tried:
                ship.note(now, "vts_request", departing=ship.departing, kind=ship.vts_kind)
            if ship.state not in (State.WAIT_CLEARANCE, State.ANCHORED, State.EXITED):
                ship.set_state(State.WAIT_CLEARANCE, now)
        return not waiting

    def withdraw(self, ship):
        if ship in self.requests:
            self.requests.remove(ship)
        ship.vts_req = False
        ship.vts_recheck = None

    def due(self, ship, now):
        """Has a recheck the strategy asked for come due?"""
        t = getattr(ship, "vts_recheck", None)
        return t is not None and now >= t and getattr(ship, "vts_req", False)

    def recheck(self, ship, now):
        ship.vts_recheck = None
        ship.vts_tried = False
        self.strategy.on_request(ShipView(ship, self.sim))

    def plan(self, now):
        """The planning round (every PLAN_EVERY steps)."""
        self.strategy.on_tick(now)

    # ------------------------------------------------------------------ checks
    def window_ok(self, ship, route, now):
        """The arrival windows of bulk carriers and tankers at CP (regs §8.6): T 13.5-14.5 m at CP no later
        than HW + 1 h; T > 14.5 m to the right-bank locks at CP within HW +- 15 min, to Kieldrecht at the
        Deurganckdok mouth from HW to HW + 40 min. The Deurganckdok mouth is taken as the lock's approach."""
        if ship.departing or ship.cls not in ("bulk_general", "tanker") or ship.draught < 13.5:
            return True
        sim, fg = self.sim, self.sim.fg
        r = np.asarray(route, dtype=np.int64)
        t_rel = self._times(ship, r)
        cp = sim.places["cp"]["node"]
        near = np.hypot(fg.x[r] - fg.x[cp], fg.y[r] - fg.y[cp])
        at_cp = int(np.argmin(near))
        if near[at_cp] > 1500.0:
            return True                        # not by way of CP
        hw = sim.high_waters
        since = lambda eta: eta - hw[np.argmin(np.abs(hw - eta))]
        if ship.draught <= 14.5:
            return since(now + t_rel[at_cp]) <= 60.0
        names = {sim.lock_of_node[n].name: i for i, n in enumerate(r) if n in sim.lock_of_node}
        if "Kieldrecht" in names:
            return 0.0 <= since(now + t_rel[names["Kieldrecht"]]) <= 40.0
        if "Zandvliet" in names or "Berendrecht" in names:
            return abs(since(now + t_rel[at_cp])) <= 15.0
        return True

    def _times(self, ship, r):
        """Minutes from the start of a route to each of its cells: planning speed, speed limits, locks."""
        sim, fg = self.sim, self.sim.fg
        d = np.r_[0.0, np.cumsum(np.hypot(np.diff(fg.x[r]), np.diff(fg.y[r])))]
        leg = np.where(np.isin(fg.speed_zone[r], [fg.code("speed_zone", "sea")]), "sea", "river")
        v = np.array([ship.stw_kn(l, NR.planning_speed_kn) for l in ("sea", "river")])
        speed = np.fmin(np.where(leg == "sea", v[0], v[1]), fg.speed_limit_kn[r]) * KNOT_M_MIN
        return np.r_[0.0, np.cumsum(np.diff(d) / speed[1:])] + np.cumsum(np.isin(r, list(sim.lock_of_node))) * LOCK_TRANSIT_MIN

    def tide_ok(self, ship, route, now):
        """Every cell of the route deep enough at the time the ship gets there, leaving now and
        WINDOW_MIN later."""
        sim = self.sim
        fg = sim.fg
        r = np.asarray(route, dtype=np.int64)
        free_from = getattr(route, "free_from", None)
        if free_from is not None:              # the open-sea leg after the pilot station is not draught-limited
            r = r[:free_from]
        if r.size < 2:                         # already there
            return True
        t_rel = self._times(ship, r)
        water = ~sim.mover.special[r]
        need = np.where(sim.nontidal[r[water]], ship.need_dock_m, ship.need_m)
        for start in (now, now + WINDOW_MIN):
            level = sim.level_along(r[water], start + t_rel[water])
            if np.any(fg.depth_m[r[water]] + level < need):
                return False
        return True

    def destination_ok(self, ship):
        return self.sim.destination_free(ship)

    def _check(self, ship, now, book_ahead=True, quiet=False):
        """The clearance checks of a pilot ship, in order: (reason, route); reason None if it may go. A voyage
        that cannot be made at any tide removes the ship (reason "infeasible")."""
        sim = self.sim
        ship.infeasible = None
        route = sim.plan_route(ship, now)  # chooses the destination once (ship.target) and routes to it
        target = ship.target
        reason = None
        if route is None:
            reason = "destination" if target is None else "no_route"
            if target is not None and ship.at is not None and not sim.voyage_reachable(ship, ship.at, target) \
                    and not sim.unreachable_resolved(ship, now):
                ship.infeasible = "no route at high water"
        if ship.infeasible:
            ship.note(now, "infeasible", why=ship.infeasible)
            sim.finish(ship, now, "infeasible")
            return "infeasible", None
        if reason is None:
            ship.lock_voyage = sim.route_has_lock(route)
            gate = sim.weather_gate(ship, route, now)
            if gate:
                reason = "weather"
                if not quiet and ship.times.get("weather_gate") != gate:
                    ship.note(now, "weather_hold", gate=gate)
                    ship.times["weather_gate"] = gate
        if reason:
            pass
        elif not self.tide_ok(ship, route, now) or not self.window_ok(ship, route, now):
            reason = "tide"
        elif not sim.pilot_available(ship, route[0], now, route=route if book_ahead else None,
                                     first_zone=None if book_ahead else sim.first_pilot_zone(route)):
            reason = "pilot"
        elif not ship.departing and not self.destination_ok(ship):
            reason = "destination"
        return reason, route

    # ------------------------------------------------------------------ orders (Control)
    def _ship(self, x):
        """A Ship from a ShipView, a Ship or an id."""
        if isinstance(x, ShipView):
            return x._s
        if isinstance(x, str):
            return self.sim.by_id.get(x)
        return x

    def _reject(self, lever, ship, reason, **extra):
        self.rejected[lever] = self.rejected.get(lever, 0) + 1
        self.sim.events.append({"t": self.sim.t, "event": "vts_rejected", "lever": lever, "reason": reason,
                                "ship": getattr(ship, "id", None), **extra})
        return Result(False, reason)

    def _override(self, lever):
        self.overrides[lever] = self.overrides.get(lever, 0) + 1

    def _waiting(self, ship, lever):
        """None if this ship can be given a clearance order, else the refusal."""
        if ship is None or ship not in self.sim.ships:
            return self._reject(lever, ship, "not_in_area")
        if not getattr(ship, "vts_req", False):
            return self._reject(lever, ship, "not_waiting")
        if (ship.state.value == "to_anchorage" and ship.at is None) or getattr(ship, "anchor_until", 0.0) > self.sim.t:
            return self._reject(lever, ship, "not_ready")
        return None

    def c_clear(self, x, book_ahead=True):
        ship = self._ship(x)
        bad = self._waiting(ship, "clearance")
        if bad is not None:
            return bad
        ship.vts_tried = True
        now = self.sim.t
        if not ship.needs_pilot:
            return self._free_clear(ship, now)
        reason, route = self._check(ship, now, book_ahead=book_ahead)
        if reason == "infeasible":
            return Result(False, reason, removed=True)
        if reason:
            if ship.times.get("vts_wait_reason") != reason:
                ship.note(now, "vts_hold", reason=reason, at=ship.at, target=ship.target, state=ship.state.value)
                ship.times["vts_wait_reason"] = reason
            return Result(False, reason, route=tuple(route) if route is not None else None)
        self.withdraw(ship)
        self.cleared += 1
        ship.clear_order = self.cleared
        ship.times.pop("vts_wait_reason", None)
        ship.note(now, "vts_cleared")
        if not self.sim.clear(ship, route, now, book_ahead=book_ahead):
            return Result(False, "pilot_lost", route=tuple(route))   # lost a pilot this round: asked again
        return Result(True, route=tuple(route))

    def _free_clear(self, ship, now):
        """A ship without a pilot: the engine starts its voyage if its route and destination exist."""
        sim = self.sim
        kind = getattr(ship, "vts_kind", "go")
        start = {"unmoor": sim.free_unmoor, "hop": sim.free_hop, "resume": sim.free_resume}.get(kind, sim.free_go)
        started = start(ship, now)
        if ship.state.value == "exited":
            return Result(False, "infeasible", removed=True)
        if not started:
            reason = "destination" if ship.target is None else "no_route"
            return Result(False, reason, retry_at=getattr(ship, "retry_at", None))
        self.withdraw(ship)
        self.cleared_free += 1
        return Result(True)

    def c_check(self, x):
        ship = self._ship(x)
        bad = self._waiting(ship, "clearance")
        if bad is not None:
            return bad
        now = self.sim.t
        if not ship.needs_pilot:
            route = self.sim.plan_route(ship, now)
            if route is None:
                return Result(False, "destination" if ship.target is None else "no_route")
            return Result(True, route=tuple(route))
        reason, route = self._check(ship, now, quiet=True)
        return Result(reason is None, reason, route=tuple(route) if route is not None else None,
                      removed=reason == "infeasible")

    def c_recheck(self, x, at):
        ship = self._ship(x)
        if ship is None or not getattr(ship, "vts_req", False):
            return self._reject("clearance", ship, "not_waiting")
        if not is_number(at):
            return self._reject("clearance", ship, "bad_time")
        ship.vts_tried = True
        ship.vts_recheck = max(float(at), self.sim.t + self.sim.dt_min)
        return Result(True, value=ship.vts_recheck)

    def _at_station(self, ship, lever):
        bad = self._waiting(ship, lever)
        if bad is not None:
            return bad
        if ship.departing or ship.state.value != "wait_clearance" or not getattr(ship, "at_station", False):
            return self._reject(lever, ship, "not_at_station")
        return None

    def c_wait_at_sea(self, x, max_min):
        ship = self._ship(x)
        bad = self._at_station(ship, "anchorage")
        if bad is not None:
            return bad
        if not is_number(max_min) or max_min < 0:
            return self._reject("anchorage", ship, "bad_time")
        ship.vts_tried = True
        now = self.sim.t
        since = ship.times.setdefault("sea_wait_since", now)
        if now - since < max_min:
            if not ship.times.get("sea_wait_noted"):
                ship.times["sea_wait_noted"] = now
                ship.note(now, "waits_at_sea", reason=ship.times.get("vts_wait_reason"))
            return Result(True, value=now - since)
        return Result(False, "max_wait", value=now - since)

    def c_send_to_anchorage(self, x):
        ship = self._ship(x)
        bad = self._at_station(ship, "anchorage")
        if bad is not None:
            return bad
        ship.vts_tried = True
        # to an anchorage; none with room or reachable now: it stays and is sent at a later round
        sent = self.sim.send_to_anchorage(ship, self.sim.t)
        ship.at_station = not sent
        return Result(bool(sent), None if sent else "no_anchorage")

    def c_set_speed(self, x, kn):
        ship = self._ship(x)
        if ship is None or ship not in self.sim.ships:
            return self._reject("speed", ship, "not_in_area")
        if kn is None:
            ship.vts_speed_kn = None
            return Result(True)
        top = max(ShipView(ship, self.sim).max_speed_kn(leg) for leg in ("sea", "river"))
        if not is_number(kn) or kn < MIN_SPEED_KN or kn > top + 1e-9:
            return self._reject("speed", ship, "out_of_range", kn=kn, max_kn=round(top, 2))
        ship.vts_speed_kn = float(kn)
        return Result(True, value=float(kn))

    def c_set_rank(self, x, rank):
        ship = self._ship(x)
        if ship is None or ship not in self.sim.ships:
            return self._reject("rank", ship, "not_in_area")
        if not isinstance(rank, int) or isinstance(rank, bool) or rank < 0:
            return self._reject("rank", ship, "bad_rank")
        ship.clear_order = rank
        return Result(True, value=rank)

    def c_set_avoid_locks(self, x, names):
        ship = self._ship(x)
        if ship is None or ship not in self.sim.ships:
            return self._reject("lock_route", ship, "not_in_area")
        names = tuple(names or ())
        unknown = [n for n in names if n not in self.sim.locks]
        if unknown:
            return self._reject("lock_route", ship, "unknown_lock", locks=unknown)
        ship.avoid_locks = names
        return Result(True, value=names)

    def stretch_cells(self):
        """Regulated stretch name -> its cells (movement.py)."""
        if self._stretch_cells is None:
            out = {}
            for c, names in self.sim.mover.stretches.items():
                for n in names:
                    out.setdefault(n, set()).add(c)
            self._stretch_cells = {n: frozenset(c) for n, c in out.items()}
        return self._stretch_cells

    def c_restrict(self, kind, stretch=None, cells=None, direction=0, who=None, start=None, until=None, name=""):
        now = self.sim.t
        if kind not in RESTRICTION_KINDS:
            return self._reject("restriction", None, "bad_kind", kind=kind)
        if (stretch is None) == (cells is None):
            return self._reject("restriction", None, "stretch_or_cells")
        if stretch is not None:
            got = self.stretch_cells().get(stretch)
            if got is None:
                return self._reject("restriction", None, "unknown_stretch", stretch=stretch)
            cells = got
        try:
            cells = frozenset(int(c) for c in cells)
        except (TypeError, ValueError):
            return self._reject("restriction", None, "bad_cells")
        if not cells or any(c < 0 or c >= self.sim.fg.n for c in cells):
            return self._reject("restriction", None, "bad_cells")
        if direction not in (0, 1, -1) or (kind == "one_way" and direction == 0):
            return self._reject("restriction", None, "bad_direction")
        start = now if start is None else start
        if not is_number(start) or until is None or not is_number(until) or until <= start \
                or until > now + RESTRICTION_MAX_MIN or start < now - 1e-9:
            return self._reject("restriction", None, "bad_time")
        allowed = {"min_loa", "min_beam", "min_draught", "classes", "sea_going", "needs_pilot"}
        if not isinstance(who, dict) or set(who) - allowed:
            return self._reject("restriction", None, "bad_who")
        r = Restriction(self._next_restriction, kind, cells, float(start), float(until), int(direction), dict(who),
                        name or (stretch or ""))
        self._next_restriction += 1
        self.restrictions[r.id] = r
        self.sim.events.append({"t": now, "event": "vts_restriction", "id": r.id, "kind": kind, "name": r.name,
                                "cells": len(cells), "start": r.start, "until": r.until, "direction": r.direction})
        return Result(True, value=r.id)

    def c_lift(self, rid):
        r = self.restrictions.get(rid)
        if r is None:
            return self._reject("restriction", None, "unknown_restriction", id=rid)
        r.until = min(r.until, self.sim.t)
        self.sim.events.append({"t": self.sim.t, "event": "vts_restriction_lifted", "id": rid})
        return Result(True)

    def active_restrictions(self, now):
        if not self.restrictions:
            return []
        for rid in [i for i, r in self.restrictions.items() if r.until <= now]:
            del self.restrictions[rid]
        return [r for r in self.restrictions.values() if r.active(now)]

    def c_note(self, x, event, **extra):
        ship = self._ship(x) if x is not None else None
        if ship is not None:
            ship.note(self.sim.t, str(event), **extra)
        else:
            self.sim.events.append({"t": self.sim.t, "event": str(event), **extra})
        return Result(True)

    # ------------------------------------------------------------------ choices offered to the strategy
    def _has(self, hook):
        return hook in self._hooks

    def arrival_delay(self, ship, default):
        if not self._has("arrival_delay"):
            return default
        got = self.strategy.arrival_delay(ShipView(ship, self.sim), default)
        if got is None:
            return default
        if not is_number(got) or got < 0 or got > ARRIVAL_DELAY_MAX_MIN:
            self._reject("arrival_time", ship, "out_of_range", minutes=got)
            return default
        if abs(got - default) > 1e-9:
            self._override("arrival_time")
        return float(got)

    def choose_berth(self, ship, options, default):
        if not self._has("choose_berth"):
            return default
        got = self.strategy.choose_berth(ShipView(ship, self.sim), list(options), default)
        if got is None:
            return default
        if got not in options:
            self._reject("berth", ship, "not_offered", berth=got)
            return default
        if got != default:
            self._override("berth")
        return got

    def choose_quay_position(self, ship, T, default):
        if not self._has("choose_quay_position"):
            return default
        free = T.free_intervals(self.sim.quay_eta(ship))
        ok = T.suitable_intervals(ship.draught, ship.sea_going)
        free = [(max(a, c), min(b, d)) for a, b in free for c, d in ok if min(b, d) > max(a, c)]
        options = [(a, b) for a, b in free if b - a >= ship.loa]
        got = self.strategy.choose_quay_position(ShipView(ship, self.sim), T.name, options, default)
        if got is None:
            return default
        if not is_number(got) or not any(a - 1e-6 <= got and got + ship.loa <= b + 1e-6 for a, b in options):
            self._reject("quay_position", ship, "not_offered", s0=got)
            return default
        if abs(got - default) > 1e-6:
            self._override("quay_position")
        return float(got)

    def anchorage_order(self, ship, pool):
        """pool: Anchorage objects in the default order; returns the ones to try, in order."""
        if not self._has("anchorage_order"):
            return pool
        by_name = {a.name: a for a in pool}
        got = self.strategy.anchorage_order(ShipView(ship, self.sim), [a.name for a in pool])
        if got is None:
            return pool
        got = list(got)
        if any(n not in by_name for n in got) or len(set(got)) != len(got):
            self._reject("anchorage", ship, "not_offered", anchorages=got)
            return pool
        if got != [a.name for a in pool]:
            self._override("anchorage")
        return [by_name[n] for n in got]

    def exit_order(self, ship, options):
        if not self._has("exit_order"):
            return options
        got = self.strategy.exit_order(ShipView(ship, self.sim), list(options))
        if got is None:
            return options
        got = list(got)
        if any(e not in options for e in got) or len(set(got)) != len(got):
            self._reject("exit", ship, "not_offered", exits=got)
            return options
        out = got + [e for e in options if e not in got]
        if out != list(options):
            self._override("exit")
        return out

    def avoid_locks(self, ship, default):
        if not self._has("avoid_locks"):
            return default
        got = self.strategy.avoid_locks(ShipView(ship, self.sim), tuple(default))
        if got is None:
            return default
        got = tuple(got)
        if any(n not in self.sim.locks for n in got):
            self._reject("lock_route", ship, "unknown_lock", locks=list(got))
            return default
        if set(got) != set(default):
            self._override("lock_route")
        return got

    def pilot_chooser(self, ship, zone):
        """A chooser for PilotPool.take, or None for its own order."""
        if not self._has("assign_pilots"):
            return None

        def choose(free, n):
            ids = [p.id for p in free]
            got = self.strategy.assign_pilots(ShipView(ship, self.sim), zone, n, ids, ids[:n])
            if got is None:
                return free[:n]
            got = list(got)
            if len(got) != n or len(set(got)) != n or any(i not in ids for i in got):
                self._reject("pilots", ship, "not_offered", pilots=got)
                return free[:n]
            if got != ids[:n]:
                self._override("pilots")
            by = {p.id: p for p in free}
            return [by[i] for i in got]
        return choose

    def tug_chooser(self, ship):
        """A chooser for TugPool.request, or None for the nearest."""
        if not self._has("assign_tugs"):
            return None

        def choose(free, n):
            ids = [t.id for t in free]
            got = self.strategy.assign_tugs(ShipView(ship, self.sim), n, ids, ids[:n])
            if got is None:
                return free[:n]
            got = list(got)
            if len(got) != n or len(set(got)) != n or any(i not in ids for i in got):
                self._reject("tugs", ship, "not_offered", tugs=got)
                return free[:n]
            if got != ids[:n]:
                self._override("tugs")
            by = {t.id: t for t in free}
            return [by[i] for i in got]
        return choose

    def lock_priority(self, ship, lock, default):
        if not self._has("lock_priority"):
            return default
        got = self.strategy.lock_priority(ShipView(ship, self.sim), lock.name, default)
        if got is None:
            return default
        if got not in LOCK_PRIORITIES:
            self._reject("lock_priority", ship, "out_of_range", priority=got)
            return default
        if got != default:
            self._override("lock_priority")
        return got

    # the lock planner: locks.Lock calls these (Lock.planner)
    def chamber(self, lock, request, options, default):
        if not self._has("choose_chamber"):
            return default
        ship = self.sim.by_id.get(request.ship_id)
        if ship is None:
            return default
        names = [c.name for c in options]
        got = self.strategy.choose_chamber(ShipView(ship, self.sim), lock.name, names, default.name)
        if got is None:
            return default
        if got not in names:
            self._reject("lock_chamber", ship, "not_offered", chamber=got, lock=lock.name)
            return default
        if got != default.name:
            self._override("lock_chamber")
        return options[names.index(got)]

    def keep_open(self, lock, c, t, default):
        if not self._has("keep_lock_open"):
            return default
        got = self.strategy.keep_lock_open(lock.name, c.name, bool(default))
        key = (lock.name, c.name)
        if got is None or bool(got) == bool(default):
            self._open_against.pop(key, None)
            return default
        if got and not default:
            since = self._open_against.setdefault(key, t)
            if t - since > KEEP_OPEN_MAX_MIN:
                if since >= 0:
                    self._reject("lockage", None, "kept_open_too_long", lock=lock.name, chamber=c.name)
                    self._open_against[key] = -math.inf      # refused once for this spell
                return default
        else:
            self._open_against.pop(key, None)
        self._override("lockage")
        return bool(got)

    # ------------------------------------------------------------------ output
    def summary(self):
        s = self.strategy
        return {"strategy": s.name, "description": s.description, "levers": list(s.levers),
                "options": {k: (v if isinstance(v, (int, float, str, bool)) or v is None else str(v))
                            for k, v in (s.options or {}).items()},
                "hooks": sorted(h for h in self._hooks if h in lever_hooks()),
                "cleared": self.cleared, "cleared_without_pilot": self.cleared_free,
                "rejected": dict(sorted(self.rejected.items())), "overrides": dict(sorted(self.overrides.items())),
                "restrictions_made": self._next_restriction - 1}
