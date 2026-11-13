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
can shift s = (lane width - B) / 2 off the cell centre, to the side of the lane it keeps (ship.side:
starboard, or port while it overtakes). Ships on opposite sides of the lane (meeting, each on its own
starboard side; or one overtaking the other on its port side) gain s1 + s2; ships on the same side
(following each other) only |s1 - s2|, so a ship cannot sail into or sit on top of the one ahead of
it in its lane, and only two fit abreast. So two barges pass in one 50 m lane, two 32 m bulk carriers
need neighbouring lanes, two 61 m ULCVs need two lanes between them, and at sea (250 m cells) ships
pass freely. Ships crossing each other wait for the other to clear (shifting does not separate them). Lock, anchorage and
approach nodes hold no hull (the resources hold the ships there). Routes of wide ships keep to cells
with room for their beam (clearance.py). ship.lateral_m records how far a ship had to stand off the
centre line to keep that distance (for the viewer: ships passing in one lane are drawn side by side).

Each step:
  1. proposal: every ship wants to advance v_sog x dt along its route, with v_sog its speed
     through the water plus the current along its heading (times the reach's SOG response to the
     current seen in AIS: 1 in the Western Scheldt, ~0.4 in the Zeeschelde), capped by the speed limit
  2. resolution: in priority order (distress, an oversized ship in a regulated stretch, VTS rank,
     a seeded tie-break) each ship takes the farthest position up to its proposal whose swept hull
     (from its old bow to its new one) and new hull conflict with no other ship, keeping to the
     starboard side of its lane, or, when that is blocked by a ship sailing the same way, passing it
     on the port side of the lane if the lane is wide enough. Before entering a
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
round first makes them stand aside (SIDESTEP_AFTER), as far as there is water for it; only with no room
for that either do the two ships pass after DEADLOCK_AFTER steps (logged as squeeze_past); so does a knot of
several stuck ships (a ship blocked that long by a ship that is itself stuck under way passes it and
the other stuck ships on its way ahead). A ship stuck LANE_FREE_AFTER steps detours without the lanes.
"""

from __future__ import annotations

import math

import numpy as np
import shapely
import shapely.ops
from scipy.spatial import cKDTree

import navigation_rules as NR
import port_infrastructure as PI
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
LANE_FREE_AFTER = 36                    # stuck this long (3 h): detours may ignore the lanes
LOCK_WAIT_M = 800.0                     # ships bound into a lock join its queue this far before the gate
LEG = {"sea": "sea", "river": "river", "dock": "river", "canal": "river"}
WAITING = ("lock_queue", "mooring", "wait_pilot", "pilot_change", "at_berth", "unmooring")
UNDER_WAY = ("sailing", "to_station", "to_anchorage")
OVERTAKE_SAME_DIRECTION = 0.7          # cos of the angle between two headings for "same way"
OVERTAKE_LATERAL_M = 400.0             # alongside: closer than this sideways
STARBOARD_AVOID_M = 1500.0             # a detour to overtake keeps off this much of the other's starboard side
IN_LINE_M = 1.0                         # hulls closer than this across the heading lie in line
SIDESTEP_AFTER = 2                      # blocked this many steps (10 min) by a ship it cannot get past: stand aside
SIDESTEP_MAX_M = 150.0                  # ... up to this far off the centre line, where there is water for it
SIDESTEP_PROBE_M = 25.0
SIDESTEP_MARGIN_M = 0.5                 # water under the keel needed where it stands aside
NEAREST_CELL_M = {"river": 110.0, "sea": 180.0}     # a point this close to a cell is that cell's water (else 40 m)
DEPTH_HOLD_MAX = 156                    # stopped by the depth this many steps (13 h, a tide): it proceeds (logged)


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
        self.near_cell = np.full(fg.n, 40.0)
        for region, m in NEAREST_CELL_M.items():
            if region in fg.labels["region"]:
                self.near_cell[fg.mask("region", region)] = m
        self.stretches = {}
        self.main_waterway = np.zeros(fg.n, dtype=bool)
        for n, d in sim.graph.nodes(data=True):
            if d.get("stretches"):
                self.stretches[n] = tuple(d["stretches"])
            if d.get("main_waterway"):
                self.main_waterway[n] = True
        self.fairway = fg.fairway.astype(bool)
        # inland craft sail faster than sea-going ships in the docks and canals (AIS); both slow at the locks
        self.inland_limit_kn = fg.speed_limit_kn.copy()
        approach = sim.graph.graph.get("speed_limits", {}).get("lock_approach_kn", 0.0)
        inland = getattr(PI, "INLAND_DOCK_SPEED_KN", {})
        for zone, key in (("dock", "dock"), ("canal", "canal")):
            if key in inland:
                m = (self.zone_label == zone) & ~(self.inland_limit_kn <= approach)
                self.inland_limit_kn[m] = inland[key][NR.SPEED_PERCENTILE]
        # ... and at the locks the inland craft's own approach speed (AIS 3.1 kn), not the sea-going ships' 2.5 kn:
        # inland craft took 1.05 h to pass Hansweert where the AIS has 0.67 h (validation, MODEL.md §19)
        if "lock_approach" in inland:
            m = np.isin(self.zone_label, ("dock", "canal")) & (fg.speed_limit_kn <= approach)
            self.inland_limit_kn[m] = inland["lock_approach"][NR.SPEED_PERCENTILE]
        self.vis_cap = None
        self.denied = set()
        self.ships = {}                                        # key -> Ship on the mesh
        self.lines = {}                                        # key -> hull centre line (n x 2)
        self.boxes = {}                                        # key -> bounding box of that line, and the beam
        self.occ = {}                                          # cell -> keys of the hulls covering it
        self.allow = {}                                        # key -> keys it may pass this step (deadlocks)
        self.next_index = 0
        self.index_of = {}
        # bow position and length per key (inf: not on the mesh), for finding the ships near a point at once
        self.bow_xy = np.full((1024, 2), np.inf)
        self.loa_of = np.zeros(1024)

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
        idx = np.fromiter((i for h in hits for i in h), dtype=np.int64)
        return np.unique(self.tree_ids[idx]).tolist()

    def shift(self, ship):
        """How far the ship can move off its cell centre line, sideways: inside its lane, or as far as it has
        been given room to stand aside (sidestep_m)."""
        head = ship.cells[-1] if ship.cells else (ship.route[0] if ship.route else None)
        if head is None:
            return 0.0
        return max(0.0, (self.lane[head] - ship.beam) / 2, getattr(ship, "sidestep_m", 0.0))

    def room_aside(self, ship, side):
        """How far the ship's centre line can move to this side (+1 starboard, -1 port) with its whole hull in
        water deep enough for it now: probed from its bow, middle and stern out to SIDESTEP_MAX_M."""
        k = self._key(ship)
        line = self.lines.get(k)
        u = self._heading(line) if line is not None else None
        if u is None:
            return 0.0
        fg, level = self.fg, self.sim.level_now
        n = np.array([u[1], -u[0]]) * side
        need = ship.draught + SIDESTEP_MARGIN_M
        room = SIDESTEP_MAX_M
        for p in (line[0], line[len(line) // 2], line[-1]):
            reach = 0.0
            for o in np.arange(SIDESTEP_PROBE_M, SIDESTEP_MAX_M + ship.beam / 2 + SIDESTEP_PROBE_M, SIDESTEP_PROBE_M):
                dist, i = self.tree.query(p + n * o)
                cell = self.tree_ids[i]
                if dist > self.near_cell[cell] or fg.depth_m[cell] + level[cell] < need:
                    break
                reach = o
            room = min(room, max(reach - ship.beam / 2, 0.0))
            if room == 0.0:
                break
        return room

    @staticmethod
    def _line(xy):
        return shapely.LineString(xy if len(xy) > 1 else np.vstack([xy, xy + 1e-3]))

    def apart(self, ship, line, side, other, other_line):
        """(y, g): how two ships lie and move relative to each other, across this ship's heading. y: where the
        other's hull lies (m, + = to starboard); g: how far apart their sides would take them when they lie
        exactly in line (meeting: each to its starboard; same way: the sides they keep). None when they cross."""
        mine, theirs = self._line(line), self._line(other_line)
        a, b = shapely.ops.nearest_points(mine, theirs)
        # the headings where the hulls are closest, not of the whole hulls: a ship following a bend alongside
        # another is not crossing it
        u1, u2 = self._heading_at(mine, a), self._heading_at(theirs, b)
        if u1 is None or u2 is None:
            return None
        c = float(np.dot(u1, u2))
        if abs(c) < OVERTAKE_SAME_DIRECTION:
            return None
        s1, s2 = self.shift(ship), self.shift(other)
        l2 = other.side * s2 if c > 0 else -s2
        return (b.x - a.x) * u1[1] - (b.y - a.y) * u1[0], l2 - side * s1

    @staticmethod
    def _heading_at(line, point, reach=30.0):
        """The heading of a line around one of its points."""
        s = line.project(point)
        p0, p1 = line.interpolate(max(s - reach, 0.0)), line.interpolate(min(s + reach, line.length))
        d = np.array([p1.x - p0.x, p1.y - p0.y])
        n = float(np.hypot(*d))
        return d / n if n > 0 else None

    def separation(self, ship, line, side, other, other_line, d):
        """The distance two ships can stand apart, shifting to their sides."""
        rel = self.apart(ship, line, side, other, other_line)
        if rel is None:                                # crossing: shifting does not help, it waits for the other ...
            now = self.lines.get(self._key(ship))
            if now is not None and self._line(now).distance(self._line(other_line)) < required_gap(ship.beam, other.beam):
                return math.inf                        # ... unless they already touch: only moving can part them
            return d
        y, g = rel
        # side by side each moves away from the other, whichever side that is (a remembered side took them
        # towards each other, or stopped two ships that had room); exactly in line their sides decide
        return abs(y) + self.shift(ship) + self.shift(other) if abs(y) > IN_LINE_M else abs(g)

    def conflict(self, ship, line, cells, side=None):
        """The first other ship whose hull is too close to this centre line, or None. side: the side of
        its lane the ship would keep (default: the one it keeps now)."""
        k = self._key(ship)
        side = ship.side if side is None else side
        others = self.near(k, ship, line)
        if not others:
            return None
        mine = self._line(line)
        for o in sorted(others):
            if o in self.allow.get(k, ()):
                continue
            other = self.ships[o]
            d = mine.distance(self._line(self.lines[o]))
            gap = required_gap(ship.beam, other.beam)
            if d >= gap:
                continue
            if self.separation(ship, line, side, other, self.lines[o], d) < gap:
                return other
        return None

    def near(self, k, ship, line):
        """The ships whose hull lies close enough to this centre line to matter, from where the hulls are:
        on the river a cell is 200 m long, and a short hull between two rows of cells covered no cell, so
        looking for ships on the same cells missed it."""
        x0, y0, x1, y1 = line[:, 0].min(), line[:, 1].min(), line[:, 0].max(), line[:, 1].max()
        out = []
        for o, (a0, b0, a1, b1, beam) in self.boxes.items():
            r = required_gap(ship.beam, beam)
            if o != k and a0 - r <= x1 and a1 + r >= x0 and b0 - r <= y1 and b1 + r >= y0:
                out.append(o)
        return out

    def free_side(self, ship, line, cells):
        """The side of its lane on which the ship's hull at `line` conflicts with no one: starboard (+1)
        first, else port (-1) when the ship in the way sails the same way (overtaking on its port side,
        regs §5.4; the rules of the stretch are checked by overtaking_violation). Returns (side, None)
        or (None, the ship in the way)."""
        other = self.conflict(ship, line, cells, side=1)
        if other is None:
            return 1, None
        ko = self._key(other)
        u1, u2 = self._heading(line), self._heading(self.lines[ko]) if ko in self.lines else None
        if u1 is not None and u2 is not None and float(np.dot(u1, u2)) >= OVERTAKE_SAME_DIRECTION \
                and self.conflict(ship, line, cells, side=-1) is None:
            return -1, None
        return None, other

    def _lateral(self):
        """ship.lateral_m of every ship under way: how far it stands off its centre line, to its side of
        the lane, to keep the required distance from the ships it is passing (0 when none is that close)."""
        for k, ship in self.ships.items():
            f, away = 0.0, ship.side
            if ship.state.value in UNDER_WAY + ("pilot_change",):   # (a short hull between two rows of cells has no hull cells)
                others = self.near(k, ship, self.lines[k])
                if others:
                    mine = self._line(self.lines[k])
                    for o in others:
                        other = self.ships[o]
                        d = mine.distance(self._line(self.lines[o]))
                        gap = required_gap(ship.beam, other.beam)
                        if d >= gap:
                            continue
                        rel = self.apart(ship, self.lines[k], ship.side, other, self.lines[o])
                        if rel is None:
                            continue
                        y, g = rel
                        beside = abs(y) > IN_LINE_M
                        a = self.shift(ship) + self.shift(other) if beside else abs(g)
                        need = min(1.0, (gap - d) / a) if a > 0 else 0.0
                        if need > f:
                            f = need
                            away = (-1 if y > 0 else 1) if beside else ship.side
            if f == 0.0:
                ship.sidestep_m = 0.0                  # clear of the others: back to its lane
            ship.lateral_m = away * f * self.shift(ship)

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
        if k >= len(self.loa_of):
            grow = len(self.loa_of)
            self.bow_xy = np.vstack([self.bow_xy, np.full((grow, 2), np.inf)])
            self.loa_of = np.r_[self.loa_of, np.zeros(grow)]
        self.bow_xy[k], self.loa_of[k] = line[-1], ship.loa
        self.boxes[k] = (line[:, 0].min(), line[:, 1].min(), line[:, 0].max(), line[:, 1].max(), ship.beam)

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
        ship.side, ship.lateral_m, ship.sidestep_m = 1, 0.0, 0.0
        self.ships.pop(k, None)
        self.lines.pop(k, None)
        self.boxes.pop(k, None)
        if k < len(self.loa_of):
            self.bow_xy[k] = np.inf

    def place(self, ship, cells=None):
        """Put a ship on the mesh at its route position; False if another hull is too close."""
        line = self.hull_line(ship, ship.head - ship.loa, ship.head)
        side, _ = self.free_side(ship, line, self.hull_cells(ship, line))
        if side is None:
            return False
        ship.side = side
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
        limit = fg.speed_limit_kn[node] if ship.sea_going else self.inland_limit_kn[node]
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
        if ship.remaining_m < 1500 and ship.lock_index >= 0:   # last approach to a lock: slow
            # (not to a berth: the mooring time, fitted on the AIS from 1 km off the berth to lying still,
            # holds that approach; slowing as well counted it twice: a sea-going ship under way in the docks
            # 3.9 at once against 2.8 in the AIS, validation MODEL.md §19)
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

    def _depth_limit(self, ship, i_from, i_to):
        """Last route index in (i_from, i_to] with water under the keel now: the VTS checks a voyage when it
        starts, but a ship held up on the way can miss its tide, and then waits for the water. Never for
        more than DEPTH_HOLD_MAX steps (logged: a route over a bank the tide never covers)."""
        cells = np.asarray(ship.route[i_from + 1:i_to + 1], dtype=np.int64)
        sim = self.sim
        bad = ~sim.passable.get(sim.k, sim.level_now, ship.draught)[cells] & ~self.special[cells]
        if not bad.any():
            ship.depth_hold = 0
            return i_to
        ship.depth_hold = getattr(ship, "depth_hold", 0) + 1
        if ship.depth_hold == 1:
            ship.note(sim.t, "hold_depth", at=int(cells[np.argmax(bad)]))
        if ship.depth_hold > DEPTH_HOLD_MAX:
            if ship.depth_hold == DEPTH_HOLD_MAX + 1:
                ship.note(sim.t, "depth_hold_overridden", at=int(cells[np.argmax(bad)]))
            return i_to
        return i_from + int(np.argmax(bad))

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
        # the ships near enough to matter, found at once (this loop ran over every ship on the mesh for
        # every move: a sixth of the run time)
        n = self.next_index
        near = np.hypot(self.bow_xy[:n, 0] - p_new[0], self.bow_xy[:n, 1] - p_new[1])             <= ship.loa + self.loa_of[:n] + dist + OVERTAKE_LATERAL_M
        if not near.any():
            return None
        near = set(np.flatnonzero(near).tolist())
        for k, other in self.ships.items():
            if k not in near or other is ship or other.state.value not in UNDER_WAY:
                continue
            line = self.lines[k]
            oh, ot = line[-1], line[0]
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

    def _stuck(self, other):
        """Under way but not moving: part of a knot, not a ship waiting at a lock or berth."""
        return other.state.value in UNDER_WAY and other.blocked_steps >= 1

    def _deadlocks(self, sailing):
        """Deadlocks with no way round, after a ship has been blocked DEADLOCK_AFTER steps: it may pass
        its blocker, and every other stuck ship on its way ahead, this step. A pair pointing at each
        other is one case; a knot (ships stopped across each other's way, several abreast, queues
        behind them) is the general one: whenever the blocker is itself stuck under way. Ships
        waiting at a lock or a berth are a queue, not a knot, and are not passed."""
        self.allow = {}
        if not hasattr(self, "squeezed"):
            self.squeezed, self.passing = set(), set()
        for pair in list(self.passing):                # a squeeze lasts until they are clear of each other
            a, b = tuple(pair)
            if a in self.lines and b in self.lines and self._line(self.lines[a]).distance(self._line(self.lines[b])) \
                    < required_gap(self.ships[a].beam, self.ships[b].beam):
                self.allow.setdefault(a, set()).add(b)
                self.allow.setdefault(b, set()).add(a)
            else:
                self.passing.discard(pair)
        for ship in sailing:
            if ship.blocked_steps < SIDESTEP_AFTER:
                continue
            b = self.blocker(ship)
            if b is None:
                continue
            pair = self.head_on(ship, b) or self.blocker(b) is ship
            stopped = b.state.value == "pilot_change"  # lying stopped in the fairway: go round it
            if pair or stopped or self._stuck(b):
                # stand aside into the water that is there, instead of waiting the hour below
                ship.sidestep_m = max(getattr(ship, "sidestep_m", 0.0), self.room_aside(ship, ship.side))
                if b.state.value in UNDER_WAY:
                    b.sidestep_m = max(getattr(b, "sidestep_m", 0.0), self.room_aside(b, b.side))
            if ship.blocked_steps < DEADLOCK_AFTER:
                continue
            if not (pair or self._stuck(b)):
                continue
            k = self._key(ship)
            others = {self._key(b)}
            for c in self.ahead_cells(ship):
                for ko in self.occ.get(c, set()) - {k}:
                    o = self.ships.get(ko)
                    if o is not None and self._stuck(o):
                        others.add(ko)
            for ko in others:
                self.allow.setdefault(k, set()).add(ko)
                self.allow.setdefault(ko, set()).add(k)
                self.passing.add(frozenset((k, ko)))
                o = self.ships.get(ko)
                if o is not None and (ship.id, o.id) not in self.squeezed:
                    self.squeezed.add((ship.id, o.id))
                    ship.note(self.sim.t, "squeeze_past", other=o.id, knot=not pair)

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
                if i_ok > i0:
                    i_ok = self._depth_limit(ship, i0, i_ok)
                heads = ([want[ship.id]] if i_ok == i_want else []) + [float(ship.s[i]) for i in range(i_ok, i0, -1)]
                for h in heads:
                    if h <= ship.head + 1e-6:
                        break
                    swept = self.hull_line(ship, min(ship.head, h - ship.loa), h)
                    side, other = self.free_side(ship, swept, self.hull_cells(ship, swept))
                    if other is None:
                        bad = self.overtaking_violation(ship, h)
                        if bad is not None:
                            other, why = bad
                            if (ship.id, other.id) not in self.denied:
                                self.denied.add((ship.id, other.id))
                                ship.note(self.sim.t, "overtake_denied", other=other.id, why=why)
                    if other is None:
                        ship.side = side
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
            # a ship bound into a lock joins its queue LOCK_WAIT_M before the gate: it waits at the
            # lock's waiting berths in the outer harbour, not in the approach channel, so ships coming
            # out of the lock find the approach free
            end = ship.s[-1] - (LOCK_WAIT_M if ship.lock_index >= 0 else 0.0)
            if ship.head >= end - 1e-6:
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
                if ship.blocked_steps >= LANE_FREE_AFTER and ship.blocked_steps % REROUTE_AFTER == 0 \
                        and not self._queueing(ship):
                    # stuck for hours: a way round that may leave the lanes (the cost of the lanes off)
                    reroutes += 1
                    ship.reroutes += 1
                    avoid = (self.ahead_cells(b) + self.starboard_cells(b)) if b is not None else ()
                    self.sim.reroute_around(ship, avoid=avoid, lanes=False)
                    continue
                due = REROUTE_AFTER * 2 ** min(ship.reroutes, 5)
                if ship.blocked_steps >= due and not self._queueing(ship):
                    reroutes += 1
                    ship.reroutes += 1
                    avoid = (self.ahead_cells(b) + self.starboard_cells(b)) if b is not None else ()
                    self.sim.reroute_around(ship, avoid=avoid)        # overtaking: round its port side
        self._lateral()
        return arrived
