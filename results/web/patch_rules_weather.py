def patch(path, pairs):
    s = open(path, encoding="utf-8").read()
    for a, b in pairs:
        assert a in s, (path, a[:70])
        s = s.replace(a, b, 1)
    open(path, "w", encoding="utf-8").write(s)


# ---------------------------------------------------------------- ship: two pilots, visibility flag
patch("src/agents/ship.py", [
('''    def pilots_needed(self, zone):
        """Two river pilots for LOA >= 340 m or B >= 51 m (regs §8.8)."""
        return 2 if zone == "river" and (self.loa >= 340 or self.beam >= 51) else 1''',
 '''    def pilots_needed(self, zone):
        """Two river pilots (at least one of the highest category) for LOA >= 340 m or B >= 51 m,
        and for LOA >= 300 m or B >= 45 m on a voyage to or from the locks (regs §8.8)."""
        if zone != "river":
            return 1
        if self.loa >= 340 or self.beam >= 51:
            return 2
        if self.lock_voyage and (self.loa >= 300 or self.beam >= 45):
            return 2
        return 1'''),
('''    @property
    def tide_dependent(self):''',
 '''    @property
    def marginal_visibility(self):
        """Ships that need 1000 m visibility at the start of the voyage (JA22, GB24)."""
        return self.sea_going and (self.loa >= 300 or self.beam >= 45 or self.draught >= 12.5)

    @property
    def tide_dependent(self):'''),
('''    reroutes: int = 0''', '''    reroutes: int = 0
    lock_voyage: bool = False                      # the voyage it is cleared for passes a lock'''),
])

# ---------------------------------------------------------------- VTS: weather gates, lock voyages
patch("src/agents/vts.py", [
('''            if reason:
                pass
            elif not self.tide_ok(ship, route, now):''',
 '''            if reason is None:
                ship.lock_voyage = sim.route_has_lock(route)
                gate = sim.weather_gate(ship, route, now)
                if gate:
                    reason = "weather"
                    if ship.times.get("weather_gate") != gate:
                        ship.note(now, "weather_hold", gate=gate)
                        ship.times["weather_gate"] = gate
            if reason:
                pass
            elif not self.tide_ok(ship, route, now):'''),
('''    pilot        a pilot (two for the largest ships) is free for its first zone, and a pilot boat''',
 '''    weather      the gates of regs §9 (agents/weather_gates.py): visibility, wind, storm
    pilot        a pilot (two for the largest ships) is free for its first zone, and a pilot boat'''),
])

# ---------------------------------------------------------------- engine: weather
patch("src/sim/engine.py", [
('''        self.L = self.tide.levels(times)[fg.labels["gauges"]].to_numpy()''',
 '''        hours = int(len(times) * DT_MIN / 60) + 2
        self.weather = Weather.generate(self.start, hours, self.rng, mode=weather_mode)
        # water levels: tide + the surge the weather drives
        self.L = self.tide.levels(times, weather=self.weather.surge_input)[fg.labels["gauges"]].to_numpy()'''),
('''    def __init__(self, start="2026-10-21 00:00", days=7.0, seed=1, delays=True, warmup_days=2.0, background=True):''',
 '''    def __init__(self, start="2026-10-21 00:00", days=7.0, seed=1, delays=True, warmup_days=2.0, background=True,
                 weather_mode="bootstrap"):'''),
('''from vts import PLAN_EVERY, SimpleVTS                     # noqa: E402''',
 '''from vts import PLAN_EVERY, SimpleVTS                     # noqa: E402
from weather import Weather                               # noqa: E402
import weather_gates as WG                                # noqa: E402'''),
# helpers used by the VTS
('''    def approach_route(self, start, station):''',
 '''    def now_ts(self, minutes=None):
        return self.start + pd.Timedelta(minutes=self.t if minutes is None else minutes)

    def route_has_lock(self, route):
        return any(n in self.lock_of_node for n in route)

    def weather_gate(self, ship, route, now):
        """Reason the weather keeps this ship from starting (regs §9), or None."""
        fg = self.fg
        r = np.asarray(route, dtype=np.int64)
        length = float(np.hypot(np.diff(fg.x[r]), np.diff(fg.y[r])).sum()) if len(r) > 1 else 0.0
        eta = length / (ship.stw_kn("river", NR.planning_speed_kn) * 1852.0 / 60.0)
        info = {"via_lock": self.route_has_lock(route),
                "tidal_terminal": ship.terminal is not None,
                "river": bool(np.any(fg.speed_zone[r] == fg.code("speed_zone", "river"))),
                "eta_min": eta,
                "boarding_at_sea": not ship.departing and self.pilot_zone(route[0]) == "sea" and ship.needs_pilot}
        return WG.start_gate(ship, self.weather, self.now_ts(now), info)

    def approach_route(self, start, station):'''),
('''import port_infrastructure as PI                          # noqa: E402''',
 '''import navigation_rules as NR                             # noqa: E402
import port_infrastructure as PI                          # noqa: E402'''),
# extra tug in strong wind
('''        ship.needs_tugs = ship.tugs_needed(departing=True)''',
 '''        ship.needs_tugs = ship.tugs_needed(departing=True) + WG.extra_tugs(ship, self.weather, self.now_ts(now))'''),
('''        ship.needs_tugs = ship.tugs_needed()''',
 '''        ship.needs_tugs = ship.tugs_needed() + WG.extra_tugs(ship, self.weather, self.now_ts(now))'''),
# cranes stop in strong gusts
('''            elif st == State.AT_BERTH:
                if ship.timer is None:                 # container waiting for cranes
                    self._start_handling(ship, now)
                    continue
                ship.timer -= DT_MIN''',
 '''            elif st == State.AT_BERTH:
                if ship.timer is None:                 # container waiting for cranes
                    self._start_handling(ship, now)
                    continue
                if ship.terminal and cranes_stopped:   # STS cranes stopped by the wind
                    continue
                ship.timer -= DT_MIN'''),
('''    def _timers(self, now):
        rising, after_hw = self.tide_phase()''',
 '''    def _timers(self, now):
        rising, after_hw = self.tide_phase()
        cranes_stopped = WG.cranes_stopped(self.weather, self.now_ts(now))'''),
# log the weather
('''               "tugs_busy": self.tugs.busy(now),''',
 '''               "wind_bft": int(self.weather.at(self.now_ts(now)).bft),
               "visibility_m": float(self.weather.at(self.now_ts(now)).visibility_m),
               "tugs_busy": self.tugs.busy(now),'''),
# CLI
('''    parser.add_argument("--no-background", action="store_true")''',
 '''    parser.add_argument("--no-background", action="store_true")
    parser.add_argument("--weather", choices=("bootstrap", "replay"), default="bootstrap",
                        help="weather: real days of the same season drawn at random, or the observed dates")'''),
('''    sim = Simulation(args.start, args.days, args.seed, not args.no_delays, args.warmup, not args.no_background)''',
 '''    sim = Simulation(args.start, args.days, args.seed, not args.no_delays, args.warmup, not args.no_background,
                     weather_mode=args.weather)'''),
# the lock voyage for pilots taken at clearance (also set by the VTS)
('''    def clear(self, ship, route, now):
        """The VTS cleared the ship: reserve, take the pilot(s), board / unmoor, then sail."""''',
 '''    def clear(self, ship, route, now):
        """The VTS cleared the ship: reserve, take the pilot(s), board / unmoor, then sail."""
        ship.lock_voyage = self.route_has_lock(route)'''),
])
print("patched")
