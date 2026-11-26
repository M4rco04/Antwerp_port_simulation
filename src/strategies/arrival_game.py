"""Strategy A: arrival-time game at the pilot station.

Select ``service_rule="A0"`` for first-come-first-served, ``"A1"`` for
planned-berth priority, or ``"A2"`` for pilot-station clearance windows.
``early_arrival_hours`` is the default choice of earlier entry relative to
the model's JIT entry; ``ship_arrival_hours`` overrides it by ship ID.

A2 assigns windows at the area boundary using the model's estimated approach
route, not advance announcements. Capacity is per pilot station. Windows
limit ordinary scheduled pilot ships; distress and tide-dependent ships
always retain baseline priority and are exempt from the window capacity.
"""

from __future__ import annotations

import math

from strategies.baseline import Baseline
from vts_api import ARRIVAL_DELAY_MAX_MIN


class ArrivalGame(Baseline):
    name = "arrival_game"
    description = "arrival-time game: FCFS (A0), berth priority (A1), or windows (A2)"
    levers = ("clearance", "anchorage", "arrival_time")

    def start(self):
        self.service_rule = str(self.options.get("service_rule", "A1")).upper()
        if self.service_rule not in {"A0", "A1", "A2"}:
            raise ValueError("service_rule must be 'A0', 'A1' or 'A2'")
        self.early_arrival_min = self._lead_minutes(self.options.get("early_arrival_hours", 0.0))
        overrides = self.options.get("ship_arrival_hours", {})
        if not isinstance(overrides, dict) or any(not isinstance(key, str) or not key for key in overrides):
            raise ValueError("ship_arrival_hours must map nonempty ship IDs to hours")
        self.ship_arrival_min = {key: self._lead_minutes(value) for key, value in overrides.items()}
        try:
            self.window_min = float(self.options.get("window_min", 60.0))
            self.approach_buffer_min = float(self.options.get("approach_buffer_min", 0.0))
            capacity = self.options.get("window_capacity", 1)
            self.window_capacity = int(capacity)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("invalid A2 window parameters") from exc
        if (not math.isfinite(self.window_min) or self.window_min <= 0
                or not math.isfinite(self.approach_buffer_min) or self.approach_buffer_min < 0
                or isinstance(capacity, bool) or self.window_capacity != capacity or self.window_capacity < 1):
            raise ValueError("window_min must be positive, approach_buffer_min nonnegative and window_capacity a positive integer")
        if "approach_min" in self.options:
            raise ValueError("approach_min is no longer supported: use route estimates and approach_buffer_min")
        self.record_approach = self.options.get("record_approach_estimates", False)
        if not isinstance(self.record_approach, bool):
            raise ValueError("record_approach_estimates must be true or false")
        if self.service_rule == "A2" and (self.window_min < self.view.round_min
                                           or self.window_min % self.view.round_min != 0):
            raise ValueError("window_min must be a positive multiple of the VTS planning round")
        self.windows = {}
        self.reservations = {}

    @staticmethod
    def _lead_minutes(value):
        try:
            minutes = float(value) * 60.0
        except (TypeError, ValueError) as exc:
            raise ValueError("arrival lead must be a number from 0 to 48 hours") from exc
        if not math.isfinite(minutes) or not 0.0 <= minutes <= 48 * 60.0:
            raise ValueError("arrival lead must be a number from 0 to 48 hours")
        return minutes

    def _reserve_window(self, ship, earliest, station):
        index = max(0, math.floor(earliest / self.window_min))
        while len(self.reservations.get((station, index), ())) >= self.window_capacity:
            index += 1
        self.reservations.setdefault((station, index), set()).add(ship.id)
        self.windows[ship.id] = (station, index)
        self.control.note(ship, "arrival_window", start=index * self.window_min,
                          end=(index + 1) * self.window_min, station=station)
        return index

    def on_tick(self, now):
        view, control = self.view, self.control
        requests = (s for s in view.requests() if s.needs_pilot)
        if self.service_rule in {"A0", "A2"}:
            priority = view.default_priority
        else:
            priority = self._planned_berth_priority

        for ship in sorted(requests, key=priority):
            if not ship.ready:
                continue
            if (self.service_rule == "A2" and not ship.departing and ship.id in self.windows
                    and not ship.distress and not ship.tide_dependent):
                station, index = self.windows[ship.id]
                if ship.request_t is not None and ship.request_t >= (index + 1) * self.window_min:
                    self.reservations[(station, index)].discard(ship.id)
                    index = self._reserve_window(ship, now, station)
                if now < index * self.window_min:
                    continue
            result = control.clear(ship)
            if result.ok or result.removed or result.reason == "pilot_lost":
                if result.ok or result.removed:
                    self.windows.pop(ship.id, None)
                continue
            self.not_cleared(ship, result)

    def _planned_berth_priority(self, ship):
        base_priority, request_time = self.view.default_priority(ship)
        if base_priority < 3:
            return base_priority, 0, request_time, request_time, ship.id
        berth_time = None if ship.departing else ship.scheduled_berth_min
        if berth_time is None:
            return base_priority, 1, request_time, request_time, ship.id
        return base_priority, 0, float(berth_time), request_time, ship.id

    def arrival_delay(self, ship, default_min):
        if ship.cls != "container" or ship.scheduled_berth_min is None or ship.terminal is None:
            return None
        lead = self.ship_arrival_min.get(ship.id, self.early_arrival_min)
        if ship.needs_pilot and (self.service_rule == "A2" or self.record_approach):
            estimate = self.view.approach_estimate(ship)
            if estimate is None:
                self.control.note(ship, "approach_estimate_skipped", reason="no_sea_approach")
            else:
                self.control.note(ship, "approach_estimate", source=estimate["source"],
                                  station=estimate["station"], approach_min=estimate["minutes"],
                                  expected_entry=self.view.now + max(float(default_min) - lead, 0.0))
                if self.service_rule == "A2" and not ship.distress and not ship.tide_dependent:
                    self._reserve_window(ship, self.view.now + default_min + estimate["minutes"]
                                         + self.approach_buffer_min, estimate["station"])
        if lead == 0:
            return None
        return min(max(float(default_min) - lead, 0.0), ARRIVAL_DELAY_MAX_MIN)
