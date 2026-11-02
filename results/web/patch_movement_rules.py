def patch(path, pairs):
    s = open(path, encoding="utf-8").read()
    for a, b in pairs:
        assert a in s, (path, a[:70])
        s = s.replace(a, b, 1)
    open(path, "w", encoding="utf-8").write(s)


patch("src/agents/movement.py", [
('''import navigation_rules as NR
from clearance import lane_width''',
 '''import navigation_rules as NR
import weather_gates as WG
from clearance import lane_width'''),
('''WAITING = ("lock_queue", "mooring", "wait_pilot", "pilot_change", "at_berth", "unmooring")''',
 '''WAITING = ("lock_queue", "mooring", "wait_pilot", "pilot_change", "at_berth", "unmooring")
UNDER_WAY = ("sailing", "to_station", "to_anchorage")
OVERTAKE_SAME_DIRECTION = 0.7          # cos of the angle between two headings for "same way"
OVERTAKE_LATERAL_M = 400.0             # alongside: closer than this sideways
STARBOARD_AVOID_M = 1500.0             # a detour to overtake keeps off this much of the other's starboard side'''),
('''        self.stretches = {}
        for n, d in sim.graph.nodes(data=True):
            if d.get("stretches"):
                self.stretches[n] = tuple(d["stretches"])''',
 '''        self.stretches = {}
        self.main_waterway = np.zeros(fg.n, dtype=bool)
        for n, d in sim.graph.nodes(data=True):
            if d.get("stretches"):
                self.stretches[n] = tuple(d["stretches"])
            if d.get("main_waterway"):
                self.main_waterway[n] = True
        self.fairway = fg.fairway.astype(bool)
        self.vis_cap = None
        self.denied = set()'''),
# speed in restricted visibility
('''        if ship.remaining_m < 1500:                     # last approach to a berth / lock: slow
            sog = min(sog, sim.dock_speed_kn)''',
 '''        if ship.remaining_m < 1500:                     # last approach to a berth / lock: slow
            sog = min(sog, sim.dock_speed_kn)
        if self.vis_cap is not None:                    # restricted visibility (COLREG 19)
            sog = min(sog, self.vis_cap)'''),
# overtaking
('''    def blocker(self, ship):''', '''    def _heading(self, line):
        d = line[-1] - line[0]
        n = float(np.hypot(*d))
        return d / n if n > 0 else None

    def overtaking_violation(self, ship, new_head):
        """A ship sailing the same way that this move would overtake against the rules: an
        overtaking ban in a regulated stretch (regs §6), or on its starboard side where the local rule
        says port (regs §5.4: river, docks, canals). Returns (other, why) or None."""
        if new_head <= ship.head + 1e-6:
            return None
        p_old, p_new = self._xy(ship, [ship.head])[0], self._xy(ship, [new_head])[0]
        d = p_new - p_old
        dist = float(np.hypot(*d))
        if dist == 0:
            return None
        u = d / dist
        i_new = int(np.searchsorted(ship.s, new_head, side="right")) - 1
        head_cell = ship.route[i_new]
        zone = self.zone_label[head_cell]
        i_old = int(np.searchsorted(ship.s, ship.head, side="right")) - 1
        passed = {x for c in ship.route[i_old:i_new + 1] for x in self.stretches.get(c, ())}
        for k, other in self.ships.items():
            if other is ship or other.state.value not in UNDER_WAY:
                continue
            line = self.lines[k]
            oh, ot = line[-1], line[0]
            if np.hypot(*(oh - p_new)) > ship.loa + other.loa + dist + OVERTAKE_LATERAL_M:
                continue
            uo = self._heading(line)
            if uo is None or float(np.dot(u, uo)) < OVERTAKE_SAME_DIRECTION:
                continue
            if float(np.dot(oh - p_old, u)) <= 0 or dist < float(np.dot(ot - p_old, u)):
                continue                                   # not ahead of us, or we do not reach it
            lateral = float(uo[0] * (p_new[1] - oh[1]) - uo[1] * (p_new[0] - oh[0]))   # > 0: on its port side
            if abs(lateral) > OVERTAKE_LATERAL_M:
                continue
            stretches = passed | set(self.stretches.get(other.cells[-1], ()) if other.cells else ())
            if stretches and NR.encounter_conflicts(list(stretches), ship.rule_flags(), other.rule_flags(), "overtake"):
                return other, "overtaking ban"
            if zone in ("river", "dock", "canal") and lateral < -self.lane[head_cell] / 2:
                return other, "starboard side"
        return None

    def starboard_cells(self, other, radius=STARBOARD_AVOID_M):
        """Cells on the starboard side of a ship near its bow (kept clear by an overtaking detour)."""
        k = self._key(other)
        if k not in self.lines:
            return []
        line = self.lines[k]
        uo = self._heading(line)
        if uo is None:
            return []
        oh = line[-1]
        idx = self.tree_ids[self.tree.query_ball_point(oh, radius)]
        dx, dy = self.fg.x[idx] - oh[0], self.fg.y[idx] - oh[1]
        return [int(n) for n in idx[uo[0] * dy - uo[1] * dx < 0]]

    def blocker(self, ship):'''),
# the step: visibility cap, priority, overtaking check, overtaking detour
('''        want = {}
        for ship in sailing:''',
 '''        self.vis_cap = WG.speed_cap_kn(self.sim.weather, self.sim.now_ts())
        want = {}
        for ship in sailing:'''),
('''        def rank(ship):
            restricted = ship.cells and any(self.stretches.get(c) for c in ship.cells) and ship.oversized()
            return (0 if ship.distress else 1, 0 if restricted else 1, ship.clear_order, rng.random())''',
 '''        def rank(ship):
            """Right of way: distress / not under command, an oversized ship in a regulated stretch,
            in the docks a dock-oversized ship then the main waterway over side docks and lock exits
            (regs §2.5, §10.2), on the river the ship in the fairway over one crossing or entering it
            (regs §5.2), then the VTS order."""
            head = ship.cells[-1] if ship.cells else ship.route[0]
            zone = self.zone_label[head]
            restricted = ship.cells and any(self.stretches.get(c) for c in ship.cells) and ship.oversized()
            dock_oversized = zone == "dock" and ship.oversized("dock")
            main = zone != "dock" or self.main_waterway[head]
            in_fairway = zone != "river" or self.fairway[head]
            return (0 if ship.distress else 1, 0 if restricted else 1, 0 if dock_oversized else 1, 0 if main else 1,
                    0 if in_fairway else 1, ship.clear_order, rng.random())'''),
('''                    swept = self.hull_line(ship, min(ship.head, h - ship.loa), h)
                    other = self.conflict(ship, swept, self.hull_cells(ship, swept))
                    if other is None:''',
 '''                    swept = self.hull_line(ship, min(ship.head, h - ship.loa), h)
                    other = self.conflict(ship, swept, self.hull_cells(ship, swept))
                    if other is None:
                        bad = self.overtaking_violation(ship, h)
                        if bad is not None:
                            other, why = bad
                            if (ship.id, other.id) not in self.denied:
                                self.denied.add((ship.id, other.id))
                                ship.note(self.sim.t, "overtake_denied", other=other.id, why=why)
                    if other is None:'''),
('''                    self.sim.reroute_around(ship, avoid=self.ahead_cells(b) if b is not None else ())''',
 '''                    avoid = (self.ahead_cells(b) + self.starboard_cells(b)) if b is not None else ()
                    self.sim.reroute_around(ship, avoid=avoid)        # overtaking: round its port side'''),
('''A ship blocked for REROUTE_AFTER steps looks for a way round the other hulls (overtaking, getting
out of a head-on blockage); routes keep to starboard.''',
 '''Right of way in a conflict: distress, an oversized ship in a regulated stretch, in the docks a
dock-oversized ship and then the main waterway, on the river the fairway over ships crossing or
entering it, then the VTS order. Overtaking (coming alongside or past a ship sailing the same way)
is refused where a regulated stretch bans it (regs §6) and, on the river, in the docks and canals,
on the other ship's starboard side (regs §5.4: overtake on its port side); detours to overtake keep
off its starboard side. In restricted visibility ships slow down (weather_gates.VIS_SPEED_CAP_KN).
A ship blocked for REROUTE_AFTER steps looks for a way round the other hulls (overtaking, getting
out of a head-on blockage); routes keep to starboard.'''),
])
print("patched")
