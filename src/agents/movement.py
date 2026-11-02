"""Ships on the mesh (PLAN.md §5.3): hulls, two-phase moves, local traffic rules.

A sailing ship follows the cells of its route (cell centres). Its hull is a centre line along the
route from its bow back over its length (LOA), with its real beam, so a ship can be longer and wider
than the cells it covers:

    ship.cells   the route cells under the centre line (the last one is the bow's cell)
    ship.hull    every cell within beam / 2 + clearance + half a cell of the centre line: what the
                 ship takes up (used to find who blocks whom and to keep detours clear)

Two ships conflict when their centre lines come closer than
        (B1 + B2) / 2 + GAP_FRACTION x max(B1, B2)        (hull to hull: 20 % of the wider beam)
less what they can still move apart sideways inside their own cell: a ship narrower than its lane
can shift (lane width - B) / 2 off the cell centre. So two barges pass in one 50 m lane, two 32 m
bulk carriers need neighbouring lanes, two 61 m ULCVs need two lanes between them, and at sea (250 m
cells) ships pass freely. Lock, anchorage and approach nodes hold no hull (the resources hold the
ships there). Routes of wide ships keep to cells with room for their beam (clearance.py).

Each step:
  1. proposal: every ship wants to advance v_sog x dt along its route, with v_sog its speed
     through the water plus the current along its heading (times the reach's SOG response to the
     current seen in AIS: 1 in the Western Scheldt, ~0.4 in the Zeeschelde), capped by the speed limit
  2. resolution: in priority order (distress, an oversized ship in a regulated stretch, VTS rank,
     a seeded tie-break) each ship takes the farthest position up to its proposal whose swept hull
     (from its old bow to its new one) and new hull conflict with no other ship. Before entering a
     regulated stretch it checks the encounter rules (navigation_rules.encounter_conflicts) against
     ships coming the other way inside it, and the 3 nm spacing rule against ships ahead. Ships that
     were stopped by a ship processed later try again (up to PASSES passes).
  3. all moves are applied together.
Right of way in a conflict: distress, an oversized ship in a regulated stretch, in the docks a
dock-oversized ship and then the main waterway, on the river the fairway over ships crossing or
entering it, then the VTS order. Overtaking (coming alongside or past a ship sailing the same way)
is refused where a regulated stretch bans it (regs §6) and, on the river, in the docks and canals,
on the other ship's starboard side (regs §5.4: overtake on its port side); detours to overtake keep
off its starboard side. In restricted visibility ships slow down (weather_gates.VIS_SPEED_CAP_KN).
A ship blocked for REROUTE_AFTER steps looks for a way round the other hulls (overtaking, getting
out of a head-on blockage); routes keep to starboard. A head-on or crossing deadlock with no way
round lets the two ships pass after DEADLOCK_AFTER steps (logged as squeeze_past).
"""

from __future__ import annotations

import numpy as np
import shapely
from scipy.spatial import cKDTree

import navigation_rules as NR
import weather_gates as WG
from clearance import lane_width

KNOT = 1852.0 / 3600.0
PASSES = 3
REROUTE_AFTER = 3
MAX_REROUTES_PER_STEP = 15
MIN_SOG_KN = 1.0
GAP_FRACTION = 0.20                     # hull-to-hull clearance of ships alongside: 20 % of the wider beam
HULL_SAMPLE_M = 25.0                    # spacing of the points that find the cells under a hull
ENCOUNTER_STALE = 3                     # a ship blocked this many steps does not count as passing through
ENCOUNTER_OVERRIDE = 12                 # held this many steps by a rule: the VTS lets it proceed (logged)
DEADLOCK_AFTER = 12                     # head-on / crossing deadlock with no way round: pass after 1 h
LEG = {"sea": "sea", "river": "river", "dock": "river", "canal": "river"}
WAITING = ("lock_queue", "mooring", "wait_pilot", "pilot_change", "at_berth", "unmooring")
UNDER_WAY = ("sailing", "to_station", "to_anchorage")
OVERTAKE_SAME_DIRECTION = 0.7          # cos of the angle between two headings for "same way"
OVERTAKE_LATERAL_M = 400.0             # alongside: closer than this sideways
STARBOARD_AVOID_M = 1500.0             # a detour to overtake keeps off this much of the other's starboard side


def required_gap(b1, b2):
    """Smallest distance between the centre lines of two ships alongside each other."""
    return (b1 + b2) / 2 + GAP_FRACTION * max(b1, b2)


class Mover:
    def __init__(self, sim):
        self.sim = sim
        fg = sim.fg
        self.fg = fg
        self.special = np.isin(fg.type, [fg.code("type", t) for t in ("lock", "anchorage", "approach")])
        self.zone_label = np.array(fg.labels["speed_zone"] + [None], dtype=object)[fg.speed_zone]
        self.lane = lane_width(fg)
        water = np.flatnonzero(~self.special)
        self.tree = cKDTree(np.column_stack([fg.x[water], fg.y[water]]))
        self.tree_ids = water
        self.stretches = {}
        self.main_waterway = np.zeros(fg.n, dtype=bool)
        for n, d in sim.graph.nodes(data=True):
            if d.get("stretches"):
                self.stretches[n] = tuple(d["stretches"])
            if d.get("main_waterway"):
                self.main_waterway[n] = True
        self.fairway = fg.fairway.astype(bool)
        self.vis_cap = None
        self.denied = set()
        self.ships = {}                                        # key -> Ship on the mesh
        self.lines = {}                                        # key -> hull centre line (n x 2)
        self.occ = {}                                          # cell -> keys of the hulls covering it
        self.allow = {}                                        # key -> keys it may pass this step (deadlocks)
        self.next_index = 0
        self.index_of = {}

    # ------------------------------------------------------------------ geometry
    def _key(self, ship):
        if ship.id not in self.index_of:
            self.index_of[ship.id] = self.next_index
            self.next_index += 1
        return self.index_of[ship.id]

    def _xy(self, ship, svals):
        r = ship.route
        return np.column_stack([np.interp(svals, ship.s, self.fg.x[r]), np.interp(svals, ship.s, self.fg.y[r])])

    def hull_line(self, ship, s_from, s_to):
        """Centre line of the ship between route positions s_from and s_to (clipped to the route)."""
        s_from, s_to = max(0.0, min(s_from, s_to)), max(0.0, s_to)
        inner = ship.s[(ship.s > s_from) & (ship.s < s_to)]
        return self._xy(ship, np.r_[s_from, inner, s_to])

    def footprint(self, ship, head=None):
        """Route cells under the centre line, bow's cell last."""
        head = ship.head if head is None else head
        s, route = ship.s, ship.route
        i1 = int(np.searchsorted(s, head, side="right")) - 1
        i0 = int(np.searchsorted(s, head - ship.loa, side="left"))
        cells = [route[i] for i in range(max(min(i0, i1), 0), i1 + 1)]
        return [c for c in cells if not self.special[c]]

    def hull_cells(self, ship, line):
        """Cells within the ship's beam / 2 + clearance + half a cell of its centre line."""
        seg = np.hypot(*np.diff(line, axis=0).T) if len(line) > 1 else np.zeros(0)
        pts = [line[:1]]
        for (a, b), d in zip(zip(line[:-1], line[1:]), seg):
            k = max(int(d // HULL_SAMPLE_M), 1)
            pts.append(a + (b - a) * (np.arange(1, k + 1) / k)[:, None])
        pts = np.vstack(pts)
        r = ship.beam / 2 + GAP_FRACTION * ship.beam + HULL_SAMPLE_M
        hits = self.tree.query_ball_point(pts, r)
        return sorted({int(self.tree_ids[i]) for h in hits for i in h})

    def shift(self, ship):
        """How far the ship can move off its cell centre line, sideways, inside its lane."""
        head = ship.cells[-1] if ship.cells else (ship.route[0] if ship.route else None)
        if head is None:
            return 0.0
        return max(0.0, (self.lane[head] - ship.beam) / 2)

    @staticmethod
    def _line(xy):
        return shapely.LineString(xy if len(xy) > 1 else np.vstack([xy, xy + 1e-3]))

    def conflict(self, ship, line, cells):
        """The first other ship whose hull is too close to this centre line, or None."""
        k = self._key(ship)
        others = set()
        for c in cells:
            others |= self.occ.get(c, set())
        others.discard(k)
        if not others:
            return None
        mine = self._line(line)
        my_shift = self.shift(ship)
        for o in sorted(others):
            if o in self.allow.get(k, ()):
                continue
            other = self.ships[o]
            d = mine.distance(self._line(self.lines[o]))
            if d + my_shift + self.shift(other) < required_gap(ship.beam, other.beam):
                return other
        return None

    # ------------------------------------------------------------------ occupancy
    def occupy(self, ship, head, line=None):
        k = self._key(ship)
        self._clear(k, ship)
        line = self.hull_line(ship, head - ship.loa, head) if line is None else line
        ship.head = head
        ship.cells = self.footprint(ship, head)
        ship.hull = self.hull_cells(ship, line)
        for c in ship.hull:
            self.occ.setdefault(c, set()).add(k)
        self.lines[k] = line
        self.ships[k] = ship

    def _clear(self, k, ship):
        for c in getattr(ship, "hull", []) or []:
            s = self.occ.get(c)
            if s is not None:
                s.discard(k)
                if not s:
                    del self.occ[c]

    def release(self, ship):
        k = self._key(ship)
        self._clear(k, ship)
        ship.cells, ship.hull = [], []
        self.ships.pop(k, None)
        self.lines.pop(k, None)

    def place(self, ship, cells=None):
        """Put a ship on the mesh at its route position; False if another hull is too close."""
        line = self.hull_line(ship, ship.head - ship.loa, ship.head)
        if self.conflict(ship, line, self.hull_cells(ship, line)) is not None:
            return False
        self.occupy(ship, ship.head, line)
        return True

    def free_mask(self, ship):
        """Cells no other ship's hull covers (for detours)."""
        k = self._key(ship)
        mask = np.ones(self.fg.n, dtype=bool)
        for c, keys in self.occ.items():
            if keys - {k}:
                mask[c] = False
        return mask

    # ------------------------------------------------------------------ speed
    def sog_kn(self, ship, node, nxt, t_index):
        fg, sim = self.fg, self.sim
        zone = self.zone_label[node]
        stw = ship.stw_kn(LEG.get(zone, "river"), NR.planning_speed_kn)
        limit = fg.speed_limit_kn[node]
        if zone == "dock" and np.isnan(limit):
            limit = sim.dock_speed_kn
        current = 0.0
        sl = sim.slice_of[node]
        if sl >= 0 and nxt is not None:
            dx, dy = fg.x[nxt] - fg.x[node], fg.y[nxt] - fg.y[node]
            n = np.hypot(dx, dy)
            if n > 0:
                current = sim.current_sog_u[t_index, sl] * (dx * fg.flow_dir[node, 0] + dy * fg.flow_dir[node, 1]) / n / KNOT
        sog = stw + current
        if not np.isnan(limit):
            sog = min(sog, limit)
        if ship.remaining_m < 1500:                     # last approach to a berth / lock: slow
            sog = min(sog, sim.dock_speed_kn)
        if self.vis_cap is not None:                    # restricted visibility (COLREG 19)
            sog = min(sog, self.vis_cap)
        return max(sog, MIN_SOG_KN)

    # ------------------------------------------------------------------ rules
    def _direction(self, ship, i):
        """+1 sailing upstream / inland at route index i, -1 downstream, 0 unknown."""
        fg, r = self.fg, ship.route
        if i + 1 >= len(r):
            return 0
        a, b = r[i], r[i + 1]
        f = fg.flow_dir[a]
        if np.isnan(f[0]):
            return 0
        c = (fg.x[b] - fg.x[a]) * f[0] + (fg.y[b] - fg.y[a]) * f[1]
        return 1 if c > 0 else -1 if c < 0 else 0

    def _stretch_limit(self, ship, i_from, i_to, directions, inside):
        """Last route index ship may reach in (i_from, i_to] under the encounter and spacing rules."""
        route = ship.route
        if not ship.rule_relevant:
            return i_to
        own = set(self.stretches.get(route[i_from], ()))
        my_dir = directions.get(ship.id, 0)
        zone = "river"
        for i in range(i_from + 1, i_to + 1):
            st = self.stretches.get(route[i], ())
            new = [x for x in st if x not in own]
            for name in new:
                for other in inside.get(name, ()):
                    if other is ship:
                        continue
                    od = directions.get(other.id, 0)
                    if my_dir and od and od != my_dir and NR.encounter_conflicts(
                            [name], ship.rule_flags(zone), other.rule_flags(zone), "meet"):
                        ship.encounter_hold += 1
                        if ship.encounter_hold > ENCOUNTER_OVERRIDE:
                            if ship.encounter_hold == ENCOUNTER_OVERRIDE + 1:
                                ship.note(self.sim.t, "encounter_rule_overridden", stretch=name, other=other.id)
                            continue
                        if ship.encounter_hold == 1:
                            ship.note(self.sim.t, "hold_encounter_rule", stretch=name, other=other.id)
                        return i - 1
            for name in st:
                for other in inside.get(name, ()):
                    if other is ship or directions.get(other.id, 0) != my_dir or not my_dir:
                        continue
                    gap = NR.min_spacing_m([name], ship.rule_flags(zone), other.rule_flags(zone))
                    if gap and other.cells:
                        ahead = self.fg.chainage_m[other.cells[-1]] - self.fg.chainage_m[route[i]]
                        if 0 < ahead * my_dir < gap:
                            return i - 1
            own |= set(st)
        return i_to

    def _heading(self, line):
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

    def blocker(self, ship):
        """The ship that stopped this one in the last step, else the first hull on its way ahead."""
        b = getattr(ship, "blocked_by", None)
        if b is not None and self._key(b) in self.ships:
            return b
        i = int(np.searchsorted(ship.s, ship.head, side="right")) - 1
        k = self._key(ship)
        for c in ship.route[i + 1:i + 40]:
            keys = self.occ.get(c, set()) - {k}
            if keys:
                return self.ships.get(min(keys))
        return None

    def ahead_cells(self, ship, n=60):
        """The next cells of a ship's route (where it is about to sail)."""
        if ship.s is None:
            return []
        i = int(np.searchsorted(ship.s, ship.head, side="right")) - 1
        return ship.route[i:i + n]

    def head_on(self, ship, other):
        """other is coming towards ship: ship's bow lies on other's way ahead."""
        if other.s is None or not ship.cells:
            return False
        return ship.cells[-1] in set(self.ahead_cells(other))

    def _deadlocks(self, sailing):
        """Head-on or crossing deadlocks with no way round (blocked DEADLOCK_AFTER steps): the two
        ships pass each other this step."""
        self.allow = {}
        for ship in sailing:
            if ship.blocked_steps < DEADLOCK_AFTER:
                continue
            b = self.blocker(ship)
            if b is None or not (self.head_on(ship, b) or self.blocker(b) is ship):
                continue
            k, kb = self._key(ship), self._key(b)
            self.allow.setdefault(k, set()).add(kb)
            self.allow.setdefault(kb, set()).add(k)
            if ship.blocked_steps == DEADLOCK_AFTER:
                ship.note(self.sim.t, "squeeze_past", other=b.id)

    def _queueing(self, ship):
        """Waiting behind a ship that is itself waiting (lock, berth, pilot): a queue, not something
        to sail round."""
        b = self.blocker(ship)
        return b is None or b.state.value in WAITING

    # ------------------------------------------------------------------ step
    def step(self, sailing, dt_min, t_index, rng):
        """Move the sailing ships; returns the ships that reached the end of their route."""
        if not sailing:
            return []
        directions, inside = {}, {}
        for ship in self.ships.values():
            if ship.s is None or not ship.cells:
                continue
            i = int(np.searchsorted(ship.s, ship.head, side="right")) - 1
            directions[ship.id] = self._direction(ship, i)
            if ship.state.value not in ("sailing", "to_station", "to_anchorage") or ship.blocked_steps >= ENCOUNTER_STALE:
                continue                       # a stopped ship is not passing through the stretch
            for name in self.stretches.get(ship.cells[-1], ()):
                inside.setdefault(name, []).append(ship)
        self.vis_cap = WG.speed_cap_kn(self.sim.weather, self.sim.now_ts())
        want = {}
        for ship in sailing:
            i = int(np.searchsorted(ship.s, ship.head, side="right")) - 1
            nxt = ship.route[i + 1] if i + 1 < len(ship.route) else None
            v = self.sog_kn(ship, ship.route[i], nxt, t_index) * KNOT * dt_min * 60.0
            want[ship.id] = min(ship.head + v, float(ship.s[-1]))

        def rank(ship):
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
                    0 if in_fairway else 1, ship.clear_order, rng.random())

        order = sorted(sailing, key=rank)
        self._deadlocks(sailing)
        moved, done = {}, set()
        todo = order
        for _ in range(PASSES):
            retry = []
            for ship in todo:
                ship.blocked_by = None
                i0 = int(np.searchsorted(ship.s, ship.head, side="right")) - 1
                i_want = int(np.searchsorted(ship.s, want[ship.id], side="right")) - 1
                i_ok = self._stretch_limit(ship, i0, i_want, directions, inside) if i_want > i0 else i0
                heads = ([want[ship.id]] if i_ok == i_want else []) + [float(ship.s[i]) for i in range(i_ok, i0, -1)]
                for h in heads:
                    if h <= ship.head + 1e-6:
                        break
                    swept = self.hull_line(ship, min(ship.head, h - ship.loa), h)
                    other = self.conflict(ship, swept, self.hull_cells(ship, swept))
                    if other is None:
                        bad = self.overtaking_violation(ship, h)
                        if bad is not None:
                            other, why = bad
                            if (ship.id, other.id) not in self.denied:
                                self.denied.add((ship.id, other.id))
                                ship.note(self.sim.t, "overtake_denied", other=other.id, why=why)
                    if other is None:
                        self.occupy(ship, h)
                        moved[ship.id] = True
                        break
                    if ship.blocked_by is None:
                        ship.blocked_by = other
                done.add(ship.id)
                b = ship.blocked_by
                if ship.id not in moved and b is not None and b.id not in done:
                    retry.append(ship)                 # blocked by a ship that has not moved yet
            if not retry:
                break
            todo = retry
        arrived = []
        reroutes = 0
        for ship in sailing:
            if ship.head >= ship.s[-1] - 1e-6:
                arrived.append(ship)
                ship.blocked_steps = 0
            elif ship.id in moved:
                ship.blocked_steps = 0
                ship.encounter_hold = 0
            else:
                ship.blocked_steps += 1
                if reroutes >= MAX_REROUTES_PER_STEP:
                    continue
                b = self.blocker(ship)
                if b is not None and self.head_on(ship, b):
                    # head-on: the lower-ranked ship gives way at once, round the other's next cells
                    if (ship.clear_order, ship.id) > (b.clear_order, b.id) or b.state.value not in ("sailing", "to_station", "to_anchorage"):
                        reroutes += 1
                        ship.reroutes += 1
                        self.sim.reroute_around(ship, avoid=self.ahead_cells(b))
                    continue
                due = REROUTE_AFTER * 2 ** min(ship.reroutes, 5)
                if ship.blocked_steps >= due and not self._queueing(ship):
                    reroutes += 1
                    ship.reroutes += 1
                    avoid = (self.ahead_cells(b) + self.starboard_cells(b)) if b is not None else ()
                    self.sim.reroute_around(ship, avoid=avoid)        # overtaking: round its port side
        return arrived
