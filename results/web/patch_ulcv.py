def patch(path, pairs):
    s = open(path, encoding="utf-8").read()
    for a, b in pairs:
        assert a in s, (path, a[:70])
        s = s.replace(a, b, 1)
    open(path, "w", encoding="utf-8").write(s)


patch("src/sim/engine.py", [
('''SEA_EXITS = ("exit_sea_southwest", "exit_sea_west", "exit_sea_north")''',
 '''SEA_EXITS = ("exit_sea_southwest", "exit_sea_west", "exit_sea_north")
# ULCV rules (regs §8.9, §8.11, JA22)
ULCV_HOLD_LOCKS = ("Zandvliet", "Berendrecht", "Terneuzen", "Hansweert")   # traffic out of them held ...
ULCV_HOLD_M = 5000.0                   # ... while a ULCV passes within this of their river side
ULCV_FALLBACK = ("PSA Noordzee Terminal", "PSA Europa Terminal", "MPET", "DP World Antwerp Gateway")
LOCK_RESERVE_LEAD_MIN = 60.0           # a ULCV's chamber is reserved this long before it reaches the lock
                                       # when its route does not pass CP'''),
# hold set-up
('''        self.route_cache, self.failed, self.reachable = {}, {}, {}''',
 '''        self.route_cache, self.failed, self.reachable = {}, {}, {}
        self.held_exits = {}                           # lock name -> ships kept in it during a ULCV passage
        self.hold_chainage = {}
        river = fg.mask("region", "river")
        for name in ULCV_HOLD_LOCKS:
            if name in self.locks:
                n = self.locks[name][0]
                near = river & (np.hypot(fg.x - fg.x[n], fg.y - fg.y[n]) < 3000.0)
                if near.any():
                    self.hold_chainage[name] = float(np.nanmedian(fg.chainage_m[near]))'''),
# lock step: holds
('''    def _locks(self, now):
        for name, (node, lock) in self.locks.items():''',
 '''    def ulcv_passing(self, name):
        """A ULCV under way on the river within ULCV_HOLD_M of this lock's river side."""
        c = self.hold_chainage.get(name)
        if c is None:
            return False
        for s in self.ships:
            if s.ulcv and s.state in MOVING and s.cells and self.mover.zone_label[s.cells[-1]] == "river":
                ch = self.fg.chainage_m[s.cells[-1]]
                if np.isfinite(ch) and abs(ch - c) <= ULCV_HOLD_M:
                    return True
        return False

    def _leave_lock(self, ship, name, t):
        ship.seg_start = ship.lock_index + 1
        self._segment(ship)
        ship.lock = None
        ship.set_state(State.SAILING, t, lock_done=name)
        if not self.mover.place(ship):
            ship.waiting_space = True

    def _locks(self, now):
        holds = {name: self.ulcv_passing(name) for name in self.hold_chainage}
        for name, ships in list(self.held_exits.items()):    # release ships held for a ULCV that has passed
            if not holds.get(name):
                for ship in ships:
                    ship.note(now, "released_after_ulcv", lock=name)
                    self._leave_lock(ship, name, now)
                del self.held_exits[name]
        for name, (node, lock) in self.locks.items():'''),
('''                elif e["event"] in ("exit", "passed"):
                    if e["event"] == "passed":
                        self.mover.release(ship)
                    ship.seg_start = ship.lock_index + 1
                    self._segment(ship)
                    ship.lock = None
                    ship.set_state(State.SAILING, e["t"], lock_done=name)
                    if not self.mover.place(ship):
                        ship.waiting_space = True''',
 '''                elif e["event"] in ("exit", "passed"):
                    if e["event"] == "passed":
                        self.mover.release(ship)
                    to_river = lock.sides.get(e.get("side"), {}).get("tidal")
                    if holds.get(name) and to_river and not ship.ulcv:
                        self.held_exits.setdefault(name, []).append(ship)      # regs: held during a ULCV passage
                        ship.note(e["t"], "held_for_ulcv", lock=name)
                        continue
                    self._leave_lock(ship, name, e["t"])'''),
# reserve the chamber at clearance
('''    def clear(self, ship, route, now):
        """The VTS cleared the ship: reserve, take the pilot(s), board / unmoor, then sail."""
        ship.lock_voyage = self.route_has_lock(route)''',
 '''    def reserve_ulcv_lock(self, ship, route, now):
        """A ULCV's lock chamber is kept empty for it from CP on (regs §8.9): reserved from its ETA
        at CP, or LOCK_RESERVE_LEAD_MIN before it reaches the lock when its route does not pass CP."""
        fg = self.fg
        r = np.asarray(route, dtype=np.int64)
        idx = [i for i, n in enumerate(route) if n in self.lock_of_node]
        if not idx:
            return
        lock = self.lock_of_node[route[idx[0]]]
        d = np.r_[0.0, np.cumsum(np.hypot(np.diff(fg.x[r]), np.diff(fg.y[r])))]
        v = ship.stw_kn("river", NR.planning_speed_kn) * 1852.0 / 60.0
        cp = self.places.get("cp", {}).get("node")
        at_cp = [i for i in range(idx[0]) if np.hypot(fg.x[r[i]] - fg.x[cp], fg.y[r[i]] - fg.y[cp]) < 1000.0] if cp is not None else []
        start = now + (d[at_cp[0]] / v if at_cp else max(d[idx[0]] / v - LOCK_RESERVE_LEAD_MIN, 0.0))
        fits = [c for c in lock.chambers if c.fits_size(ship.loa, ship.beam)]
        if not fits:
            return
        chamber = max(fits, key=lambda c: c.sill_depth_m)
        lock.reserve(ship.id, start, chamber.name)
        ship.note(now, "lock_reserved", lock=lock.name, chamber=chamber.name, from_min=round(start, 1),
                  from_cp=bool(at_cp))

    def clear(self, ship, route, now):
        """The VTS cleared the ship: reserve, take the pilot(s), board / unmoor, then sail."""
        ship.lock_voyage = self.route_has_lock(route)
        if ship.ulcv and ship.lock_voyage:
            self.reserve_ulcv_lock(ship, route, now)'''),
# fallback berth
('''        if ship.terminal:
            T = self.terminals[ship.terminal]
            if not any(b - a >= ship.loa for a, b in T.suitable_intervals(ship.draught, ship.sea_going)):
                ship.infeasible = f"no stretch of quay at {T.name} allows {ship.draught} m over {ship.loa:.0f} m"
                return None
            s0 = T.find_position(ship.loa, draught=ship.draught, sea_going=ship.sea_going)
            if s0 is None:
                return None                            # quay full: wait''',
 '''        if ship.terminal:
            T = self.terminals[ship.terminal]
            fits = any(b - a >= ship.loa for a, b in T.suitable_intervals(ship.draught, ship.sea_going))
            s0 = T.find_position(ship.loa, draught=ship.draught, sea_going=ship.sea_going) if fits else None
            if s0 is None and ship.ulcv and not ship.departing:
                # ULCV: the fallback berth its agent has to name (regs §8.11)
                for name in ULCV_FALLBACK:
                    F = self.terminals.get(name)
                    if F is None or F is T:
                        continue
                    s1 = F.find_position(ship.loa, draught=ship.draught, sea_going=ship.sea_going)
                    if s1 is not None:
                        ship.note(self.t, "fallback_berth", planned=ship.terminal, used=name)
                        ship.planned_terminal = ship.planned_terminal if hasattr(ship, "planned_terminal") else ship.terminal
                        ship.terminal, T, s0, fits = name, F, s1, True
                        break
            if not fits:
                ship.infeasible = f"no stretch of quay at {T.name} allows {ship.draught} m over {ship.loa:.0f} m"
                return None
            if s0 is None:
                return None                            # quay full: wait'''),
])
print("patched")
