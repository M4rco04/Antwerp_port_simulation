"""The time-stepped simulation (PLAN.md §0): Δt = 5 min, every step in the plan's order

    1. environment     water level at every node (tide), current along the estuary
    2. arrivals        new ships from the generator (containers: schedule replay or fitted NHPP;
                       background NHPP)
    3. VTS             clearance every 3 steps (agents/vts.py, the simple version)
    4. resources       locks step, timers of boarding / pilot change / mooring / handling / dwell
    5. movement        two-phase moves on the mesh (agents/movement.py)
    6. arrivals at the end of a route: station, anchorage, lock, berth, port, exit
    7. logging         events, per-ship records, a time series of queues and utilisation

A voyage: the ship sails (from a sea source to the pilot station, where it asks the VTS; from an
anchorage or a port once cleared) along a route that is split at the locks. At a lock it queues
(Lock.request) and leaves the mesh until the lock lets it out on the other side. At its berth
it moors (tugs, boatmen, the AIS mooring time), is handled (containers: moves / cranes at the
terminal's rate) or dwells (background: lognormal from AIS), then asks to leave and sails to its
exit. Pilots change zone at Vlissingen and at the locks.

Usage:
    py src/sim/engine.py --days 7 --seed 1 [--progress-hours 2] [--max-minutes 60]
Run through src/sim/pipeline.py (results/runs/<id>/, with a viewer). Writes: events.csv, ships.csv, timeseries.csv, summary.json, positions.csv.gz (+ routes.json),
levels.csv.gz
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
for sub in ("src/environment", "src/agents", "src/data"):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

import background_traffic as BT                           # noqa: E402
import navigation_rules as NR                             # noqa: E402
import port_infrastructure as PI                          # noqa: E402
from anchorages import FCFS, TIDE_DEPENDENT, choose_anchorage   # noqa: E402
from currents import CurrentModel                         # noqa: E402
from clearance import node_clearance                      # noqa: E402
from fast_graph import FastGraph                          # noqa: E402
from lanes import Lanes                                   # noqa: E402
from generator import Generator                           # noqa: E402
from locks import ShipRequest                             # noqa: E402
from movement import Mover                                # noqa: E402
from services import PILOT_BOAT_MIN, PilotPool, TugPool, boatmen, pilot_boats   # noqa: E402
from ship import State                                    # noqa: E402
from tide import TideModel                                # noqa: E402
from vts import PLAN_EVERY, SimpleVTS                     # noqa: E402
from weather import Weather                               # noqa: E402
import weather_gates as WG                                # noqa: E402

log = logging.getLogger("sim")

GRAPH = ROOT / "cache" / "antwerp_scheldt_graph.pkl"
DT_MIN = 5.0
LOOKAHEAD_H = 30                       # tide and current computed this far beyond the end (VTS checks)
BOARDING_MIN = 20.0
PILOT_CHANGE_MIN = 10.0
PILOT_BOOK_MARGIN_MIN = 30.0           # pilots for a later stretch are booked from this long before the ETA there
LOCK_TRANSIT_MIN = 60.0                # a lock passage on the way, for those ETAs
OFF_FAIRWAY_ANCHORAGE_M = 5000.0       # a ship that must wait for a pilot waits at an anchorage this close
TERMINAL_FAIR_AFTER_MIN = 24 * 60.0    # once the longest-waiting ship for a terminal has waited this long, later
                                       # ships get no quay there before it (no starving of long / deep ships)
TUG_ORDER_M = 15_000.0
DETOUR_M = 3000.0
MIN_CELL_CLEARANCE_M = 25.0            # every cell has at least this much water to each side (clearance.py)                      # how far ahead a blocked ship looks for a way round                 # order tugs this far before the berth (buoy 35 for arrivals from sea)
PORT_PLACES = ("vlissingen", "terneuzen", "breskens")
SEA_EXITS = ("exit_sea_southwest", "exit_sea_west", "exit_sea_north")
# ULCV rules (regs §8.9, §8.11, JA22)
ULCV_HOLD_LOCKS = ("Zandvliet", "Berendrecht", "Terneuzen", "Hansweert")   # traffic out of them held ...
ULCV_HOLD_M = 5000.0                   # ... while a ULCV passes within this of their river side
ULCV_FALLBACK = ("PSA Noordzee Terminal", "PSA Europa Terminal", "MPET", "DP World Antwerp Gateway")
LOCK_RESERVE_LEAD_MIN = 60.0           # a ULCV's chamber is reserved this long before it reaches the lock
                                       # when its route does not pass CP
STATION_OF_SOURCE = {"sea_north": "pilot_station_steenbank"}      # else Wandelaar
TIDAL_BERTH_MARGIN_M = 1.0             # tidal berths: mean tide above LAT counted on when choosing one
MOVING = (State.TO_STATION, State.TO_ANCHORAGE, State.SAILING)
PILOT_ZONE = {"sea": "sea", "river": "river", "dock": "dock", "canal": "dock"}


class Simulation:
    def __init__(self, start="2026-10-21 00:00", days=7.0, seed=1, delays=True, warmup_days=2.0, background=True,
                 weather_mode="bootstrap", container_mode="replay", container_rate=1.0, bunching=True,
                 routing="lanes"):
        t0 = time.time()
        self.start = pd.Timestamp(start, tz="UTC")
        self.n_steps = int(days * 24 * 60 / DT_MIN)
        self.warmup_min = warmup_days * 24 * 60
        self.rng = np.random.default_rng(seed)
        self.graph = pickle.load(open(GRAPH, "rb"))["graph"]
        self.fg = FastGraph.load(GRAPH.with_suffix(".arrays.npz"), self.graph)
        fg = self.fg
        fg.clearance = node_clearance(fg)
        # routing: "lanes" = hold the starboard side of the buoyed fairway (lanes.py); "shortest" = the
        # shortest allowed path with the plain keep-right preference
        self.routing = routing
        self.lanes = Lanes.for_graph(fg) if routing == "lanes" else None
        # environment: tide at the gauges and current along the estuary, for the whole run + lookahead
        times = pd.date_range(self.start, periods=self.n_steps + int(LOOKAHEAD_H * 60 / DT_MIN) + 1, freq=f"{DT_MIN:g}min")
        self.times = times
        self.tide = TideModel.load()
        fg.bind_tide(self.tide)
        hours = int(len(times) * DT_MIN / 60) + 2
        self.weather = Weather.generate(self.start, hours, self.rng, mode=weather_mode)
        # water levels: tide + the surge the weather drives
        self.L = self.tide.levels(times, weather=self.weather.surge_input)[fg.labels["gauges"]].to_numpy()
        self.A, self.const = fg._tide
        cm = CurrentModel(self.graph, self.tide)
        field = cm.compute(times)
        self.current_u = field.u                       # the physical current (m/s, + = flood)
        # what ships' speed over ground makes of it (AIS, fit_currents.py): in the Zeeschelde pilots
        # take back part of a fair or foul current, so their SOG swings less than the current
        response = cm.cal.get("sog_response", {})
        self.current_sog_u = field.u * np.array([response.get(r, 1.0) for r in cm.reach])[None, :]
        self.slice_of = np.full(fg.n, -1, dtype=np.int64)
        for n, j in field.slice_of.items():
            self.slice_of[n] = j
        g = fg.labels["gauges"].index("antwerpen.loodsgebouw")
        self.hw_series = self.L[:, g]
        self.dock_speed_kn = 5.0
        # resources
        self.locks = {d["name"]: (n, d["lock"]) for n, d in self.graph.nodes(data=True) if d["type"] == "lock"}
        self.lock_of_node = {n: lock for n, lock in self.locks.values()}
        self.anchorages = {name: self.graph.nodes[n]["anchorage"] for name, n in self.graph.graph["anchorages"].items()}
        self.anchorage_node = dict(self.graph.graph["anchorages"])
        self.terminals = {t["name"]: t["resource"] for t in self.graph.graph["terminals"]}
        for T in self.terminals.values():              # the harbour master's limits of each quay slot
            for b, r in T.berths.items():
                r.setdefault("max_draught", self.graph.graph["berths"].get(b, {}).get("max_draught_m"))
                r.setdefault("category", self.graph.graph["berths"].get(b, {}).get("category"))
        self.berths = self.graph.graph["berths"]
        self.berth_ship = {}
        self.places = self.graph.graph["places"]
        self.destinations = self.graph.graph["destinations"]
        self.pilots = PilotPool()
        self.pilot_boats = pilot_boats()
        self.boatmen = boatmen()
        self.tugs = TugPool(self.places)
        self.tugs.bind(lambda n: (float(fg.x[n]), float(fg.y[n])))
        # agents
        self.mover = Mover(self)
        self.vts = SimpleVTS(self)
        self.generator = Generator(self.start, self.rng, delays=delays, background=background,
                                   container_mode=container_mode, rate_factor=container_rate, bunching=bunching)
        if self.generator.nhpp:
            f = self.generator.nhpp
            log.info("container arrivals: fitted Poisson process, %.2f calls/day x %.2f%s",
                     f["base_per_h"] * 24, f["rate_factor"],
                     f", daily gamma factor shape {f['gamma_shape']:.1f}" if f["gamma_shape"] else "")
        self.ships, self.done, self.by_id = [], [], {}
        self.route_cache, self.failed, self.reachable = {}, {}, {}
        self.held_exits = {}                           # lock name -> ships kept in it during a ULCV passage
        self.hold_chainage = {}
        river = fg.mask("region", "river")
        for name in ULCV_HOLD_LOCKS:
            if name in self.locks:
                n = self.locks[name][0]
                near = river & (np.hypot(fg.x - fg.x[n], fg.y - fg.y[n]) < 3000.0)
                if near.any():
                    self.hold_chainage[name] = float(np.nanmedian(fg.chainage_m[near]))
        self.level_high = np.asarray(self.A @ self.L[:int(25 * 60 / DT_MIN)].max(axis=0)).ravel() + self.const
        river = np.flatnonzero(fg.region == fg.code("region", "river")) if "region" in fg.labels else np.arange(fg.n)
        self.reach_from = int(river[np.argmax(fg.depth_m[river])])      # the deepest cell of the main channel
        self.events, self.series, self.positions = [], [], []
        self.routes_rec, self._last_pos = [], {}
        self.terminal_waiting = {}                     # terminal -> {ship id: since when it waits for quay}   # routes sailed (node lists) and last fixed position per ship
        self.t, self.k = 0.0, 0
        self.level_now = self._levels(0)
        log.info("simulation ready in %.0f s: %d steps, pilots %s, %d pilot boats, %d boatmen crews, %d tugs",
                 time.time() - t0, self.n_steps, self.pilots.sizes, self.pilot_boats.n, self.boatmen.n, len(self.tugs.tugs))

    # ------------------------------------------------------------------ environment
    def _levels(self, k):
        return np.asarray(self.A @ self.L[min(k, len(self.L) - 1)]).ravel() + self.const

    def level_along(self, nodes, t_min):
        ti = np.clip(np.round(np.asarray(t_min) / DT_MIN).astype(int), 0, len(self.L) - 1)
        rows = self.A[np.asarray(nodes)]
        return np.asarray(rows.multiply(self.L[ti]).sum(axis=1)).ravel() + self.const[np.asarray(nodes)]

    def tide_phase(self):
        """(rising, hours since the last high water) at Antwerp."""
        h = self.hw_series
        k = self.k
        rising = k > 0 and h[k] > h[k - 1]
        j = k
        while j > 1 and not (h[j] >= h[j - 1] and h[j] >= h[min(j + 1, len(h) - 1)]):
            j -= 1
        return rising, (k - j) * DT_MIN / 60.0

    def pilot_zone(self, node):
        return PILOT_ZONE.get(self.mover.zone_label[node], "river")

    # ------------------------------------------------------------------ routes
    def route(self, start, target, ship, level=None, mask=None, lanes=True):
        fg = self.fg
        profile = self.lane_profile(ship) if lanes else None
        key = (start, target, round(ship.need_m * 2) / 2, math.ceil(ship.loa / 25), math.ceil(ship.beam / 5), profile)
        if level is None and mask is None and key in self.route_cache:
            return self.route_cache[key]
        if level is not None and mask is None and self.failed.get(key, -1) == self.k // 12:
            return None                                # failed at a water level this hour already
        import networkx as nx
        r = None
        wide = ship.beam / 2 if ship.beam / 2 > MIN_CELL_CLEARANCE_M else None
        for clearance in ((wide, None) if wide else (None,)):
            try:
                r = fg.route(start, target, ship.draught, ship.ukc_m, ship.loa, ship.beam, level=level, nodes_mask=mask,
                             keep_right=True, min_clearance=clearance,
                             lane_factor=self.lanes.factor(fg, profile) if self.lanes is not None and profile else None)
                if wide and clearance is None:
                    ship.note(self.t, "narrow_route", beam=ship.beam)    # no route with room for its beam
                break
            except nx.NetworkXNoPath:
                continue
        if level is None and mask is None:
            self.route_cache[key] = r
        elif r is None and mask is None:
            self.failed[key] = self.k // 12
        return r

    def lane_profile(self, ship):
        """Which lane a ship holds (lanes.py): inland craft at or beyond the main fairway's starboard
        edge or in the side channels, small sea-going ships (no compulsory pilot) near the starboard
        edge or in the side channels, ULCVs and tide-dependent ships more towards the middle, other
        ships in the middle of the starboard half. None when routing is "shortest"."""
        if self.lanes is None:
            return None
        if not ship.sea_going:
            return "inland"
        if ship.ulcv or ship.tide_dependent:
            return "wide"
        if not ship.needs_pilot:                       # small sea-going ships may take the side channels
            return "small"
        return "sea"

    def now_ts(self, minutes=None):
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

    def approach_route(self, start, station):
        """Sea source -> pilot station: open sea, not draught-limited here (the VTS checks the
        voyage from the station)."""
        key = ("approach", start, station)
        if key not in self.route_cache:
            import networkx as nx
            try:
                self.route_cache[key] = self.fg.route(start, station, 0.0, 0.0, keep_right=False)
            except nx.NetworkXNoPath:
                self.route_cache[key] = None
        return self.route_cache[key]

    def plan_route(self, ship, now):
        """Route for the ship's next voyage from where it lies: at LAT if that works (cached),
        else at the current water level."""
        target = self.choose_target(ship)
        if target is None or ship.at is None:
            return None
        ship.target = target
        return self.route(ship.at, target, ship) or self.route(ship.at, target, ship, level=self.level_now)

    # ------------------------------------------------------------------ destinations
    def _berth_fits(self, b, ship, ignore_tanker=False):
        """May this ship use this berth? The harbour master's data where it exists (allowed draught,
        category, maximum length / beam, tanker quays), else the berth's size and depth."""
        if not b["nodes"] or b.get("berth_type") == "Sluis":   # lock chambers are not berths
            return False
        category = b.get("category")
        if category:
            if ship.sea_going and category != "zeevaart":
                return False                               # inland craft may use sea-going berths too
        elif ship.sea_going and b["size_class"] != "seagoing" or not ship.sea_going and b["size_class"] == "small_craft":
            return False
        tanker = ship.cls in ("tanker", "inland_tanker")
        if not ignore_tanker and (tanker and not b["tanker_berth"] or not tanker and b["tanker_berth"]):
            return False
        if b.get("max_loa_m") and ship.loa > float(b["max_loa_m"]) or b.get("max_beam_m") and ship.beam > float(b["max_beam_m"]):
            return False
        if b.get("max_draught_m") is not None:
            if ship.draught > b["max_draught_m"]:
                return False
        else:
            depth = b["depth_m"] if b["depth_m"] is not None else 0.0
            depth += float(self.level_now[b["nodes"][0]]) if b["tidal"] is False else TIDAL_BERTH_MARGIN_M
            if depth < ship.draught + 0.3:
                return False
        length = b.get("berth_length_m") or b["length_m"]
        if length < 0.5 * ship.loa:
            return False
        return self.berth_reachable(b, ship)

    def berth_reachable(self, b, ship):
        """Can the ship get to this berth at all (from the river at Vlissingen)?"""
        return self.reachable_between(self.reach_from, b["nodes"][len(b["nodes"]) // 2], ship)

    def reach(self, ship):
        """Nodes a ship of this draught and size can reach from the river at Vlissingen at the
        highest water of the first tide; one search per draught / size class, cached."""
        need = math.ceil(ship.need_m * 2) / 2
        key = (need, math.ceil(ship.loa / 50) * 50, math.ceil(ship.beam / 5) * 5)
        if key not in self.reachable:
            self.reachable[key] = self.fg.reachable(self.reach_from, need, 0.0, key[1], key[2], level=self.level_high)
        return self.reachable[key]

    def reachable_between(self, a, b, ship):
        """Is there a route a -> b for this ship at high water? Both ends reachable from the river
        (passing rules are the same both ways)."""
        r = self.reach(ship)
        return bool(r[a] and r[b])

    def choose_target(self, ship):
        """Node the next voyage ends at, and what is reserved there (ship.berth, tentatively)."""
        if ship.departing:
            options = [ship.exit or "exit_sea_north"] + [e for e in SEA_EXITS if e != ship.exit]
            for exit_ in options:
                name = exit_[5:]
                if name in self.places and (ship.at is None or
                                            self.reachable_between(ship.at, self.places[name]["node"], ship)):
                    if exit_ != ship.exit:
                        ship.note(self.t, "exit_changed", planned=ship.exit, new=exit_)
                        ship.exit = exit_
                    return self.places[name]["node"]
            ship.infeasible = "no exit reachable at high water"
            return None
        if ship.berth:                                 # already chosen (re-planning)
            return ship.berth["node"]
        if ship.terminal:
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
            queue = self.terminal_waiting.setdefault(T.name, {})
            if s0 is None:
                queue.setdefault(ship.id, self.t)      # quay full: wait, in this terminal's queue
                return None
            first = min(queue, key=queue.get) if queue else None
            waited = self.t - queue[first] if first is not None else 0.0
            if (first is not None and first != ship.id and waited >= TERMINAL_FAIR_AFTER_MIN and first in self.by_id
                    and self.by_id[first].state != State.EXITED):
                queue.setdefault(ship.id, self.t)      # an earlier ship has waited a day: it goes first
                return None
            queue.pop(ship.id, None)
            # the cell to sail to: on a suitable slot under the ship, reachable, nearest its middle
            ok = {b for b, r in T.berths.items() if (r.get("max_draught") is None or r["max_draught"] >= ship.draught)
                  and (not ship.sea_going or r.get("category") in (None, "zeevaart"))}
            nodes = sorted({n for b in T.berths_at(s0, s0 + ship.loa) if b in ok for n in T.berths[b]["nodes"]})
            reach = self.reach(ship)
            nodes = [n for n in nodes if reach[n]]
            if not nodes:
                return None
            mid = T.nodes_at(s0, s0 + ship.loa)
            mid = mid[len(mid) // 2] if mid else nodes[0]
            node = min(nodes, key=lambda n: math.hypot(self.fg.x[n] - self.fg.x[mid], self.fg.y[n] - self.fg.y[mid]))
            ship.candidate = {"kind": "terminal", "s0": s0, "node": node, "nodes": nodes}
            return ship.candidate["node"]
        zone = ship.berth_zone or ship.destination
        if zone in SEA_EXITS and ship.at is not None and not self.reachable_between(ship.at, self.places[zone[5:]]["node"], ship):
            for alt in SEA_EXITS:                      # through traffic too deep for this sea exit: another one
                if self.reachable_between(ship.at, self.places[alt[5:]]["node"], ship):
                    ship.note(self.t, "exit_changed", planned=zone, new=alt)
                    ship.destination = zone = alt
                    break
        if zone.startswith("exit_") or zone in self.places:
            name = zone[5:] if zone.startswith("exit_") else zone
            if name in self.places:
                kind = "place" if name in PORT_PLACES and not zone.startswith("exit_") else "exit"
                ship.candidate = {"kind": kind, "node": self.places[name]["node"], "name": name}
                return ship.candidate["node"]
        dest = self.destinations.get(zone)
        if not dest:
            return None
        ids = dest["berths"]
        fits = [b for b in ids if self._berth_fits(self.berths[b], ship)]
        if not fits:                                   # nothing fits even empty: relax the tanker rule
            fits = [b for b in ids if self._berth_fits(self.berths[b], ship, ignore_tanker=True)]
        if not fits and ship.sea_going:
            ship.infeasible = f"no berth in {zone} fits or can be reached"
            return None
        free = [b for b in fits if b not in self.berth_ship]
        pick = None
        if free:
            pick = free[int(self.rng.integers(len(free)))]
        else:
            loose = [b for b in ids if self._berth_fits(self.berths[b], ship, ignore_tanker=True) and b not in self.berth_ship]
            if loose:
                pick = loose[int(self.rng.integers(len(loose)))]
        if pick is None:
            if ship.sea_going:
                return None                            # wait for a berth (at anchor)
            node = dest["node"]                        # inland craft: lie alongside at the zone
            ship.candidate = {"kind": "berth", "id": None, "node": node, "nodes": [node], "zone": zone}
            return node
        b = self.berths[pick]
        ship.candidate = {"kind": "berth", "id": pick, "node": b["nodes"][len(b["nodes"]) // 2], "nodes": b["nodes"], "zone": zone}
        return ship.candidate["node"]

    def destination_free(self, ship):
        return ship.departing or ship.berth is not None or self.choose_target(ship) is not None

    def reserve_destination(self, ship, now):
        c = getattr(ship, "candidate", None)
        if ship.departing or ship.berth or c is None:
            return
        if c["kind"] == "terminal":
            T = self.terminals[ship.terminal]
            if T.moor(ship.id, ship.loa, now, s0=c["s0"]) is None:
                return
        elif c["kind"] == "berth" and c["id"]:
            self.berth_ship[c["id"]] = ship.id
        ship.berth = c

    # ------------------------------------------------------------------ pilots
    def pilot_plan(self, ship, route, now):
        """The later pilot stretches of a voyage: [(zone, ETA)] at each change of pilot zone along the
        route, sailing at its planning speed plus LOCK_TRANSIT_MIN per lock before the change."""
        fg = self.fg
        r = np.asarray(route, dtype=np.int64)
        if len(r) < 2:
            return []
        if getattr(self, "_pz_code", None) is None:              # pilot zone per node, once
            names = ("sea", "river", "dock")
            self._pz_names = names
            self._pz_code = np.array([names.index(self.pilot_zone(n)) for n in range(fg.n)], dtype=np.int8)
            self._is_lock = np.zeros(fg.n, dtype=bool)
            self._is_lock[list(self.lock_of_node)] = True
        d = np.r_[0.0, np.cumsum(np.hypot(np.diff(fg.x[r]), np.diff(fg.y[r])))]
        locks = np.cumsum(self._is_lock[r])
        keep = ~self.mover.special[r] & ~self._is_lock[r]
        idx = np.flatnonzero(keep)
        if len(idx) < 2:
            return []
        z = self._pz_code[r[idx]]
        ch = np.flatnonzero(z[1:] != z[:-1]) + 1
        v = ship.stw_kn("river", NR.planning_speed_kn) * 1852.0 / 60.0
        return [(self._pz_names[z[k]], now + d[idx[k]] / v + locks[idx[k]] * LOCK_TRANSIT_MIN) for k in ch]

    def pilot_available(self, ship, start_node, now, route=None):
        """A pilot for the first stretch now (and a pilot boat for a boarding at sea / Vlissingen), and,
        with the route, pilots that can be booked for every later stretch when the ship gets there."""
        if not ship.needs_pilot:
            return True
        zone = self.pilot_zone(start_node)
        boat = ship.state in (State.WAIT_CLEARANCE, State.ANCHORED) and not ship.departing and zone in ("sea", "river")
        if not (self.pilots.available(zone, ship.pilots_needed(zone), now, ship.id)
                and (not boat or self.pilot_boats.available(now) > 0)):
            return False
        if route is not None:
            for z, eta in self.pilot_plan(ship, route, now):
                if not self.pilots.can_book(z, ship.pilots_needed(z), eta - PILOT_BOOK_MARGIN_MIN, now):
                    return False
        return True

    def book_pilots(self, ship, route, now):
        """Book the pilots for the later stretches; False (and nothing booked) if one cannot be."""
        for z, eta in self.pilot_plan(ship, route, now):
            if not self.pilots.book(z, ship.pilots_needed(z), ship.id, eta - PILOT_BOOK_MARGIN_MIN, now):
                self.pilots.cancel(ship.id)
                return False
            ship.note(now, "pilot_booked", zone=z, eta_min=round(eta - now))
        return True

    def wait_for_pilot(self, ship, zone, now):
        """No pilot for the next stretch: the ship gets out of the fairway and waits, at an anchorage
        within OFF_FAIRWAY_ANCHORAGE_M (Vlissingen roads, Schaar van Ouden Doel, ...) on the river or at
        sea, or off the mesh where it is in the docks; it carries on when a pilot is free."""
        head = ship.cells[-1] if ship.cells else ship.at
        self.mover.release(ship)
        node = head
        if zone in ("sea", "river") and head is not None:
            near = [(math.hypot(self.fg.x[a] - self.fg.x[head], self.fg.y[a] - self.fg.y[head]), a)
                    for a in self.anchorage_node.values()]
            near = [x for x in near if x[0] <= OFF_FAIRWAY_ANCHORAGE_M]
            if near:
                node = min(near)[1]
        ship.at, ship.off_fairway, ship.wait_zone = node, True, zone
        ship.set_state(State.WAIT_PILOT, now, zone=zone)
        ship.note(now, "wait_pilot_off_fairway", zone=zone, at=int(node) if node is not None else None)

    def take_pilots(self, ship, zone, now, boat=False):
        if boat and not self.pilot_boats.take(now, PILOT_BOAT_MIN):
            return False
        got = self.pilots.take(zone, ship.pilots_needed(zone), ship.id, now)
        if got is None:
            return False
        ship.pilots, ship.pilot_zone = got, zone
        return True

    def drop_pilots(self, ship, now):
        if ship.pilots:
            self.pilots.release(ship.pilots, now)
            ship.note(now, "pilot_off", zone=ship.pilot_zone)
        ship.pilots, ship.pilot_zone = [], None

    # ------------------------------------------------------------------ life cycle
    def terminal_draught(self, ship):
        """A container ship's draught drawn from its TEU can exceed what its terminal allows; a real one
        calls loaded to what the quay allows. Capped at the deepest allowed draught of a stretch of
        quay long enough for it (unchanged when that is deeper)."""
        if ship.cls != "container" or not ship.terminal or ship.terminal not in self.terminals:
            return
        T = self.terminals[ship.terminal]
        fits = lambda d: any(b - a >= ship.loa for a, b in T.suitable_intervals(d, ship.sea_going))
        if fits(ship.draught):
            return
        allowed = sorted({r["max_draught"] for r in T.berths.values() if r.get("max_draught")}, reverse=True)
        cap = next((d for d in allowed if d < ship.draught and fits(d)), None)
        if cap is not None:
            ship.note(self.t, "draught_capped", drawn=ship.draught, allowed=cap, terminal=T.name)
            ship.draught = float(cap)

    def spawn(self, ship):
        now = self.t
        self.terminal_draught(ship)
        ship.set_state(State.SPAWNED, now, source=ship.source, destination=ship.destination, cls=ship.cls)
        self.ships.append(ship)
        self.by_id[ship.id] = ship
        place = self.places.get(ship.source)
        if place is None:
            self.finish(ship, now, "no_source")
            return
        node = place["node"]
        # an anchorage source on an anchorage node starts at anchor; "anchorage_other" (AIS: anchored
        # somewhere else) lies on a sea cell and starts at sea like the other arrivals
        if ship.source.startswith("anchorage_") and self.graph.nodes[node].get("type") == "anchorage":
            ship.at = node
            name = self.graph.nodes[node]["name"]
            ship.request_t = now
            self.anchor(ship, name, now)
            if ship.state != State.ANCHORED:
                self.go(ship, now)
            elif ship.needs_pilot:
                self.vts.request(ship, now)            # it waits at anchor for its clearance like any arrival
            else:                                      # no pilot needed: it weighs anchor and sails
                self.anchorages[ship.anchorage].leave(ship.id, now)
                ship.anchorage = None
                ship.set_state(State.WAIT_CLEARANCE, now)
                self.go(ship, now)
            return
        ship.at = node
        sea = self.mover.zone_label[node] == "sea" or self.graph.nodes[node]["region"] == "sea"
        if sea and ship.needs_pilot:
            name = STATION_OF_SOURCE.get(ship.source, "pilot_station_wandelaar")
            station = self.places[name]["node"]
            if name != "pilot_station_wandelaar" and not self.reachable_between(station, self.reach_from, ship):
                station = self.places["pilot_station_wandelaar"]["node"]
                ship.note(now, "station_changed", to="pilot_station_wandelaar")
            r = self.approach_route(node, station)
            if r is None:
                self.finish(ship, now, "no_route_to_station")
                return
            self.sail(ship, r, State.TO_STATION, now)
            return
        self.go(ship, now)

    def go(self, ship, now):
        """Ask the VTS (pilot ships) or just leave (others)."""
        if ship.needs_pilot:
            ship.set_state(State.WAIT_CLEARANCE, now) if ship.state != State.ANCHORED else None
            self.vts.request(ship, now)
            return
        route = self.plan_route(ship, now)
        if route is None:
            ship.retries = getattr(ship, "retries", 0) + 1
            if ship.retries == 1 or ship.retries % 10 == 0:
                ship.note(now, "no_route_or_berth", tries=ship.retries)
            ship.retry_at = now + min(30.0 * 2 ** min(ship.retries - 1, 4), 480.0)
            if ship.state != State.WAIT_CLEARANCE:
                ship.set_state(State.WAIT_CLEARANCE, now)
            return
        self.reserve_destination(ship, now)
        self.start_voyage(ship, route, now)

    def reserve_ulcv_lock(self, ship, route, now):
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
            self.reserve_ulcv_lock(ship, route, now)
        self.reserve_destination(ship, now)
        zone = self.pilot_zone(route[0])
        ship.at_station = False
        if ship.state == State.ANCHORED:
            self.anchorages[ship.anchorage].leave(ship.id, now)
            ship.note(now, "anchor_up", anchorage=ship.anchorage)
            ship.at = self.anchorage_node[ship.anchorage]
            ship.anchorage = None
            route = self.route(ship.at, ship.target, ship) or self.route(ship.at, ship.target, ship, level=self.level_now) or route
        boat = not ship.departing and zone in ("sea", "river")
        if ship.needs_pilot and not self.book_pilots(ship, route, now):
            self.vts.request(ship, now)                # a later pilot went to another ship this round
            return
        if ship.needs_pilot and not self.take_pilots(ship, zone, now, boat=boat):
            self.pilots.cancel(ship.id)
            self.vts.request(ship, now)                # lost the pilot to another ship this round
            return
        ship.pending_route = route
        if ship.departing:
            self.start_unmooring(ship, now)
        else:
            ship.set_state(State.BOARDING, now, zone=zone)
            ship.timer = BOARDING_MIN

    def start_voyage(self, ship, route, now):
        ship.pending_route = None
        self.sail(ship, route, State.SAILING, now)

    def sail(self, ship, route, state, now):
        ship.full_route = list(route)
        ship.seg_start = 0
        self._segment(ship)
        ship.at = None
        ship.set_state(state, now)
        if not self.mover.place(ship):
            ship.waiting_space = True

    def _segment(self, ship):
        """The part of full_route from seg_start up to the node before the next lock."""
        r = ship.full_route
        end = len(r) - 1
        for i in range(ship.seg_start + 1, len(r)):
            if r[i] in self.lock_of_node:
                end = i - 1
                break
        ship.route = r[ship.seg_start:end + 1]
        xy = np.column_stack([self.fg.x[ship.route], self.fg.y[ship.route]])
        ship.s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
        ship.head = 0.0
        ship.lock_index = end + 1 if end + 1 < len(r) and r[end + 1] in self.lock_of_node else -1

    def reroute_around(self, ship, avoid=(), lanes=True):
        """Blocked for several steps: a detour round the cells other ships hold, within DETOUR_M,
        back onto its own route beyond the blockage (or to the end of this part of the route)."""
        fg, mover = self.fg, self.mover
        i = int(np.searchsorted(ship.s, ship.head, side="right")) - 1
        here = ship.route[i]
        j = min(int(np.searchsorted(ship.s, ship.head + DETOUR_M)), len(ship.route) - 1)
        free = mover.free_mask(ship)                   # cells no other hull covers
        avoid_set = set(avoid)
        while j > i + 1 and (not free[ship.route[j]] or ship.route[j] in avoid_set):
            j -= 1
        if j <= i + 1:
            return
        rejoin = ship.route[j]
        near = np.hypot(fg.x - fg.x[here], fg.y - fg.y[here]) <= 1.2 * DETOUR_M
        mask = near & free
        if len(avoid):
            mask[np.asarray(list(avoid))] = False
        r = self.route(here, rejoin, ship, level=self.level_now, mask=mask, lanes=lanes)
        if r is None or len(r) < 2:
            return
        mover.release(ship)
        rest = ship.full_route[ship.seg_start + j + 1:]
        ship.full_route = list(ship.full_route[:ship.seg_start + i]) + r + rest
        ship.seg_start = ship.seg_start + i
        self._segment(ship)
        if not mover.place(ship):
            ship.waiting_space = True
        # blocked_steps is not reset here: only moving resets it, so a ship that keeps finding detours
        # without getting anywhere still reaches the deadlock release
        ship.note(self.t, "reroute" if lanes else "reroute_without_lanes")

    def send_to_anchorage(self, ship, now):
        pool = choose_anchorage(self.anchorages, ship.loa, ship.draught, dangerous_signals=ship.dg == "A",
                                tide_dependent=ship.tide_dependent, level_m=0.0)
        here = ship.at
        for a in sorted(pool, key=lambda a: math.hypot(self.fg.x[self.anchorage_node[a.name]] - self.fg.x[here],
                                                       self.fg.y[self.anchorage_node[a.name]] - self.fg.y[here])):
            r = self.route(here, self.anchorage_node[a.name], ship)
            if r is not None:
                ship.anchor_target = a.name
                self.sail(ship, r, State.TO_ANCHORAGE, now)
                return
        ship.note(now, "no_anchorage")

    def anchor(self, ship, name, now):
        a = self.anchorages[name]
        prio = TIDE_DEPENDENT if ship.tide_dependent else FCFS
        if a.arrive(ship.id, ship.loa, ship.draught, now, priority=prio) is None:
            ship.note(now, "anchorage_full", anchorage=name)
            return False
        a.request_pilot(ship.id, now, priority=prio)
        ship.anchorage = name
        ship.at = self.anchorage_node[name]
        ship.set_state(State.ANCHORED, now, anchorage=name)
        return True

    def start_unmooring(self, ship, now):
        ship.set_state(State.UNMOORING, now)
        ship.timer = None                              # set once tugs and boatmen are there
        ship.needs_tugs = ship.tugs_needed(departing=True) + WG.extra_tugs(ship, self.weather, self.now_ts(now))

    def finish(self, ship, now, how="exited"):
        if ship.anchorage:
            self.anchorages[ship.anchorage].leave(ship.id, now)
            ship.anchorage = None
        self.mover.release(ship)
        self.drop_pilots(ship, now)
        self.pilots.cancel(ship.id)
        for q in self.terminal_waiting.values():
            q.pop(ship.id, None)
        self.vts.withdraw(ship)
        ship.set_state(State.EXITED, now, how=how)
        self.ships.remove(ship)
        self.done.append(ship)

    # ------------------------------------------------------------------ per-step handlers
    def _arrive_end(self, ship, now):
        """The ship reached the end of its route part."""
        if ship.lock_index >= 0:
            lock_node = ship.full_route[ship.lock_index]
            lock = self.lock_of_node[lock_node]
            side = lock.side_of(ship.route[-1]) or "a"
            prio = 2 if ship.tide_dependent else 4
            high = max(float(np.mean(self.level_now[d["nodes"]])) for d in lock.sides.values() if d["nodes"])
            try:
                lock.request(ShipRequest(ship.id, ship.loa, ship.beam, ship.draught, side, prio,
                                         container=ship.cls == "container"), now, level_m=high)
            except ValueError:
                ship.note(now, "lock_does_not_fit", lock=lock.name)
                self.finish(ship, now, "lock_does_not_fit")
                return
            ship.lock = lock.name
            self.mover.release(ship)                   # waits at the lock's waiting berths, off the fairway
            ship.set_state(State.LOCK_QUEUE, now, lock=lock.name, side=side)
            return
        if ship.state == State.TO_STATION:
            ship.at = ship.route[-1]
            self.mover.release(ship)
            ship.set_state(State.WAIT_CLEARANCE, now)
            ship.at_station = True
            self.vts.request(ship, now)
            return
        if ship.state == State.TO_ANCHORAGE:
            self.mover.release(ship)
            ship.at = ship.route[-1]
            if not self.anchor(ship, ship.anchor_target, now):
                ship.set_state(State.WAIT_CLEARANCE, now)
                self.send_to_anchorage(ship, now)
            return
        if ship.departing or (ship.berth or {}).get("kind") == "exit":
            self.finish(ship, now)
            return
        b = ship.berth or {}
        if b.get("kind") == "place":
            self.mover.release(ship)
            self.drop_pilots(ship, now)
            ship.at = ship.route[-1]
            ship.set_state(State.DWELL_PORT, now, place=b["name"])
            ship.timer = 60.0 * BT.sample_berth_dwell(ship.cls, self.rng, b["name"])
            return
        # a berth: moor
        self.mover.release(ship)                       # moored alongside the quay: off the route cells
        ship.at = ship.route[-1]
        ship.set_state(State.MOORING, now, berth=b.get("id") or ship.terminal)
        ship.timer = None
        ship.needs_tugs = ship.tugs_needed() + WG.extra_tugs(ship, self.weather, self.now_ts(now))

    def _berth_area(self, ship):
        b = ship.berth or {}
        if b.get("kind") == "terminal":
            return "tidal"
        bid = b.get("id")
        return "dock" if bid and self.berths[bid]["tidal"] is False else "tidal"

    def _service_ready(self, ship, now, kind):
        """Tugs and boatmen for mooring / unmooring; True when the manoeuvre can start."""
        x, y = float(self.fg.x[ship.at]), float(self.fg.y[ship.at])
        if getattr(ship, "needs_tugs", 0) and not ship.tugs:
            tugs, ready = self.tugs.request(ship.needs_tugs, x, y, ship.id, now)
            if tugs is None:
                return False
            ship.tugs, ship.tugs_ready_at = tugs, ready
            ship.note(now, "tugs_assigned", n=len(tugs), ready_in_min=round(ready - now, 1))
        if ship.tugs and ship.tugs_ready_at > now:
            return False
        if ship.needs_boatmen and self._berth_area(ship) == "dock" and not getattr(ship, "has_boatmen", False):
            if not self.boatmen.hold(now):
                return False
            ship.has_boatmen = True
        return True

    def _release_services(self, ship, now):
        if ship.tugs:
            self.tugs.release(ship.tugs, float(self.fg.x[ship.at]), float(self.fg.y[ship.at]), now)
            ship.tugs, ship.tugs_ready_at = [], None
        if getattr(ship, "has_boatmen", False):
            self.boatmen.release(now)
            ship.has_boatmen = False

    def _timers(self, now):
        rising, after_hw = self.tide_phase()
        cranes_stopped = WG.cranes_stopped(self.weather, self.now_ts(now))
        for ship in list(self.ships):
            st = ship.state
            if st == State.BOARDING:
                ship.timer -= DT_MIN
                if ship.timer <= 0:
                    self.start_voyage(ship, ship.pending_route, now)
            elif st == State.PILOT_CHANGE:
                ship.timer -= DT_MIN
                if ship.timer <= 0:
                    if getattr(ship, "off_fairway", False):   # back from waiting off the fairway
                        route = self.plan_route(ship, now)
                        if route is None:
                            ship.timer = DT_MIN                # no water yet: try again next step
                            continue
                        ship.off_fairway = False
                        self.sail(ship, route, State.SAILING, now)
                    else:
                        ship.set_state(State.SAILING, now)
            elif st == State.WAIT_PILOT:
                zone = getattr(ship, "wait_zone", None) or self.pilot_zone(ship.cells[-1] if ship.cells else ship.route[-1])
                if self.take_pilots(ship, zone, now, boat=ship.pilot_change_boat):
                    ship.set_state(State.PILOT_CHANGE, now, zone=zone)
                    ship.timer = PILOT_CHANGE_MIN
            elif st == State.MOORING:
                if ship.timer is None:
                    T = self.terminals.get(ship.terminal) if (ship.berth or {}).get("kind") == "terminal" else None
                    if T and not T.berthing_allowed(ship.loa, ship.berth["s0"], rising, after_hw):
                        continue
                    if not self._service_ready(ship, now, "arrival"):
                        continue
                    ship.timer = PI.mooring_minutes(ship.loa, "arrival", self._berth_area(ship), self.rng)
                ship.timer -= DT_MIN
                if ship.timer <= 0:
                    self._release_services(ship, now)
                    self.drop_pilots(ship, now)
                    self._moored(ship, now)
            elif st == State.AT_BERTH:
                if ship.timer is None:                 # container waiting for cranes
                    self._start_handling(ship, now)
                    continue
                if ship.terminal and cranes_stopped:   # STS cranes stopped by the wind
                    continue
                ship.timer -= DT_MIN
                if ship.timer <= 0:
                    self._ready_to_leave(ship, now)
            elif st == State.UNMOORING:
                if ship.timer is None:
                    T = self.terminals.get(ship.terminal) if (ship.berth or {}).get("kind") == "terminal" else None
                    if T and not T.departure_allowed(ship.id, rising, after_hw):
                        continue
                    if not self._service_ready(ship, now, "departure"):
                        continue
                    ship.timer = PI.mooring_minutes(ship.loa, "departure", self._berth_area(ship), self.rng)
                ship.timer -= DT_MIN
                if ship.timer <= 0:
                    self._release_services(ship, now)
                    self._leave_berth(ship, now)
                    self.start_voyage(ship, ship.pending_route, now)
            elif st == State.DWELL_PORT:
                ship.timer -= DT_MIN
                if ship.timer <= 0:
                    ship.departing = True
                    ship.exit = BT.sample_exit(ship.cls, self.rng, ship.berth["name"]) if ship.cls in BT.P_EXIT_GIVEN_CLASS else "exit_sea_north"
                    ship.berth = None
                    self.go(ship, now)
            elif st == State.WAIT_CLEARANCE and not ship.needs_pilot and now >= getattr(ship, "retry_at", 0):
                self.go(ship, now)

    def _moored(self, ship, now):
        b = ship.berth
        ship.set_state(State.AT_BERTH, now, berth=b.get("id") or ship.terminal)
        if b.get("kind") == "terminal":
            ship.timer = None
            self._start_handling(ship, now)
        else:
            hours = ship.dwell_h or BT.sample_berth_dwell(ship.cls, self.rng, b.get("zone"))
            ship.timer = 60.0 * hours

    def _start_handling(self, ship, now):
        T = self.terminals[ship.terminal]
        n = T.assign_cranes(ship.id, ship.cranes_wanted)
        if n == 0:
            return
        ship.timer = 60.0 * T.handling_hours(ship.moves, n)
        ship.note(now, "handling", cranes=n, moves=ship.moves, hours=round(ship.timer / 60, 1))

    def _ready_to_leave(self, ship, now):
        ship.departing = True
        zone = (ship.berth or {}).get("zone") or ("antwerp_deurganckdok" if ship.terminal in ("MPET", "DP World Antwerp Gateway") else "antwerp_river_quays")
        cls = ship.cls if ship.cls in BT.P_EXIT_GIVEN_CLASS else "bulk_general"
        ship.exit = BT.sample_exit(cls, self.rng, zone)
        ship.mark("ready", now)
        ship.set_state(State.WAIT_CLEARANCE, now, departing=True)
        if ship.needs_pilot:
            self.vts.request(ship, now)
        else:
            route = self.plan_route(ship, now)
            if route is None:
                ship.retry_at = now + 30
                return
            ship.pending_route = route
            self.start_unmooring(ship, now)

    def _leave_berth(self, ship, now):
        b = ship.berth or {}
        if b.get("kind") == "terminal":
            self.terminals[ship.terminal].unmoor(ship.id, now)
        elif b.get("id"):
            self.berth_ship.pop(b["id"], None)
        self.mover.release(ship)
        ship.berth = None

    def ulcv_passing(self, name):
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
        for name, (node, lock) in self.locks.items():
            levels = {s: float(np.mean(self.level_now[d["nodes"]])) for s, d in lock.sides.items() if d["nodes"]}
            for e in lock.step(now, DT_MIN, levels):
                self.events.append({**e, "t": e["t"]})
                ship = self.by_id.get(e.get("ship"))
                if ship is None:
                    continue
                if e["event"] == "enter":
                    ship.set_state(State.IN_LOCK, e["t"], lock=name)
                elif e["event"] in ("exit", "passed"):
                    if e["event"] == "passed":
                        self.mover.release(ship)
                    to_river = lock.sides.get(e.get("side"), {}).get("tidal")
                    if holds.get(name) and to_river and not ship.ulcv:
                        self.held_exits.setdefault(name, []).append(ship)      # regs: held during a ULCV passage
                        ship.note(e["t"], "held_for_ulcv", lock=name)
                        continue
                    self._leave_lock(ship, name, e["t"])

    def _after_move(self, ship, now):
        """Pilot changes and tug orders on the way."""
        head = ship.cells[-1] if ship.cells else None
        if head is None:
            return
        if ship.needs_pilot and ship.pilots:
            zone = self.pilot_zone(head)
            if zone != ship.pilot_zone:
                self.drop_pilots(ship, now)
                ship.pilot_change_boat = zone == "river"          # boarding at Vlissingen by pilot boat
                if self.take_pilots(ship, zone, now, boat=ship.pilot_change_boat):
                    ship.set_state(State.PILOT_CHANGE, now, zone=zone)
                    ship.timer = PILOT_CHANGE_MIN
                else:
                    self.wait_for_pilot(ship, zone, now)
        if (not ship.departing and ship.berth and ship.berth.get("kind") in ("terminal", "berth") and not ship.tugs
                and ship.tugs_needed() and ship.lock_index < 0 and ship.remaining_m < TUG_ORDER_M):
            x, y = float(self.fg.x[ship.berth["node"]]), float(self.fg.y[ship.berth["node"]])
            tugs, ready = self.tugs.request(ship.tugs_needed(), x, y, ship.id, now)
            if tugs:
                ship.tugs, ship.tugs_ready_at = tugs, ready
                ship.note(now, "tugs_ordered", n=len(tugs))

    # ------------------------------------------------------------------ the step
    def step(self):
        now = self.t
        self.level_now = self._levels(self.k)                                     # 1 environment
        for ship in self.generator.arrivals(now, DT_MIN):                         # 2 arrivals
            self.spawn(ship)
        if self.k % PLAN_EVERY == 0:                                              # 3 VTS
            self.vts.plan(now)
        self._locks(now)                                                          # 4 resources
        self._timers(now)
        for ship in self.ships:                                                   # ships waiting for room to start
            if getattr(ship, "waiting_space", False) and ship.state in MOVING + (State.SAILING,):
                if self.mover.place(ship):
                    ship.waiting_space = False
        sailing = [s for s in self.ships if s.state in MOVING and not getattr(s, "waiting_space", False)]
        arrived = self.mover.step(sailing, DT_MIN, self.k, self.rng)              # 5 movement
        for ship in sailing:
            if ship.state in MOVING and ship not in arrived:
                self._after_move(ship, now)
        for ship in arrived:                                                      # 6 ends of routes
            self._arrive_end(ship, now + DT_MIN)
        self._record(now)                                                         # 7 logging
        self.t += DT_MIN
        self.k += 1

    def _record(self, now):
        states = pd.Series([s.state.value for s in self.ships]).value_counts().to_dict() if self.ships else {}
        row = {"t": now, "time": self.times[self.k], "ships": len(self.ships), **{f"n_{k}": v for k, v in states.items()},
               "vts_requests": len(self.vts.requests),
               "lock_queue": sum(c.waiting() for _, l in self.locks.values() for c in l.chambers),
               "wind_bft": int(self.weather.at(self.now_ts(now)).bft),
               "visibility_m": float(self.weather.at(self.now_ts(now)).visibility_m),
               "tugs_busy": self.tugs.busy(now), "pilot_boats_busy": self.pilot_boats.n - self.pilot_boats.available(now),
               "boatmen_busy": self.boatmen.n - self.boatmen.available(now),
               **{f"pilots_busy_{z}": self.pilots.busy(z, now) for z in self.pilots.sizes},
               **{f"free_quay_{k}": round(T.free_quay_m()) for k, T in self.terminals.items()}}
        self.series.append(row)
        # positions for the viewer, every step: a ship under way as (route, distance of its bow along it),
        # so it can be drawn along the water it sails; a ship lying still as its node, only when it changes
        for s in self.ships:
            if s.state in MOVING and s.cells and s.route and s.s is not None:
                self._last_pos[s.id] = None
                self.positions.append((self.k, s.id, s.state.value, self._route_id(s), round(float(min(s.head, s.s[-1])), 1)))
                continue
            node = s.cells[-1] if s.cells else s.at
            if node is None:
                continue
            key = (int(node), s.state.value)
            if self._last_pos.get(s.id) != key:
                self._last_pos[s.id] = key
                self.positions.append((self.k, s.id, s.state.value, -1, int(node)))

    def _route_id(self, ship):
        """Index of the ship's current route in routes_rec (each route list is stored once)."""
        if getattr(ship, "_rec_route", None) is not ship.route:
            ship._rec_route, ship._rec_rid = ship.route, len(self.routes_rec)
            self.routes_rec.append([int(n) for n in ship.route])
        return ship._rec_rid

    def progress(self, wall_s):
        """One status line: the state of the port and how fast the run goes."""
        states = {}
        for s in self.ships:
            states[s.state.value] = states.get(s.state.value, 0) + 1
        blocked = sum(1 for s in self.ships if s.state in MOVING and s.blocked_steps >= 6)
        removed = sum(1 for s in self.done if s.log and s.log[-1].get("how") == "infeasible")
        days = self.t / 1440
        log.info("day %5.2f | area %4d done %5d removed %3d | sailing %3d blocked %3d berth %3d anchored %3d "
                 "vts %3d lockq %2d | pilots s/r/d %d/%d/%d tugs %d | %4.0f s wall, %3.0f s per day",
                 days, len(self.ships), len(self.done), removed, states.get("sailing", 0), blocked,
                 states.get("at_berth", 0), states.get("anchored", 0), len(self.vts.requests),
                 sum(c.waiting() for _, l in self.locks.values() for c in l.chambers),
                 self.pilots.busy("sea", self.t), self.pilots.busy("river", self.t), self.pilots.busy("dock", self.t),
                 self.tugs.busy(self.t), wall_s, wall_s / max(days, 1e-9))

    def run(self, progress_hours=2.0, max_minutes=None, should_stop=None):
        """Run all steps, a status line every progress_hours of simulated time; stop early (and
        say so) after max_minutes of wall-clock time, or when should_stop() says so (a stop asked
        for from the setup page). Either way the caller saves what was simulated."""
        t0 = time.time()
        every = max(1, int(progress_hours * 60 / DT_MIN))
        self.stopped_early, self.stop_reason = False, None
        for _ in range(self.n_steps):
            if should_stop is not None and should_stop():
                self.stopped_early, self.stop_reason = True, "stopped manually"
                log.warning("stop requested at day %.2f: stopping and saving", self.t / 1440)
                break
            self.step()
            wall = time.time() - t0
            if self.k % every == 0:
                self.progress(wall)
            if max_minutes is not None and wall > max_minutes * 60:
                self.stopped_early, self.stop_reason = True, "wall-clock limit"
                log.warning("wall-clock limit of %.0f min reached at day %.2f: stopping and saving", max_minutes, self.t / 1440)
                break
        self.progress(time.time() - t0)
        return self

    # ------------------------------------------------------------------ output
    def ship_table(self):
        rows = []
        for s in self.done + self.ships:
            d = s.durations.copy()
            if s.state != State.EXITED and s.since is not None:
                d[s.state.value] = d.get(s.state.value, 0.0) + self.t - s.since
            rows.append({"id": s.id, "name": s.name, "class": s.cls, "level": s.level, "loa": s.loa, "beam": s.beam,
                         "draught": s.draught, "teu": s.teu, "source": s.source, "destination": s.destination,
                         "terminal": s.terminal, "exit": s.exit, "spawn_min": s.spawn_t,
                         "finished": s.state == State.EXITED, "end_min": s.times.get("exited"),
                         "scheduled_berth_min": s.schedule.get("arrival_min"), "moored_min": s.times.get("at_berth"),
                         "scheduled_departure_min": s.schedule.get("departure_min"), "ready_min": s.times.get("ready"),
                         **{f"min_{k}": round(v, 1) for k, v in d.items()}})
        return pd.DataFrame(rows)

    def summary(self, ships):
        done = ships[ships.finished & (ships.spawn_min >= self.warmup_min)]
        how = pd.Series([s.log[-1].get("how") for s in self.done if s.log])
        out = {"steps": self.k, "days": round(self.t / 1440, 2), "stopped_early": getattr(self, "stopped_early", False),
               "stop_reason": getattr(self, "stop_reason", None),
               "start": str(self.start), "warmup_min": self.warmup_min, "step_min": DT_MIN,
               "ships_generated": len(ships),
               "removed_infeasible": int((how == "infeasible").sum()),
               "ships_finished_after_warmup": len(done), "still_in_area": int((~ships.finished).sum())}
        cols = [c for c in ships.columns if c.startswith("min_")]
        per = {}
        for cls, g in done.groupby("class"):
            per[cls] = {"n": len(g), "hours_in_area_mean": round(((g.end_min - g.spawn_min) / 60).mean(), 2),
                        **{c[4:] + "_h_mean": round(g[c].fillna(0).mean() / 60, 2) for c in cols}}
        out["per_class"] = per
        ts = pd.DataFrame(self.series)
        out["utilisation_mean"] = {c: round(float(ts[c].mean()), 2) for c in ts.columns
                                   if c.endswith("_busy") or c.startswith("pilots_busy")}
        out["anchored_mean"] = round(float(ts.get("n_anchored", pd.Series([0])).fillna(0).mean()), 2)
        return out

    def save(self, out):
        out.mkdir(parents=True, exist_ok=True)
        ships = self.ship_table()
        ships.to_csv(out / "ships.csv", index=False)
        events = [e for s in self.done + self.ships for e in s.log] + self.events
        pd.DataFrame(events).sort_values("t").to_csv(out / "events.csv", index=False)
        pd.DataFrame(self.series).to_csv(out / "timeseries.csv", index=False)
        # water level at the tide gauges each step (m above LAT, tide + surge): the viewer's live depth
        gauges = self.fg.labels["gauges"]
        lv = pd.DataFrame(self.L[:self.k + 1], columns=gauges).round(3)
        lv.insert(0, "t", np.arange(len(lv)) * DT_MIN)
        lv.to_csv(out / "levels.csv.gz", index=False)
        # route = -1: the ship lies at node `value`; else it is `value` m along routes[route] (route.json)
        pd.DataFrame(self.positions, columns=["step", "ship", "state", "route", "value"]).to_csv(
            out / "positions.csv.gz", index=False)
        (out / "routes.json").write_text(json.dumps(self.routes_rec, separators=(",", ":")))
        summary = self.summary(ships)
        (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
        return summary


def main():
    """Every run goes through the pipeline: a numbered folder in results/runs/ with its viewer."""
    import pipeline
    pipeline.main()


if __name__ == "__main__":
    main()
