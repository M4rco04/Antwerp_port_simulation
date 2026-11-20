"""The baseline VTS: first come first served, the VTS the model was calibrated with (MODEL.md §9).

Ships that need a pilot are cleared in the planning round, every 15 min, in order of (priority class, request
time): 0 a ship in distress, 1 a tide-dependent ship (T > 13.10 m), 3 the others. A ship is cleared when it passes
the checks (route, weather, tide, pilots, destination). An arrival at the pilot station that is not cleared goes
to an anchorage; a container ship with a berth time waiting for its quay or its tide first waits off the station,
in the area, for up to 18 h (engine.CONTAINER_SEA_WAIT_MAX_MIN), then anchors like the others.

Ships without a pilot are cleared the moment they ask, when their route and destination exist; one that cannot go
is tried again after a back-off (30 min, doubling to 8 h), as the model always did.

Every choice the engine offers (berths, chambers, tugs, ...) is left to its default. This strategy is the reference
every other one is compared with: on one seed it gives the same run as the model before the strategy API.
"""

from __future__ import annotations

from vts_api import Strategy


class Baseline(Strategy):
    name = "baseline"
    description = "first come first served (distress, tide-dependent, then by request time); defaults elsewhere"
    levers = ("clearance", "anchorage")

    def on_request(self, ship):
        if ship.needs_pilot:
            return                                     # cleared in the planning round
        result = self.control.clear(ship)
        if not result.ok and not result.removed and result.retry_at is not None:
            self.control.recheck(ship, result.retry_at)

    def on_tick(self, now):
        view, control = self.view, self.control
        for ship in sorted((s for s in view.requests() if s.needs_pilot), key=view.default_priority):
            if not ship.ready:
                continue                               # under way to its anchorage, or lying out its anchor stay
            result = control.clear(ship)
            if result.ok or result.removed or result.reason == "pilot_lost":
                continue
            self.not_cleared(ship, result)

    def not_cleared(self, ship, result):
        """An arrival at the pilot station that is not cleared: off the station for a while (a container ship
        with a berth time waiting for its quay or its tide), else to an anchorage; departures wait at the berth."""
        if ship.departing or ship.state != "wait_clearance" or not ship.at_station:
            return
        if ship.cls == "container" and ship.terminal and result.reason in ("destination", "tide"):
            if self.control.wait_at_sea(ship, self.view.container_sea_wait_max_min).ok:
                return                                 # loses the time at sea, not at anchor
        self.control.send_to_anchorage(ship)
