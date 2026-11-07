"""The VTS, kept as simple as possible for now (PLAN.md §4, §8). No reservations, no
optimisation and no game theory yet.

Ships that need a pilot ask for clearance: arrivals at the pilot station or at anchor, departures
from a berth or from a port. Every PLAN_EVERY steps (15 min) the VTS walks the requests in order
(distress, then tide-dependent ships, then first come first served by request time) and clears a
ship when all of these hold:

    route        a route exists for its draught (+ UKC), size and the locks it needs (engine.voyage_route:
                 valid at the run's lowest water if possible, else the deep channel, which needs the tide;
                 to a sea exit only as far as the pilot station, then open sea)
    tide         the arrival windows of bulk carriers and tankers at CP (regs §8.6), and the whole route (up to
                 the pilot station on the way out) stays deep enough when it
                 leaves now AND 60 min later, sailing at its planning speed, the speed limits in the docks
                 and the time of a lock passage (regs §8: the window at the start must be at least 60 min)
    weather      the gates of regs §9 (agents/weather_gates.py): visibility, wind, storm
    pilot        a pilot (two for the largest ships) is free for its first pilot stretch, pilots can
                 be booked for every later stretch of the voyage for when it gets there (never for a
                 time before now), and a pilot boat for a boarding at sea / at Vlissingen
    destination  its terminal has quay room, or its berth is free (the one the route goes to: the
                 destination is chosen once per round)

An arrival at the pilot station that is not cleared at once goes to an anchorage
(anchorages.choose_anchorage, regs §11) and waits there; if none has room or can be reached it
waits at the station and is sent at a later round. A ship under way to its anchorage is skipped
until it is there. Ships that need no pilot (inland craft, small ships) do not ask: they sail when
their route exists.
"""

from __future__ import annotations

import numpy as np

import navigation_rules as NR

PLAN_EVERY = 3
WINDOW_MIN = 60.0
LOCK_TRANSIT_MIN = 60.0
KNOT_M_MIN = 1852.0 / 60.0


class SimpleVTS:
    def __init__(self, sim):
        self.sim = sim
        self.requests = []                     # ships waiting for clearance
        self.cleared = 0

    def request(self, ship, now):
        # the time of this voyage's request: a departure is queued from when it is ready to leave, not
        # from when it asked to come in (that put every departure ahead of every waiting arrival); a ship
        # put back after losing its pilot keeps its place
        if ship.request_t is None or getattr(ship, "request_leg", None) != ship.departing:
            ship.request_t = now
            ship.request_leg = ship.departing
        if ship not in self.requests:
            self.requests.append(ship)
            ship.note(now, "vts_request", departing=ship.departing)

    def withdraw(self, ship):
        if ship in self.requests:
            self.requests.remove(ship)

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

    # ------------------------------------------------------------------ planning
    def plan(self, now):
        sim = self.sim
        for ship in sorted(self.requests, key=lambda s: s.vts_priority()):
            if ship.state.value == "to_anchorage":
                continue                       # under way to its anchorage (no place to start from): asked once there
            if getattr(ship, "anchor_until", 0.0) > now:
                continue                       # entered the area at anchor: it lies there for its stay first
            ship.infeasible = None
            route = sim.plan_route(ship, now)  # chooses the destination once (ship.target) and routes to it
            target = ship.target
            reason = None
            if route is None:
                reason = "destination" if target is None else "no_route"
                if target is not None and ship.at is not None and not sim.voyage_reachable(ship, ship.at, target):
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
            elif not self.tide_ok(ship, route, now) or not self.window_ok(ship, route, now):
                reason = "tide"
            elif not sim.pilot_available(ship, route[0], now, route=route):
                reason = "pilot"
            elif not ship.departing and not self.destination_ok(ship):
                reason = "destination"
            if reason:
                if ship.times.get("vts_wait_reason") != reason:
                    ship.note(now, "vts_hold", reason=reason, at=ship.at, target=ship.target, state=ship.state.value)
                    ship.times["vts_wait_reason"] = reason
                if not ship.departing and ship.state.value == "wait_clearance" and getattr(ship, "at_station", False):
                    # to an anchorage; none with room or reachable now: it stays and is sent at a later round
                    # (it used to be left at the station for good, holding its place in the queue)
                    ship.at_station = not sim.send_to_anchorage(ship, now)
                continue
            self.requests.remove(ship)
            self.cleared += 1
            ship.clear_order = self.cleared
            ship.times.pop("vts_wait_reason", None)
            ship.note(now, "vts_cleared")
            sim.clear(ship, route, now)
