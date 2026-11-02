"""The VTS, kept as simple as possible for now (PLAN.md §4, §8). No reservations, no
optimisation and no game theory yet.

Ships that need a pilot ask for clearance: arrivals at the pilot station or at anchor, departures
from a berth or from a port. Every PLAN_EVERY steps (15 min) the VTS walks the requests in order
(distress, then tide-dependent ships, then first come first served by request time) and clears a
ship when all of these hold:

    route        a route exists for its draught (+ UKC), size and the locks it needs
    tide         the whole route stays deep enough when it leaves now AND 60 min later, sailing at
                 its planning speed (regs §8: the window at the start must be at least 60 min)
    weather      the gates of regs §9 (agents/weather_gates.py): visibility, wind, storm
    pilot        a pilot (two for the largest ships) is free for its first zone, and a pilot boat
                 for a boarding at sea / at Vlissingen
    destination  its terminal has quay room, or its berth is free

An arrival at the pilot station that is not cleared at once goes to an anchorage
(anchorages.choose_anchorage, regs §11) and waits there. Ships that need no pilot (inland craft,
small ships) do not ask: they sail when their route exists.
"""

from __future__ import annotations

import numpy as np

import navigation_rules as NR

PLAN_EVERY = 3
WINDOW_MIN = 60.0
KNOT_M_MIN = 1852.0 / 60.0


class SimpleVTS:
    def __init__(self, sim):
        self.sim = sim
        self.requests = []                     # ships waiting for clearance
        self.cleared = 0

    def request(self, ship, now):
        if ship.request_t is None:
            ship.request_t = now
        if ship not in self.requests:
            self.requests.append(ship)
            ship.note(now, "vts_request", departing=ship.departing)

    def withdraw(self, ship):
        if ship in self.requests:
            self.requests.remove(ship)

    # ------------------------------------------------------------------ checks
    def tide_ok(self, ship, route, now):
        """Every cell of the route deep enough at the time the ship gets there, leaving now and
        WINDOW_MIN later."""
        sim = self.sim
        fg = sim.fg
        r = np.asarray(route, dtype=np.int64)
        if r.size < 2:                         # already there
            return True
        d = np.r_[0.0, np.cumsum(np.hypot(np.diff(fg.x[r]), np.diff(fg.y[r])))]
        leg = np.where(np.isin(fg.speed_zone[r], [fg.code("speed_zone", "sea")]), "sea", "river")
        v = np.array([ship.stw_kn(l, NR.planning_speed_kn) for l in ("sea", "river")])
        speed = np.where(leg == "sea", v[0], v[1]) * KNOT_M_MIN
        t_rel = np.r_[0.0, np.cumsum(np.diff(d) / speed[1:])]
        water = ~sim.mover.special[r]
        for start in (now, now + WINDOW_MIN):
            level = sim.level_along(r[water], start + t_rel[water])
            if np.any(fg.depth_m[r[water]] + level < ship.need_m):
                return False
        return True

    def destination_ok(self, ship):
        return self.sim.destination_free(ship)

    # ------------------------------------------------------------------ planning
    def plan(self, now):
        sim = self.sim
        for ship in sorted(self.requests, key=lambda s: s.vts_priority()):
            ship.infeasible = None
            route = sim.plan_route(ship, now)
            reason = None
            if route is None:
                target = sim.choose_target(ship)
                reason = "destination" if target is None else "no_route"
                if target is not None and ship.at is not None and not sim.reachable_between(ship.at, target, ship):
                    ship.infeasible = "no route at high water"
            if ship.infeasible:
                ship.note(now, "infeasible", why=ship.infeasible)
                sim.finish(ship, now, "infeasible")
                continue
            if reason is None:
                ship.lock_voyage = sim.route_has_lock(route)
                gate = sim.weather_gate(ship, route, now)
                if gate:
                    reason = "weather"
                    if ship.times.get("weather_gate") != gate:
                        ship.note(now, "weather_hold", gate=gate)
                        ship.times["weather_gate"] = gate
            if reason:
                pass
            elif not self.tide_ok(ship, route, now):
                reason = "tide"
            elif not sim.pilot_available(ship, route[0], now):
                reason = "pilot"
            elif not ship.departing and not self.destination_ok(ship):
                reason = "destination"
            if reason:
                if ship.times.get("vts_wait_reason") != reason:
                    ship.note(now, "vts_hold", reason=reason, at=ship.at, target=ship.target, state=ship.state.value)
                    ship.times["vts_wait_reason"] = reason
                if not ship.departing and ship.state.value == "wait_clearance" and getattr(ship, "at_station", False):
                    ship.at_station = False
                    sim.send_to_anchorage(ship, now)
                continue
            self.requests.remove(ship)
            self.cleared += 1
            ship.clear_order = self.cleared
            ship.times.pop("vts_wait_reason", None)
            ship.note(now, "vts_cleared")
            sim.clear(ship, route, now)
