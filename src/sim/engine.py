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
levels.csv.gz, port_state.json.gz (locks, VTS queue and berths over time, src/sim/port_state.py)
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import pickle
import sys
import tempfile
import time
import zlib
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.ndimage import maximum_filter1d

ROOT = Path(__file__).resolve().parents[2]
for sub in ("src/environment", "src/agents", "src/data", "src/sim"):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

import background_traffic as BT                           # noqa: E402
import navigation_rules as NR                             # noqa: E402
import port_infrastructure as PI                          # noqa: E402
from anchorages import FCFS, TIDE_DEPENDENT, choose_anchorage   # noqa: E402
from currents import CurrentModel                         # noqa: E402
from clearance import node_clearance                      # noqa: E402
from fast_graph import FastGraph, PassabilityCache        # noqa: E402
from lanes import Lanes                                   # noqa: E402
from generator import INLAND_TRIP_SCALE, WEEK_TZ, Generator   # noqa: E402
from locks import HOLD_FREE_PRIORITY, LockTimes, ShipRequest, in_next_lockage   # noqa: E402
from movement import Mover                                # noqa: E402
from services import PILOT_BOAT_MIN, PilotPool, TugPool, boatmen, pilot_boats   # noqa: E402
from port_state import PortStateLog                       # noqa: E402
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
DEFAULT_STAY_H = 24.0                  # a container call without a scheduled stay (none: the generator draws one)
TUG_ORDER_M = 15_000.0
DETOUR_M = 3000.0
MIN_CELL_CLEARANCE_M = 25.0            # every cell has at least this much water to each side (clearance.py)
MIN_PILOT_STRETCH_M = 3000.0           # a stretch of another pilot zone shorter than this is sailed with the pilot
                                       # already on board (no change for 500 m of river at Vlissingen)
DEPTH_PENALTY_PER_M = 20.0             # a cell that needs the tide costs 1 + this x the metres it lacks at low water:
                                       # routes keep to the deep channel and the VTS tide check finds the time
TIDE_CYCLE_STEPS = 150                 # 12.5 h
NORTH_GATE_MARGIN_M = 1.5
QUAY_GAP_M = 30.0                      # berths this close end to end are one stretch of quay
MAX_SHIP_LOA_M = 400.0
INLAND_MAX_CALLS = 12                  # a safeguard on the chain of inland calls
# A ship whose next call has no berth free waits for one at the berth it lies at (it was 6 h and then it left the
# port: with more traffic the calls that found no berth were not made, and the shortage of berths did not show).
# After this long it leaves all the same, so that two ships waiting for each other's berth do not wait for ever:
# counted (summary: silent.next_call_dropped), and a run in which it happens more than now and then says so
NEXT_CALL_WAIT_MIN = 1440.0
# An inland craft that finds no berth free in its zone lies beside one that is taken, up to this many beside each
# berth of the zone that it could take (assumed: two abreast). When they are taken too it waits where it is for
# room (summary: silent.berth_wait, and its time waiting for clearance); it used to lie alongside without limit, so
# that no number of inland craft could fill a zone. Not for a barge beside a ship (a bunker barge at a terminal)
ALONGSIDE_PER_BERTH = 1
# what the model does to keep going where a real port would show a shortage: counted in every run's summary
SILENT = ("next_call_dropped", "next_call_unfit", "destination_redrawn", "berth_wait", "anchorage_full", "no_anchorage")
# the deepest a ship may leave at (regs §8: right-bank and Kieldrecht locks 14.5 m, container ships 15.2 m)
DEPARTURE_MAX_DRAUGHT_M = {"container": 15.2, "bulk_general": 14.5, "tanker": 14.5}
PORT_PLACES = ("vlissingen", "terneuzen", "breskens")
# an inland craft calling in a canal zone lies there and comes back (AIS: most that cross the river cross it
# twice); it does not leave the model on arrival. "exit_<canal>" is the way out
INLAND_CALL_PLACES = ("ghent_terneuzen_canal", "zuid_beveland_canal", "schelde_rijn_canal", "albert_canal", "upper_sea_scheldt")
# so does a sea-going ship calling on the Ghent-Terneuzen canal inside the area (Sluiskil): it left the model
# there and never came back out through the lock (validation: 16 sea-going lock passages a day at Terneuzen
# where the AIS has 27)
# ... and one calling on the Albert canal, the Upper Sea Scheldt or the two Dutch canals (one bulk-carrier call in
# fourteen in the right-bank docks is followed by a call on the Albert canal): it left the model there too, with
# the voyage back out through the locks and down the river never made (MODEL.md §19)
SEA_CALL_PLACES = ("ghent_terneuzen_canal", "zeebrugge", "albert_canal", "upper_sea_scheldt", "schelde_rijn_canal",
                   "zuid_beveland_canal")
# A call beyond the area: a sea-going ship up the Ghent-Terneuzen canal to Ghent and back (background_traffic:
# in from sea and out to sea with no call heard, but heard on the canal). It sails to the canal's end of the model,
# is away for a stay of its class, and comes back out through the lock; while away it is not in the area
# (validate.py). Destination -> the place it leaves the area by
AWAY_CALLS = {"beyond_ghent_terneuzen_canal": "ghent_terneuzen_canal"}
# Inland craft calling at Vlissingen: one call in eleven is at the town (the inner harbour and the Walcheren canal,
# 41 of 435 calls in the AIS), 8 km down-river of Vlissingen-Oost where the place lies, and the craft passes the
# river section off Vlissingen on its way there and back (inland passages there 10.6 a day against 12.7)
VLISSINGEN_TOWN = (3.5976, 51.4508)
# The share of the town is the AIS share of the calls, 0.094 (41 of 435). It was set to 0.036 on those passages
# (with 0.094 they were 16.1 a day): that made up for 83 inland craft a run that left by the sea past Vlissingen
# because their beam of 22 to 24 m, counted as 25 m, could not "reach" their canal (reachable_between, run 0023).
# With that put right the passages were 8.9 a day with 0.036 (run 0024)
VLISSINGEN_TOWN_SHARE = {"inland": 0.094}
# Inland craft keep off the sea locks at the head of the big docks where another lock will do: the AIS has 43 %
# of their right-bank lock passages at Zandvliet and Berendrecht (the rest at Boudewijn and Van Cauwelaert) and
# half of the left bank's at Kieldrecht (the rest at Kallo), where routes by length alone gave 58 % and 60 %
# (6 km added gave 21 % and 28 %, and 2.5 km 30 % with Boudewijn and Van Cauwelaert overrun: 141 passages a day
# against 94, 2.7 h to pass). As metres of route added to those locks for an inland craft (calibrated,
# MODEL.md §19)
# (Kieldrecht 1000 and 1500 m: 59 % of the left bank's at Kieldrecht, 38 a day against 25, Kallo 27 against 23)
# (Kieldrecht 2000 m: 34 a day against 25; 3500 m: 52 % of the left bank's, as in the AIS. Zandvliet and
# Berendrecht 1700 m: 36 % of the right bank's against 44 %)
INLAND_SEA_LOCK_COST_M = {"Zandvliet": 1350.0, "Berendrecht": 1350.0, "Kieldrecht": 3500.0}
# locks side by side: which one a ship takes is a matter of which is free, not of 500 m of route, so each
# ship draws one by the AIS shares (LOCK_PASSAGES); the nearer one used to get them all
# "antwerp_other" is the port away from a charted berth: lock approaches, waiting places, small quays. Nine in ten
# of the inland craft's calls there, and three in four of the sea-going ships', lie on the river side of the locks
# (the waiting places at Lillo and off the Zandvliet locks), but nine in ten of the zone's charted berths lie
# behind them, and the berth drawn by its AIS calls sent 89 % of these calls (44 a day by inland craft) through a
# dock lock and back: inland craft passed the dock locks 263 times a day where the AIS has 213 (MODEL.md §19).
# Zone -> the share of its calls on the river side, per group (AIS); the berth is drawn on that side
ZONE_RIVER_SIDE_SHARE = {"antwerp_other": {"inland": 0.90, "sea_going": 0.74}}
# ... and where along the river the inland craft's calls of that side lie (AIS, 618 calls): river km from, to, share.
# Seven in ten at the waiting places off Lillo and Deurganckdok (km 68-72), a fifth off the Zandvliet locks. Drawn
# by the berths' own AIS calls (which count calls within 150 m of a berth, and this zone is the calls away from
# one) they went to the quays at the city, and the inland traffic past km 80 rose to 71 a day against 52
ZONE_RIVER_KM_SHARE = {"antwerp_other": ((63.5, 67.5, 0.20), (67.5, 72.5, 0.71), (75.0, 78.5, 0.05), (78.5, 92.0, 0.04))}
TWIN_LOCKS = (("Zandvliet", "Berendrecht"), ("Boudewijn", "Van Cauwelaert"))
# the lock complexes into one dock system: which one a sea-going ship takes is the lock planners' choice, not the
# shortest route. The routes put no ship through Kallo (it is 3 to 6 km longer to every left-bank berth than
# Kieldrecht) and one in six through Boudewijn or Van Cauwelaert (the river beyond Zandvliet costs more than the
# docks: lanes and keep-right); the AIS has one in three and one in five (validation, MODEL.md §19). Each
# sea-going ship draws a complex per dock system by the AIS shares (LOCK_PASSAGES), as for the twins
LOCK_COMPLEXES = ((("Zandvliet", "Berendrecht"), ("Boudewijn", "Van Cauwelaert")), (("Kieldrecht",), ("Kallo",)))
# ... times a factor on the second complex of each system: drawn by the shares alone, 17 % of the right bank's
# sea-going passages went by Boudewijn and Van Cauwelaert and 27 % of the left bank's by Kallo, where the AIS has
# 21 % and 33 % (a ship too wide or too deep for the complex it drew takes the other one, and those are all ships
# that drew the smaller locks). Calibrated (MODEL.md §19)
LOCK_COMPLEX_FACTOR = {("Boudewijn", "Van Cauwelaert"): 1.32, ("Kallo",): 1.9}     # (Kallo 1.35: -18 %, 1.7: -12 %)
BERENDRECHT_MIN_BEAM_M = 43.0          # regs §8.9: ships this wide prefer Berendrecht
SEA_EXITS = ("exit_sea_southwest", "exit_sea_west", "exit_sea_north")
SEA_EXIT_STATION = {"sea_north": "pilot_station_steenbank"}        # else Wandelaar: the pilot leaves there
# ULCV rules (regs §8.9, §8.11, JA22)
ULCV_HOLD_LOCKS = ("Zandvliet", "Berendrecht", "Terneuzen", "Hansweert")   # traffic out of them held ...
ULCV_HOLD_M = 5000.0                   # ... while a ULCV passes within this of their river side
ULCV_FALLBACK_AFTER_MIN = 12 * 60.0    # assumed: waited this long for its own quay
ULCV_FALLBACK = ("PSA Noordzee Terminal", "PSA Europa Terminal", "MPET", "DP World Antwerp Gateway")
# A container ship that finds its quay taken, or the tide wrong, when it asks for clearance is not sent to anchor
# at once: a ship with a berth time is told before it is there and loses the time at sea (it waits off the pilot
# station, counted in the area but not at anchor). After this long it anchors like any other ship. Sent to anchor
# at once, one in four container ships anchored where the AIS has one in eight
CONTAINER_SEA_WAIT_MAX_MIN = 18 * 60.0
BERTH_CHANGE_MIN = 60.0                # berth planning: a ship is planned to leave this long before the next
                                       # one is due on its quay (assumed)
UNMOORING_PLAN_MIN = 60.0              # planned from the end of the work to the quay being free (assumed)
LOCK_RESERVE_LEAD_MIN = 60.0           # a ULCV's chamber is reserved this long before it reaches the lock
                                       # when its route does not pass CP
# A ship waits for a lock at the waiting places away from it (movement.LOCK_WAIT_M before the gate) until it is
# called: its chamber lies open at its side, or will by the time the ship can be at the gate (LOCK_CALL_LEAD_MIN
# to spare). Then it sails in at this speed (the AIS speeds in the lock approaches: sea-going ships 2.5 kn, inland
# craft and sea-going ships no longer than a barge 3.6 kn) and can go into the chamber when it is at the gate.
# Called as soon as its chamber had closed at the other side, a ship lay 20 min at the gate where the AIS has it
# pass straight in: inland craft took 64 min through Terneuzen for the AIS's 52 (MODEL.md §19)
LOCK_SAIL_IN_KN = {"sea_going": 2.5, "inland": 3.6}
LOCK_CALL_LEAD_MIN = 5.0
# ... and a sea-going ship takes this much longer to come in at the sea locks of Antwerp (tugs, lines, the change
# of pilot): it passes them 20 to 35 min slower than an inland craft in the AIS, and the entry and exit times of
# the chamber alone gave 10. Calibrated per lock on the median passage time of the sea-going ships (MODEL.md §19)
# (28, 26, 20 and 18 min gave medians 11 to 17 % over the AIS at Zandvliet-Berendrecht, Boudewijn-Van Cauwelaert
# and Kallo, run 0009, but there a fifth to a third of the ships missed their chamber, locks.CALLED_HOLD_MAX_MIN;
# with that mended, 18, 15, 18 and 10 min gave them 5 to 13 % under)
LOCK_SEA_COMING_IN_MIN = {"Zandvliet": 30.0, "Berendrecht": 30.0, "Boudewijn": 20.0, "Van Cauwelaert": 20.0,
                          "Kieldrecht": 26.0, "Kallo": 14.0}
# Random streams, each from its own child of the seed (numpy SeedSequence.spawn): what arrives and when, and the
# weather, do not depend on what happens in the port, so two configurations run with one seed see the same ships
# in the same weather (common random numbers) and their difference is not blurred by different arrivals.
#   arrivals    when ships arrive (generator)        attributes  what they are (generator)
#   weather     the weather sequence                 service     durations: stays, mooring, anchor waits, draught change
#   choice      berths, exits, next calls, locks     movement    tie-breaks in the right of way
#   speed       each ship's own speed (SPEED_SPREAD)
#   locks       the holds of the locks               stays       a container call's stay over its line's
# Choices, durations and speed are drawn per ship (Simulation.ship_rng): each ship has a stream of its own for each,
# from the seed, the stream and its id (the ids come from the arrivals, which do not depend on the port). With one
# stream for all ships a change that made one more draw for one ship moved every later draw of every other ship,
# so two configurations no longer compared like with like (the share of calls at the town of Vlissingen moved
# Terneuzen's sea-going lock times and the tankers at anchor, runs 0024 / 0028)
STREAMS = ("arrivals", "attributes", "weather", "service", "choice", "movement", "speed", "locks", "stays")
SHIP_STREAMS = ("choice", "service", "speed")
# Ships of one class do not all sail at one speed: each ship's speed through the water is its class's times a
# factor drawn once, lognormal with this standard deviation of the logarithm (median 1), kept within
# SPEED_FACTOR_RANGE. With one speed per class the 90th percentiles of the sailing times were 12 to 17 % short of
# the AIS (3.05 h against 3.50 h from km 8 to km 62) with the medians right. Calibrated (MODEL.md §19)
SPEED_SPREAD = 0.10
SPEED_FACTOR_RANGE = (0.75, 1.30)
# The anchor stay of a ship that enters the area at anchor, as a factor on the fitted one: bulk carriers lay 3.9 at
# anchor at once where the AIS has 5.6 (some of them stop at the river anchorages on the way, which the model does
# not do; their time is added here). Calibrated (MODEL.md §19)
# Taken out again (runs 0015/0016, seeds 401-405): without it 77.4 bulk ships in the area against the AIS 77.4
# (with 1.30: 81.2) and 4.8 at anchor against 5.6 (within the tolerance); the stops at the river anchorages are
# not modelled and their time is not added elsewhere
ANCHOR_WAIT_FACTOR = {}
# Inland craft anchor on the way (AIS: 130 anchor stops of dry-cargo craft and 33 of tankers in 375 h, nearly all
# at Everingen, BT.P_ANCHORAGE_GIVEN_CLASS; stays BT.ANCHORAGE_WAIT_H: mean 2.7 h and 10.4 h): about one of each
# class at anchor at once. Without them the model had none. A craft whose route passes within INLAND_ANCHOR_NEAR_M
# of one of its class's anchorages stops there with this probability (once a visit), for a fitted anchor stay.
# Set on the craft at anchor at once (1.07 and 0.87 in the AIS). Calibrated (MODEL.md §19)
INLAND_ANCHOR_STOP_P = {"inland_cargo": 0.19, "inland_tanker": 0.23}    # (0.15 and 0.18: 0.85 and 0.78 at anchor)
INLAND_ANCHOR_NEAR_M = 4000.0
# The calls of a visit of an inland craft from the canals that calls in the area and makes its whole chain of calls
# (NEXT_CALL): 2.0 in the model (1.75 a visit with the single-call trips among them, screening runs of 15 November
# 2026). Dividing the stays by the whole trip scale, as when the added trips made the whole chain too, left 9 % too
# few dry-cargo craft at berths (147 against 161) once they made one call (MODEL.md §19)
INLAND_CALLS_PER_VISIT = 2.0
# Virtual arrival with the quay in view: a container ship whose quay will still be taken at its berth time (by the
# ships lying there and when they are to leave, Terminal.free_intervals) is given the time it comes free, up to
# this far ahead, and slows down at sea for it. Planned on its berth time alone it entered the area and waited off
# the pilot station for its quay: container ships in the area 29.2 against 25.9 once their stays had the AIS's
# long tail (MODEL.md §19)
VIRTUAL_ARRIVAL_LOOKAHEAD_H = 24.0
VIRTUAL_ARRIVAL_STEP_MIN = 30.0
# events that are release valves: a rule given up so that the model keeps moving. Their rate is a result (summary)
RELEASE_VALVES = ("encounter_rule_overridden", "depth_hold_overridden", "squeeze_past")
STATION_OF_SOURCE = {"sea_north": "pilot_station_steenbank", "anchorage_other": "pilot_station_steenbank"}      # else Wandelaar
NORTH_SOURCES = ("sea_north", "anchorage_other")   # in the part of the sea mesh joined to Wandelaar only through the river
TIDAL_BERTH_MARGIN_M = 1.0             # tidal berths: mean tide above LAT counted on when choosing one
MOVING = (State.TO_STATION, State.TO_ANCHORAGE, State.SAILING)
PILOT_ZONE = {"sea": "sea", "river": "river", "dock": "dock", "canal": "dock"}


class Route(list):
    """A voyage's node ids. free_from: index from which the route is not draught-limited (the open-sea
    leg from the pilot station to a sea exit, sailed like the arrivals' approach); None: all of it is."""
    free_from = None


class PositionLog:
    """The ships' positions every step (for the viewer and the validation), kept in a binary file on disk rather
    than in memory: a row is (step, ship, state, route, value, offset), 21 bytes in the file where a tuple in a list
    took about 300. Rows are buffered and written in blocks; frame() reads them back. The file is removed when the
    log is closed or collected."""
    DTYPE = np.dtype([("step", "<i4"), ("ship", "<i4"), ("state", "u1"), ("route", "<i4"), ("value", "<f8")])
    BLOCK = 20000

    def __init__(self):
        fd, self.path = tempfile.mkstemp(prefix="positions_", suffix=".bin")
        self.fh = open(fd, "wb")
        self.ships, self.ship_code = [], {}
        self.states, self.state_code = [], {}
        self.buf, self.offsets, self.offset_buf = [], None, []
        self.n = 0

    def append(self, row):
        step, ship, state, route, value, offset = row
        s = self.ship_code.get(ship)
        if s is None:
            s = self.ship_code[ship] = len(self.ships)
            self.ships.append(ship)
        c = self.state_code.get(state)
        if c is None:
            c = self.state_code[state] = len(self.states)
            self.states.append(state)
        self.buf.append((step, s, c, route, value))
        self.offset_buf.append(offset)
        self.n += 1
        if len(self.buf) >= self.BLOCK:
            self.flush()

    def flush(self):
        if self.buf:
            np.array(self.buf, dtype=self.DTYPE).tofile(self.fh)
            # the sideways offset is almost always 0: kept apart, as (row, offset) for the rows where it is not
            nz = [(self.n - len(self.buf) + i, o) for i, o in enumerate(self.offset_buf) if o]
            if nz:
                block = np.array(nz, dtype=[("row", "<i8"), ("offset", "<f4")])
                self.offsets = block if self.offsets is None else np.concatenate([self.offsets, block])
            self.buf, self.offset_buf = [], []
            self.fh.flush()

    def __len__(self):
        return self.n

    def frame(self, step_from=None):
        """The rows as a DataFrame (step, ship, state, route, value, offset); with step_from, only the rows from that
        step on and each ship's last row before it (where it was then: a ship lying still has no row while it lies)."""
        self.flush()
        a = np.fromfile(self.path, dtype=self.DTYPE)
        offset = np.zeros(len(a), dtype=np.float32)
        if self.offsets is not None:
            offset[self.offsets["row"]] = self.offsets["offset"]
        keep = None
        if step_from is not None:
            keep = a["step"] >= step_from
            before = np.flatnonzero(~keep)
            if len(before):                            # the last record of each ship before the cut
                last = pd.Series(before).groupby(a["ship"][before]).max().to_numpy()
                keep[last] = True
        if keep is not None:
            a, offset = a[keep], offset[keep]
        ships = np.array(self.ships, dtype=object)
        states = pd.Categorical.from_codes(a["state"].astype(np.int16), categories=self.states) if self.states else []
        return pd.DataFrame({"step": a["step"].astype(np.int64), "ship": ships[a["ship"]] if len(a) else np.array([], dtype=object),
                             "state": np.asarray(states, dtype=object) if len(a) else np.array([], dtype=object),
                             "route": a["route"].astype(np.int64), "value": a["value"], "offset": offset.astype(np.float64)})

    def close(self):
        try:
            self.fh.close()
            os.remove(self.path)
        except Exception:                              # already closed, or the interpreter is shutting down
            pass

    def __del__(self):
        self.close()


class Simulation:
    def __init__(self, start="2026-10-21 00:00", days=7.0, seed=1, delays=True, warmup_days=2.0, background=True,
                 weather_mode="bootstrap", container_mode="replay", container_rate=1.0, bunching=True,
                 routing="lanes", checks=False):
        t0 = time.time()
        self.checks = checks                           # check the invariants every step (check_invariants)
        self.start = pd.Timestamp(start, tz="UTC")
        self.n_steps = int(days * 24 * 60 / DT_MIN)
        self.warmup_min = warmup_days * 24 * 60
        self.seed = int(seed)
        self.streams = dict(zip(STREAMS, (np.random.default_rng(q) for q in np.random.SeedSequence(seed).spawn(len(STREAMS)))))
        self.container_sea_wait_max_min = CONTAINER_SEA_WAIT_MAX_MIN
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
        self.weather = Weather.generate(self.start, hours, self.streams["weather"], mode=weather_mode)
        # water levels: tide + the surge the weather drives
        self.L = self.tide.levels(times, weather=self.weather.surge_input)[fg.labels["gauges"]].to_numpy()
        self.A, self.const = fg._tide
        # the lowest water at every node over the whole run (tide + surge; the weights of A are >= 0, so this
        # is a lower bound): a route deep enough at this level is valid at any time, and in the docks it is
        # the dock level, not LAT (planning at LAT made every deep dock voyage tide-bound)
        self.level_base = np.asarray(self.A @ self.L.min(axis=0)).ravel() + self.const
        # the usual high water at every node: the median over the run of each tide's high water, so whether a
        # voyage can be made at all does not depend on the tide the run happens to start on
        self.level_high = np.asarray(self.A @ np.median(maximum_filter1d(self.L, TIDE_CYCLE_STEPS, axis=0, mode="nearest"),
                                                        axis=0)).ravel() + self.const
        # cells at a fixed level behind the locks (no tide term): UKC_DOCK_M applies there
        self.nontidal = np.diff(self.A.tocsr().indptr) == 0
        self.passable = PassabilityCache(fg)
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
        h = self.hw_series                             # the high waters at Antwerp, minutes from the start
        self.high_waters = (np.flatnonzero((h[1:-1] >= h[:-2]) & (h[1:-1] > h[2:]) & (h[1:-1] > np.percentile(h, 60))) + 1) * DT_MIN
        self.dock_speed_kn = 5.0
        # resources
        self.locks = {d["name"]: (n, d["lock"]) for n, d in self.graph.nodes(data=True) if d["type"] == "lock"}
        self.lock_of_node = {n: lock for n, lock in self.locks.values()}
        for _, lock in self.locks.values():            # the durations of the code, not those the graph was built with
            lock.times = LockTimes()                   # (the cached graph holds each lock's own copy)
            lock.rng = self.streams["locks"]
            for c in lock.chambers:
                c.held = False
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
        self.exit_place = {self.places[e[5:]]["node"]: e[5:] for e in SEA_EXITS if e[5:] in self.places}
        self.destinations = self.graph.graph["destinations"]
        self.pilots = PilotPool()
        self.pilot_boats = pilot_boats()
        self.boatmen = boatmen()
        self.tugs = TugPool(self.places)
        self.tugs.bind(lambda n: (float(fg.x[n]), float(fg.y[n])))
        # agents
        self.mover = Mover(self)
        self.vts = SimpleVTS(self)
        self.generator = Generator(self.start, self.streams["arrivals"], delays=delays, background=background,
                                   container_mode=container_mode, rate_factor=container_rate, bunching=bunching,
                                   rng_attributes=self.streams["attributes"], rng_stays=self.streams["stays"],
                                   quay_m={name: sum(b - a for a, b in T.suitable_intervals(None, True))
                                           for name, T in self.terminals.items()})
        self.at_sea = []                               # container ships slowed down at sea for their berth time
        self.lead_min = {}                             # planned minutes from entering the area to the berth
        self.n_entered = 0
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
        river = np.flatnonzero(fg.region == fg.code("region", "river")) if "region" in fg.labels else np.arange(fg.n)
        self.reach_from = int(river[np.argmax(fg.depth_m[river])])      # the deepest cell of the main channel
        self.events, self.series, self.positions = [], [], PositionLog()
        self.routes_rec, self._last_pos = [], {}
        self.terminal_waiting = {}                     # terminal -> {ship id: since when it waits for quay}   # routes sailed (node lists) and last fixed position per ship
        self.port_log = PortStateLog(self)             # locks, VTS queue and berths over time (the viewer)
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

    def ship_rng(self, ship, stream):
        """The ship's own random stream for choices, durations or its speed (SHIP_STREAMS): from the seed, the
        stream and the ship's id, so that a draw one ship makes or does not make leaves every other ship's draws
        as they were (common random numbers between two configurations, MODEL.md §1)."""
        key = "_rng_" + stream
        g = ship.__dict__.get(key)
        if g is None:
            g = np.random.default_rng(np.random.SeedSequence([self.seed, STREAMS.index(stream), zlib.crc32(ship.id.encode())]))
            ship.__dict__[key] = g
        return g

    # ------------------------------------------------------------------ routes
    @staticmethod
    def needs(ship):
        """Water a ship needs on the tidal water and behind the locks, in half-metre classes."""
        return math.ceil(ship.need_m * 2) / 2, math.ceil(ship.need_dock_m * 2) / 2

    def plan_level(self, level, ship):
        """A water level to test against a ship's tidal need: behind the locks it needs less water, which
        comes to the same as that much more level there."""
        need, dock = self.needs(ship)
        return level + (need - dock) * self.nontidal if need > dock else level

    def route(self, start, target, ship, level=None, mask=None, lanes=True, tag="now", tide_bound=False):
        """Route at the run's lowest water (level None: valid at any time, cached), at a given level (tag
        names it, for the "failed this hour" memory), or, tide_bound, the deep channel for a ship that
        needs the tide somewhere: every cell it can pass at the usual high water, keeping to the deepest
        water (cached: where it sails does not depend on when; the VTS tide check finds the time)."""
        fg = self.fg
        profile = self.lane_profile(ship) if lanes else None
        need, dock = self.needs(ship)
        avoid = self.locks_avoided(ship)
        key = (start, target, need, dock, math.ceil(ship.loa / 25), math.ceil(ship.beam / 5), profile, avoid, ship.sea_going)
        if tide_bound:
            key += ("tide_bound",)
            level = self.level_high
        cached = (level is None or tide_bound) and mask is None
        if cached and key in self.route_cache:
            return self.route_cache[key]
        if not cached and mask is None and self.failed.get(key + (tag,), -1) == self.k // 12:
            return None                                # failed at this water level this hour already
        import networkx as nx
        r = None
        wide = ship.beam / 2 if ship.beam / 2 > MIN_CELL_CLEARANCE_M else None
        at = self.plan_level(self.level_base if level is None else level, ship)
        depth = (self.plan_level(self.level_base, ship), need, DEPTH_PENALTY_PER_M) if tide_bound else None
        for clearance in ((wide, None) if wide else (None,)):
            try:
                r = fg.route(start, target, need, 0.0, ship.loa, ship.beam, level=at, nodes_mask=mask,
                             keep_right=True, min_clearance=clearance, depth_penalty=depth, avoid_locks=avoid,
                             lock_cost=None if ship.sea_going else INLAND_SEA_LOCK_COST_M,
                             lane_factor=self.lanes.factor(fg, profile) if self.lanes is not None and profile else None)
                if wide and clearance is None:
                    ship.note(self.t, "narrow_route", beam=ship.beam)    # no route with room for its beam
                break
            except nx.NetworkXNoPath:
                continue
        if cached:
            self.route_cache[key] = r
        elif r is None and mask is None:
            self.failed[key + (tag,)] = self.k // 12
        return r

    def locks_avoided(self, ship):
        """The lock of each pair side by side that this ship does not take (drawn once, by the AIS shares)."""
        avoid = getattr(ship, "avoid_locks", None)
        if avoid is None:
            group = "sea_going" if ship.sea_going else "inland"
            avoid = []
            if ship.sea_going:
                for complexes in LOCK_COMPLEXES:
                    if ship.beam >= BERENDRECHT_MIN_BEAM_M and "Berendrecht" in complexes[0]:
                        avoid += list(complexes[1])        # Berendrecht only (below)
                        continue
                    w = np.array([sum(PI.LOCK_PASSAGES.get(l, {}).get(group, 0.0) for l in c) * LOCK_COMPLEX_FACTOR.get(c, 1.0)
                                  for c in complexes], dtype=float)
                    if w.sum() <= 0:
                        continue
                    pick = int(self.ship_rng(ship, "choice").choice(len(complexes), p=w / w.sum()))
                    avoid += [l for i, c in enumerate(complexes) if i != pick for l in c]
                # Royers and Kattendijk carry the same penalty as a complex not drawn, so a ship whose drawn complex
                # does not fit went through them on a tie (0.3 sea-going passages a day; the AIS has none)
                avoid += ["Royers", "Kattendijk"]
            for a, b in TWIN_LOCKS:
                na = PI.LOCK_PASSAGES.get(a, {}).get(group, 1.0)
                nb = PI.LOCK_PASSAGES.get(b, {}).get(group, 1.0)
                if "Berendrecht" in (a, b) and ship.beam >= BERENDRECHT_MIN_BEAM_M:
                    avoid.append(a if b == "Berendrecht" else b)
                    continue
                if a in avoid or b in avoid:
                    continue                           # its complex is not this ship's
                avoid.append(b if self.ship_rng(ship, "choice").random() < na / max(na + nb, 1e-9) else a)
            avoid = ship.avoid_locks = tuple(avoid)
        return avoid

    def tidal_route(self, start, target, ship):
        """A route valid at any time, else the deep channel, which needs the tide. Not a route for the water
        level now: that takes any cell wet at the moment (banks at sea, shallows along a lock approach), one
        level for the whole voyage, and then fails the tide check at the far end of it, so that ships of
        13-15 m to the locks found almost no window."""
        return self.route(start, target, ship) or self.route(start, target, ship, tide_bound=True)

    def exit_station(self, node, ship):
        """The pilot station on the way to a sea exit node (None: node is not a sea exit). The pilot leaves
        there; beyond it the ship sails the open sea like an arrival's approach, not draught-limited
        (the exit cells lie on the banks at the edge of the AIS area, 9 m deep at sea_north)."""
        name = self.exit_place.get(node)
        if name is None:
            return None
        # (a sea leg keeps to deep water where it can: approach_route)
        station = SEA_EXIT_STATION.get(name, "pilot_station_wandelaar")
        return self.places[station]["node"]

    def north_gate_ok(self, ship):
        """Can this ship use the north gate and Steenbank: the Oostgat NORTH_GATE_MARGIN_M below the usual
        high water, so that its window there lasts hours and a long voyage can meet it (at the high water
        itself ships of 10.7 m from the Upper Sea Scheldt waited for weeks)? The sea mesh has no way from
        there to Wandelaar except back through the Oostgat and the river (93 km, over banks of 9 m), so a
        deeper ship enters and leaves by the west gate, as its deep route would at sea."""
        need, dock = self.needs(ship)
        key = ("north", need, dock, math.ceil(ship.loa / 50) * 50, math.ceil(ship.beam / 5) * 5)
        if key not in self.reachable:
            self.reachable[key] = self.fg.reachable(self.reach_from, need, 0.0, key[3], key[4],
                                                    level=self.plan_level(self.level_high - NORTH_GATE_MARGIN_M, ship))
        return bool(self.reachable[key][self.places["pilot_station_steenbank"]["node"]])

    def port_node(self, name, ship):
        """Where a ship calling at a port with no berth model (Vlissingen, Terneuzen, Breskens) ends: the
        port's node, or for a ship too deep for the mesh's way in (AIS does show bulk carriers of 15 m at
        Vlissingen-Oost) the nearest water it can reach."""
        node = self.places[name]["node"]
        reach = self.reach(ship)
        if reach[node]:
            return node
        ok = np.flatnonzero(reach & ~self.mover.special)
        return int(ok[np.argmin(np.hypot(self.fg.x[ok] - self.fg.x[node], self.fg.y[ok] - self.fg.y[node]))]) if len(ok) else node

    def voyage_reachable(self, ship, a, target):
        """reachable_between for a voyage: to a sea exit, its pilot station must be reachable."""
        station = self.exit_station(target, ship)
        return self.reachable_between(a, target if station is None else station, ship)

    def voyage_route(self, ship, start, target):
        """The route of a voyage (a Route): tidal_route to the target, or, to a sea exit, tidal_route to
        its pilot station followed by the open-sea approach from there (free_from marks where)."""
        if start is None or target is None:
            return None
        station = self.exit_station(target, ship)
        tail = self.approach_route(station, target, ship) if station is not None else None
        if tail is None:
            r = self.tidal_route(start, target, ship)
            return Route(r) if r is not None else None
        r = [start] if start == station else self.tidal_route(start, station, ship)
        if r is None:
            return None
        out = Route(list(r) + list(tail[1:]))
        out.free_from = len(r)
        return out

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
                "boarding_at_sea": not ship.departing and self.first_pilot_zone(route) == "sea" and ship.needs_pilot}
        return WG.start_gate(ship, self.weather, self.now_ts(now), info)

    def approach_route(self, start, station, ship):
        """Open sea between a sea gate and a pilot station: it keeps to water deep enough for the ship at low
        water wherever there is any (the banks cost DEPTH_PENALTY_PER_M, they used to be crossed by ships of
        15 m), and is not forbidden where there is none. The VTS checks the voyage from the station."""
        need = self.needs(ship)[0]
        key = ("approach", start, station, need)
        if key not in self.route_cache:
            import networkx as nx
            try:
                self.route_cache[key] = self.fg.route(start, station, 0.0, 0.0, keep_right=False,
                                                      depth_penalty=(self.level_base, need, DEPTH_PENALTY_PER_M))
            except nx.NetworkXNoPath:
                self.route_cache[key] = None
        return self.route_cache[key]

    def plan_route(self, ship, now):
        """Route for the ship's next voyage from where it lies (voyage_route). Sets ship.target (None: no
        destination free now) so callers do not choose again (a second choice could draw another berth)."""
        target = self.choose_target(ship)
        ship.target = target
        if target is None or ship.at is None:
            return None
        return self.voyage_route(ship, ship.at, target)

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
        if self.quay_length(b) < ship.loa:
            return False
        return self.berth_reachable(b, ship)

    @staticmethod
    def berth_length(b):
        return b.get("berth_length_m") or b["length_m"]

    def berth_neighbours(self, bid):
        """The berths next to this one along the same quay (their ends within QUAY_GAP_M, about the same
        heading), nearest first."""
        if not hasattr(self, "_adjacent"):
            ids = [i for i, r in self.berths.items() if r["nodes"] and r.get("berth_type") != "Sluis"]
            xy = np.array([(self.fg.x[self.berths[i]["nodes"][0]], self.fg.y[self.berths[i]["nodes"][0]]) for i in ids])
            self._adjacent = {}
            for a, i in enumerate(ids):
                r, near = self.berths[i], []
                dist = np.hypot(*(xy - xy[a]).T)
                for c in np.argsort(dist)[1:13]:
                    o = self.berths[ids[c]]
                    turn = abs(((r.get("heading_deg") or 0.0) - (o.get("heading_deg") or 0.0) + 90) % 180 - 90)
                    if dist[c] <= (self.berth_length(r) + self.berth_length(o)) / 2 + QUAY_GAP_M and turn <= 20 \
                            and o.get("basin") == r.get("basin"):
                        near.append(ids[c])
                self._adjacent[i] = near
        return self._adjacent.get(bid, [])

    def quay_length(self, b):
        """The length of quay around a berth: its own and the berths next to it, one step each way or on."""
        bid = next((i for i, r in self.berths.items() if r is b), None) if "quay_m" not in b else None
        if "quay_m" not in b:
            seen, todo, total = {bid}, [bid], 0.0
            while todo:
                i = todo.pop()
                total += self.berth_length(self.berths[i])
                for n in self.berth_neighbours(i):
                    if n not in seen and total < MAX_SHIP_LOA_M:
                        seen.add(n)
                        todo.append(n)
            b["quay_m"] = total
        return b["quay_m"]

    def berths_for(self, bid, ship):
        """The berth and the free ones next to it that a ship this long lies across, or None if the quay is
        taken (a ship used to moor at any berth half its length, overhanging whoever lay next to it)."""
        out, total = [bid], self.berth_length(self.berths[bid])
        frontier = [bid]
        while total < ship.loa and frontier:
            i = frontier.pop(0)
            for n in self.berth_neighbours(i):
                if n not in out and n not in self.berth_ship:
                    out.append(n)
                    frontier.append(n)
                    total += self.berth_length(self.berths[n])
                    if total >= ship.loa:
                        break
        return out if total >= ship.loa else None

    def berth_reachable(self, b, ship):
        """Can the ship get to this berth at all (from the river at Vlissingen)?"""
        return self.reachable_between(self.reach_from, b["nodes"][len(b["nodes"]) // 2], ship)

    def reach(self, ship, exact=False):
        """Nodes a ship of this draught and size can reach from the river at Vlissingen at the usual
        high water (level_high); one search per draught / size class, cached. exact: by its own length and
        beam (to the metre and the decimetre above), not the class."""
        need, dock = self.needs(ship)
        key = ((need, dock, math.ceil(ship.loa), math.ceil(ship.beam * 10 - 1e-9) / 10) if exact else
               (need, dock, math.ceil(ship.loa / 50) * 50, math.ceil(ship.beam / 5) * 5))
        if key not in self.reachable:
            self.reachable[key] = self.fg.reachable(self.reach_from, need, 0.0, key[2], key[3],
                                                    level=self.plan_level(self.level_high, ship))
        return self.reachable[key]

    def reachable_between(self, a, b, ship):
        """Is there a route a -> b for this ship at high water? Both ends reachable from the river
        (passing rules are the same both ways)."""
        r = self.reach(ship)
        if r[a] and r[b]:
            return True
        # the size class rounds up (beam to 5 m, length to 50 m): a craft of 22 to 24 m beam counted as 25 m and
        # so as too wide for the 24 m chambers of Kreekrak and Hansweert, which it had just come through; it was
        # removed for "no exit reachable" (nine a run, run 0021). "No" by the class is asked again by its own size
        r = self.reach(ship, exact=True)
        return bool(r[a] and r[b])

    def choose_target(self, ship):
        """Node the next voyage ends at, and what is reserved there (ship.berth, tentatively)."""
        shift = getattr(ship, "shift", None)           # a further call: it leaves its berth for another one
        if shift and getattr(ship, "next_berth", None):
            return ship.next_berth["node"]             # already reserved (re-planning)
        if shift and self.t - ship.shift_since > NEXT_CALL_WAIT_MIN:
            ship.note(self.t, "next_call_dropped", destination=shift)
            ship.shift = shift = None                  # no berth there for hours: it leaves instead
        if ship.departing and not shift:
            options = [ship.exit or "exit_sea_north"] + [e for e in SEA_EXITS if e != ship.exit]
            for exit_ in options:
                name = exit_[5:]
                if name == "sea_north" and ship.needs_pilot and not self.north_gate_ok(ship):
                    continue
                if name in self.places and (ship.at is None or
                                            self.voyage_reachable(ship, ship.at, self.places[name]["node"])):
                    if exit_ != ship.exit:
                        ship.note(self.t, "exit_changed", planned=ship.exit, new=exit_)
                        ship.exit = exit_
                    return self.places[name]["node"]
            ship.infeasible = "no exit reachable at high water"
            return None
        if ship.berth and not shift:                   # already chosen (re-planning)
            return ship.berth["node"]
        prev = getattr(ship, "candidate", None)
        ship.candidate = None                          # set below only when a destination is free now
        if ship.terminal:
            T = self.terminals[ship.terminal]
            fits = any(b - a >= ship.loa for a, b in T.suitable_intervals(ship.draught, ship.sea_going))
            s0 = (T.find_position(ship.loa, draught=ship.draught, sea_going=ship.sea_going, at=self.quay_eta(ship))
                  if fits else None)
            waited_quay = self.t - self.terminal_waiting.get(T.name, {}).get(ship.id, self.t)
            if s0 is None and ship.ulcv and not ship.departing and (not fits or waited_quay >= ULCV_FALLBACK_AFTER_MIN):
                # ULCV: the fallback berth its agent has to name (regs §8.11): for when its own quay stays
                # taken, not whenever it is taken on arrival (four in ten ULCVs changed terminal)
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
            while first is not None and first != ship.id:
                # the first in the queue goes first only while quay is what it waits for. One that has room by
                # now and waits for something else (its tide, a pilot, the VTS) leaves the queue: it kept
                # DP World's quay empty for four days with seven ships at anchor behind it (replications 0003)
                f = self.by_id.get(first)
                if (f is not None and f.state != State.EXITED and f.berth is None and f.terminal == T.name
                        and T.find_position(f.loa, draught=f.draught, sea_going=f.sea_going, at=self.quay_eta(f)) is None):
                    break
                queue.pop(first)
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
        zone = shift or ship.berth_zone or ship.destination
        if zone in SEA_EXITS and ship.at is not None and (
                (zone == "exit_sea_north" and ship.needs_pilot and not self.north_gate_ok(ship))
                or not self.voyage_reachable(ship, ship.at, self.places[zone[5:]]["node"])):
            for alt in SEA_EXITS:                      # through traffic too deep for this sea exit: another one
                if self.voyage_reachable(ship, ship.at, self.places[alt[5:]]["node"]):
                    ship.note(self.t, "exit_changed", planned=zone, new=alt)
                    ship.destination = zone = alt
                    break
        if zone in AWAY_CALLS and AWAY_CALLS[zone] in self.places:
            ship.candidate = {"kind": "place", "node": self.places[AWAY_CALLS[zone]]["node"], "name": zone}
            return ship.candidate["node"]
        if zone.startswith("exit_") or zone in self.places:
            name = zone[5:] if zone.startswith("exit_") else zone
            if name in self.places:
                calls = PORT_PLACES + (SEA_CALL_PLACES if ship.sea_going else INLAND_CALL_PLACES)
                kind = "place" if name in calls and not zone.startswith("exit_") else "exit"
                node = self.port_node(name, ship) if name in PORT_PLACES else self.places[name]["node"]
                if name == "vlissingen" and kind == "place":
                    node = self._vlissingen_node(ship, node)
                ship.candidate = {"kind": kind, "node": node, "name": name}
                return ship.candidate["node"]
        dest = self.destinations.get(zone)
        if not dest:
            return None
        ids = dest["berths"]
        share = ZONE_RIVER_SIDE_SHARE.get(zone)
        if share:                                      # river side or behind the locks, by the AIS share of the calls
            drawn = getattr(ship, "call_side", None)
            if not drawn or drawn[0] != (zone, getattr(ship, "calls", 1)):
                river = bool(self.ship_rng(ship, "choice").random() < share["sea_going" if ship.sea_going else "inland"])
                drawn = ship.call_side = ((zone, getattr(ship, "calls", 1)), river)
            side = [i for i in ids if self.berths[i]["nodes"] and self._behind_locks(self.berths[i]["nodes"][0]) != drawn[1]]
            where = ZONE_RIVER_KM_SHARE.get(zone)
            if side and drawn[1] and where and not ship.sea_going:
                # an inland craft at a waiting place on the river: where the AIS has these calls, lying alongside
                # (a waiting place holds many craft; it is no berth of the register)
                if len(drawn) < 3:
                    km = self.fg.chainage_m / 1000.0
                    groups = [[self.berths[i]["nodes"][0] for i in side if lo <= km[self.berths[i]["nodes"][0]] < hi]
                              for lo, hi, _ in where]
                    w = np.array([p if g else 0.0 for g, (_, _, p) in zip(groups, where)], dtype=float)
                    g = groups[int(self.ship_rng(ship, "choice").choice(len(groups), p=w / w.sum()))]
                    drawn = ship.call_side = drawn + (int(g[int(self.ship_rng(ship, "choice").integers(len(g)))]),)
                node = drawn[2]
                ship.candidate = {"kind": "berth", "id": None, "node": node, "nodes": [node], "zone": zone}
                return node
            if side:
                ids = side
                dest = dict(dest, node=self.berths[side[len(side) // 2]]["nodes"][0])
        fits = [b for b in ids if self._berth_fits(self.berths[b], ship)]
        relaxed = not fits
        if relaxed:                                    # nothing fits even empty: relax the tanker rule
            fits = [b for b in ids if self._berth_fits(self.berths[b], ship, ignore_tanker=True)]
        if relaxed and not ship.sea_going:
            # an inland craft calling where no berth is of its kind lies alongside, not on a quay: an inland tanker
            # at a container terminal is a bunker barge alongside a ship (AIS: 337 such calls in 30 days took
            # container quay as if they were ships of their own)
            fits = []
        if not fits and ship.sea_going:
            # the zone drawn has no berth this ship could ever take (its size and draught are drawn apart from its
            # destination). It used to be removed, one ship a day; now its next call is not made, or its
            # destination is drawn again among the zones that have a berth for it
            if shift:
                ship.note(self.t, "next_call_unfit", destination=shift)
                ship.shift = None
                return self.choose_target(ship)
            if ship.cls == "container" and self._cap_draught_to_zone(ship, zone, ids):
                return self.choose_target(ship)
            other = self._redraw_destination(ship, zone)
            if other is None:
                ship.infeasible = f"no berth in {zone} fits or can be reached"
                return None
            ship.note(self.t, "destination_redrawn", planned=zone, new=other)
            ship.destination = ship.berth_zone = other
            return self.choose_target(ship)
        free = [b for b in fits if b not in self.berth_ship and self.berths_for(b, ship)]
        pick = None
        if prev and prev.get("kind") == "berth" and prev.get("id") in free:
            pick = prev["id"]                          # keep the berth drawn earlier while it stays free
        elif free:
            pick = self.draw_berth(free, ship)
        elif ship.sea_going and ship.cls != "tanker":  # a sea-going tanker waits for a tanker berth (regs §10.5);
            loose = [b for b in ids if self._berth_fits(self.berths[b], ship, ignore_tanker=True) and b not in self.berth_ship
                     and self.berths_for(b, ship)]
            if loose:
                pick = self.draw_berth(loose, ship)
        # an inland craft with no free berth of its kind lies alongside (below) rather than on a berth of the other
        # kind: inland tankers took container quay as bunker barges, 120 calls in 12 days
        if pick is None:
            if ship.sea_going:
                return None                            # wait for a berth (at anchor)
            stretch = None if relaxed or ship.cls != "inland_tanker" else self.tank_barge_stretch(ship, zone)
            if stretch is not None:                    # an inland tanker lies at a tank-barge stretch of the zone
                node = stretch["nodes"][len(stretch["nodes"]) // 2]
                ship.candidate = {"kind": "berth", "id": None, "node": node, "nodes": [node], "zone": zone,
                                  "stretch": stretch["id"]}
                ship.note(self.t, "tank_barge_berth", zone=zone, place=stretch["id"])
                return node
            if not relaxed:                            # room beside the zone's berths (ALONGSIDE_PER_BERTH)
                lying = sum(1 for s in self.ships if s is not ship and (s.berth or {}).get("alongside") == zone)
                if lying >= ALONGSIDE_PER_BERTH * len(fits):
                    if not getattr(ship, "berth_wait_noted", None) == zone:
                        ship.berth_wait_noted = zone
                        ship.note(self.t, "berth_wait", zone=zone)
                    return None
            ship.note(self.t, "alongside", zone=zone, why="no berth of its kind" if relaxed else "no free berth")
            node = dest["node"]                        # inland craft: lie alongside at the zone
            ship.candidate = {"kind": "berth", "id": None, "node": node, "nodes": [node], "zone": zone,
                              "alongside": None if relaxed else zone}
            return node
        b = self.berths[pick]
        ship.candidate = {"kind": "berth", "id": pick, "node": b["nodes"][len(b["nodes"]) // 2], "nodes": b["nodes"], "zone": zone,
                          "across": self.berths_for(pick, ship)}
        return ship.candidate["node"]

    def unreachable_resolved(self, ship, now):
        """A voyage that has no route at high water, where the cause is a draw made apart from the ship's draught
        (three ships a run were removed, run 0023). True when it is put right, and the ship plans again:
        - a further call it cannot reach (a tanker of 9.5 m sent on to the Zuid-Beveland canal): the call is not made;
        - a sea-going ship entering from a canal deeper than the canal carries (8.8 m from the Schelde-Rijn canal):
          it came through the canal, so its draught is lowered, in half metres, to what gets it to its target."""
        shift = getattr(ship, "shift", None)
        if shift and not getattr(ship, "next_berth", None):
            ship.note(now, "next_call_unfit", destination=shift, why="no route")
            ship.shift = None
            ship.candidate = None
            return True
        if (ship.sea_going and not ship.departing and ship.at is not None and ship.target is not None
                and self.graph.nodes[ship.at].get("region") == "canal"):
            drawn = ship.draught
            d = math.ceil(drawn * 2) / 2 - 0.5
            while d >= 2.5:
                ship.draught = d
                if self.voyage_reachable(ship, ship.at, ship.target):
                    ship.note(now, "draught_capped", drawn=drawn, allowed=d, source=ship.source)
                    return True
                d -= 0.5
            ship.draught = drawn
        return False

    def _cap_draught_to_zone(self, ship, zone, ids):
        """A container ship of the schedule bound for a zone (a terminal that is not modelled as a quay) with a
        draught, drawn from its TEU, that no berth there allows: a real one calls loaded to what the berth and the
        lock allow (as terminal_draught does at the four terminals). Its draught is lowered, in half metres, to
        the deepest a berth of the zone takes; False if none takes it at any draught."""
        drawn = ship.draught
        d = math.ceil(drawn * 2) / 2 - 0.5
        while d >= 8.0:
            ship.draught = d
            if any(self._berth_fits(self.berths[b], ship, ignore_tanker=True) for b in ids):
                ship.note(self.t, "draught_capped", drawn=drawn, allowed=d, zone=zone)
                return True
            d -= 0.5
        ship.draught = drawn
        return False

    def _redraw_destination(self, ship, zone):
        """Another berth zone for a sea-going ship that no berth of `zone` could take: drawn by its class's
        destinations (BT.P_DESTINATION_GIVEN_CLASS) among the zones with a berth for it; None if there is none."""
        names, w = [], []
        for z, q in BT.P_DESTINATION_GIVEN_CLASS.get(ship.cls, {}).items():
            d = self.destinations.get(z)
            if z != zone and d and q > 0 and any(self._berth_fits(self.berths[b], ship, ignore_tanker=True) for b in d["berths"]):
                names.append(z)
                w.append(q)
        if not names:
            return None
        return names[int(self.ship_rng(ship, "choice").choice(len(names), p=np.array(w) / sum(w)))]

    def _vlissingen_node(self, ship, node):
        """Where a call at Vlissingen lies: Vlissingen-Oost (the place), or for a share of the inland craft the
        town (VLISSINGEN_TOWN_SHARE), drawn once a call."""
        share = VLISSINGEN_TOWN_SHARE.get("sea_going" if ship.sea_going else "inland", 0.0)
        if share <= 0.0:
            return node
        drawn = getattr(ship, "vlissingen_call", None)
        if not drawn or drawn[0] != getattr(ship, "calls", 1):
            drawn = ship.vlissingen_call = (getattr(ship, "calls", 1), bool(self.ship_rng(ship, "choice").random() < share))
        if not drawn[1]:
            return node
        if not hasattr(self, "_vlissingen_town"):
            from pyproj import Transformer
            x, y = Transformer.from_crs("EPSG:4326", self.graph.graph["crs"], always_xy=True).transform(*VLISSINGEN_TOWN)
            ok = np.flatnonzero(~self.mover.special & np.isin(self.mover.zone_label, ("river", "sea", "dock")))
            self._vlissingen_town = int(ok[np.argmin(np.hypot(self.fg.x[ok] - x, self.fg.y[ok] - y))])
        town = self._vlissingen_town
        return town if self.reach(ship)[town] else node

    def _behind_locks(self, node):
        """Does this cell lie in a dock behind the locks (a basin with a level of its own)?"""
        return bool(self.graph.nodes[node].get("basin"))

    def tank_barge_stretch(self, ship, zone):
        """A free stretch of the zone where inland tank barges may lie (harbour master, "Tankvaart"), allowed for
        its cargo: a barge with dangerous goods (AIS hazard category) not on a no-cone stretch, one without not on
        a stretch only for one-cone barges. Room by length: the barges on it, end to end, 10 m apart. The reachable
        one with the most room left; None if none has room."""
        if not hasattr(self, "_stretch_ships"):
            self._stretch_ships = {}
            self._stretches = {}
            for t in self.graph.graph.get("tank_barge_berths", []):
                self._stretches.setdefault(t["zone"], []).append(t)
        reach = self.reach(ship)
        best, room_best = None, 0.0
        for t in self._stretches.get(zone, []):
            if (ship.dg and t["class"] in (1, 3)) or (not ship.dg and t["class"] == 5):
                continue
            used = sum(self.by_id[s].loa + 10.0 for s in self._stretch_ships.get(t["id"], ()) if s in self.by_id)
            room = t["length_m"] - used
            if room >= ship.loa and any(reach[n] for n in t["nodes"]) and room > room_best:
                best, room_best = t, room
        return best

    def draw_berth(self, ids, ship):
        """A berth of the zone, weighted by the calls AIS saw there by ships of this class (other classes count
        for little, and a berth nobody was seen at for less): all the berths of a zone alike sent ships to
        old quays nobody uses, some reached only through locks that are hardly used."""
        w = np.array([(self.berths[b].get("calls") or {}).get(ship.cls, 0)
                      + 0.1 * sum((self.berths[b].get("calls") or {}).values()) + 0.05 for b in ids], dtype=float)
        return ids[int(self.ship_rng(ship, "choice").choice(len(ids), p=w / w.sum()))]

    def quay_eta(self, ship):
        """The minute a ship cleared now is planned to need its quay: now for a ship inside the area's
        river and docks; for one at sea (entering, or at a sea anchorage) the planned voyage later, less
        BERTH_CHANGE_MIN, so that a ship leaves that long before the next one is due on its metres."""
        a = self.anchorages.get(ship.anchorage) if ship.anchorage else None
        if ship.anchorage and not (a and a.sea_anchorage):
            return self.t
        lead = self.voyage_minutes(ship)
        return self.t if lead is None else self.t + max(lead - BERTH_CHANGE_MIN, 0.0)

    def destination_free(self, ship):
        """After plan_route: is the destination it chose free? (No new choice: drawing again could give
        another berth than the one the route goes to, and the ship would be booked at one and moor at
        the other, on top of whoever got that one.)"""
        if getattr(ship, "shift", None):
            return getattr(ship, "next_berth", None) is not None or getattr(ship, "candidate", None) is not None
        return ship.departing or ship.berth is not None or getattr(ship, "candidate", None) is not None

    def reserve_destination(self, ship, now):
        c = getattr(ship, "candidate", None)
        shift = getattr(ship, "shift", None)
        if c is None or (getattr(ship, "next_berth", None) if shift else (ship.departing or ship.berth)):
            return
        if c["kind"] == "terminal":
            T = self.terminals[ship.terminal]
            if T.moor(ship.id, ship.loa, now, s0=c["s0"], at=self.quay_eta(ship), arrived=False) is None:
                return
        elif c["kind"] == "berth" and c.get("stretch") is not None:
            self._stretch_ships.setdefault(c["stretch"], set()).add(ship.id)
        elif c["kind"] == "berth" and c["id"]:
            c["across"] = self.berths_for(c["id"], ship) or [c["id"]]   # as they are now
            for i in c["across"]:
                self.berth_ship[i] = ship.id
            if len(c["across"]) > 1:
                ship.note(now, "berths_across", n=len(c["across"]), berth=c["id"])
        if shift:
            ship.next_berth = c                        # it still lies at ship.berth until it has unmoored
        else:
            ship.berth = c

    # ------------------------------------------------------------------ pilots
    def _pilot_arrays(self):
        if getattr(self, "_pz_code", None) is None:              # pilot zone per node, once
            fg = self.fg
            names = ("sea", "river", "dock")
            self._pz_names = names
            self._pz_code = np.array([names.index(self.pilot_zone(n)) for n in range(fg.n)], dtype=np.int8)
            self._is_lock = np.zeros(fg.n, dtype=bool)
            self._is_lock[list(self.lock_of_node)] = True

    def pilot_stretches(self, route):
        """The pilot stretches of a route: [(zone, route index where it starts)], the first at index 0.
        Only water cells count (lock, anchorage and approach nodes have no zone of their own: an anchorage
        at sea is not "river"). Between locks, a stretch of another zone shorter than MIN_PILOT_STRETCH_M
        is sailed with the pilot on board (taken by the previous stretch; the first one by the next): a
        departure from Vlissingen to sea takes a sea pilot, not a river pilot for 500 m. A lock always
        ends a stretch (river -> dock); equal zones either side of it stay one stretch, as before."""
        self._pilot_arrays()
        fg = self.fg
        r = np.asarray(route, dtype=np.int64)
        if len(r) == 0:
            return []
        d = np.r_[0.0, np.cumsum(np.hypot(np.diff(fg.x[r]), np.diff(fg.y[r])))]
        water = ~self.mover.special[r] & ~self._is_lock[r]
        pieces, cur = [], []
        for i in range(len(r)):
            if self._is_lock[r[i]]:
                pieces.append(cur)
                cur = []
            elif water[i]:
                cur.append(i)
        pieces.append(cur)
        out = []
        for piece in pieces:
            if not piece:
                continue
            idx = np.asarray(piece)
            z = self._pz_code[r[idx]]
            starts = np.r_[0, np.flatnonzero(z[1:] != z[:-1]) + 1]
            ends = np.r_[starts[1:], len(idx)]
            # [zone, first index, length]: a run lasts to the start of the next one (or to its last cell)
            runs = [[int(z[a]), int(idx[a]), float(d[idx[b]] - d[idx[a]]) if b < len(idx) else float(d[idx[-1]] - d[idx[a]])]
                    for a, b in zip(starts, ends)]
            while len(runs) > 1:
                k = min(range(len(runs)), key=lambda j: runs[j][2])
                if runs[k][2] >= MIN_PILOT_STRETCH_M:
                    break
                if k > 0:                              # the pilot on board carries on through it
                    runs[k - 1][2] += runs[k][2]
                else:                                  # the first: the next stretch's pilot boards at the start
                    runs[1][1], runs[1][2] = runs[0][1], runs[1][2] + runs[0][2]
                del runs[k]
                merged = []
                for run in runs:
                    if merged and merged[-1][0] == run[0]:
                        merged[-1][2] += run[2]
                    else:
                        merged.append(run)
                runs = merged
            for zc, i0, _ in runs:
                if not out or out[-1][0] != self._pz_names[zc]:
                    out.append((self._pz_names[zc], i0))
        if not out:
            return [(self.pilot_zone(int(r[0])), 0)]
        out[0] = (out[0][0], 0)
        return out

    def first_pilot_zone(self, route):
        return self.pilot_stretches(route)[0][0]

    def pilot_zone_at_head(self, ship):
        """The pilot stretch the ship's bow is in (pilot_stretches of its whole voyage, kept per route)."""
        cache = getattr(ship, "_pz_cache", None)
        if cache is None or cache[0] is not ship.full_route:
            cache = (ship.full_route, self.pilot_stretches(ship.full_route))
            ship._pz_cache = cache
        i = ship.seg_start + int(np.searchsorted(ship.s, ship.head, side="right")) - 1
        zone = cache[1][0][0]
        for z, start in cache[1]:
            if start > i:
                break
            zone = z
        return zone

    def pilot_plan(self, ship, route, now):
        """The later pilot stretches of a voyage: [(zone, ETA)] at each change of pilot stretch along the
        route, sailing at its planning speed plus LOCK_TRANSIT_MIN per lock before the change."""
        fg = self.fg
        r = np.asarray(route, dtype=np.int64)
        if len(r) < 2:
            return []
        stretches = self.pilot_stretches(route)
        d = np.r_[0.0, np.cumsum(np.hypot(np.diff(fg.x[r]), np.diff(fg.y[r])))]
        locks = np.cumsum(self._is_lock[r])
        v = ship.stw_kn("river", NR.planning_speed_kn) * 1852.0 / 60.0
        return [(z, now + d[i] / v + locks[i] * LOCK_TRANSIT_MIN) for z, i in stretches[1:]]

    @staticmethod
    def book_time(eta, now):
        """From when a later pilot is booked: PILOT_BOOK_MARGIN_MIN before the ship gets there, never
        before now (a booking in the past could never be met: no pilot is free before now, and the
        ship would wait for the VTS forever, as departures from Vlissingen did)."""
        return max(eta - PILOT_BOOK_MARGIN_MIN, now)

    def pilot_available(self, ship, start_node, now, route=None):
        """A pilot for the first stretch now (and a pilot boat for a boarding at sea / Vlissingen), and,
        with the route, pilots that can be booked for every later stretch when the ship gets there."""
        if not ship.needs_pilot:
            return True
        zone = self.first_pilot_zone(route) if route is not None else self.pilot_zone(start_node)
        boat = ship.state in (State.WAIT_CLEARANCE, State.ANCHORED) and not ship.departing and zone in ("sea", "river")
        if not (self.pilots.available(zone, ship.pilots_needed(zone), now, ship.id)
                and (not boat or self.pilot_boats.available(now) > 0)):
            return False
        if route is not None:
            for z, eta in self.pilot_plan(ship, route, now):
                if not self.pilots.can_book(z, ship.pilots_needed(z), self.book_time(eta, now), now, ship.id):
                    return False
        return True

    def book_pilots(self, ship, route, now):
        """Book the pilots for the later stretches; False (and nothing booked) if one cannot be."""
        for z, eta in self.pilot_plan(ship, route, now):
            if not self.pilots.book(z, ship.pilots_needed(z), ship.id, self.book_time(eta, now), now):
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

    def voyage_minutes(self, ship):
        """Planned minutes from entering the area to lying at its terminal: the approach to the pilot station,
        boarding, the voyage to the middle of the terminal's quay at its planning speed (speed limits and
        LOCK_TRANSIT_MIN per lock included), the pilot changes and the mooring. None if it cannot be planned."""
        place, T = self.places.get(ship.source), self.terminals.get(ship.terminal)
        if place is None or T is None or not ship.needs_pilot:
            return None
        key = (ship.source, ship.terminal, math.ceil(ship.draught), math.ceil(ship.loa / 50), math.ceil(ship.beam / 10))
        if key not in self.lead_min:
            station = self.places[STATION_OF_SOURCE.get(ship.source, "pilot_station_wandelaar")]["node"]
            nodes = T.nodes_at(0.0, T.quay_length_m)
            a = self.approach_route(place["node"], station, ship)
            b = self.tidal_route(station, nodes[len(nodes) // 2], ship) if nodes else None
            lead = None
            if a is not None and b is not None:
                own, ship.speed_factor = ship.speed_factor, 1.0     # at its class's speed: the plan is kept per class
                minutes = sum(float(self.vts._times(ship, np.asarray(r, dtype=np.int64))[-1]) for r in (a, b) if len(r) > 1)
                ship.speed_factor = own
                lead = (minutes + BOARDING_MIN + PILOT_CHANGE_MIN * max(len(self.pilot_stretches(b)) - 1, 0)
                        + PI.mooring_minutes(ship.loa, "arrival", "dock" if self.route_has_lock(b) else "tidal"))
            self.lead_min[key] = lead
        return self.lead_min[key]

    def slow_down_min(self, ship, now):
        """Minutes a container ship entering now would be early for its berth time (the schedule and its delay):
        it slows down at sea and enters that much later, so that it berths at its time, not before it (virtual
        arrival). 0 for a ship that is on time or late, and for one without a berth time."""
        due = ship.schedule.get("berth_min") if ship.schedule else None
        if due is None or ship.terminal is None:
            return 0.0
        lead = self.voyage_minutes(ship)
        wait = 60.0 * (getattr(ship, "anchor_wait_h", None) or 0.0)    # it lies at anchor first
        if lead is None:
            return 0.0
        return max(self._quay_free_at(ship, max(due, now + lead + wait)) - lead - wait - now, 0.0)

    def _quay_free_at(self, ship, at):
        """The first minute from `at` at which the ship's quay has room for it, by the ships lying there and when
        they are to leave (VIRTUAL_ARRIVAL_LOOKAHEAD_H); `at` itself when it has room then or none comes soon."""
        T = self.terminals.get(ship.terminal)
        if T is None:
            return at
        for k in range(int(VIRTUAL_ARRIVAL_LOOKAHEAD_H * 60 / VIRTUAL_ARRIVAL_STEP_MIN) + 1):
            t = at + k * VIRTUAL_ARRIVAL_STEP_MIN
            if T.find_position(ship.loa, draught=ship.draught, sea_going=ship.sea_going, at=t) is not None:
                return t
        return at

    def enter(self, ship, now):
        """A ship from the generator: into the area now, or kept at sea until it is in time for its berth."""
        wait = self.slow_down_min(ship, now)
        if wait >= DT_MIN:
            ship.slowed_min = round(wait, 1)
            ship.spawn_t = now + wait
            self.at_sea.append(ship)
        else:
            self.spawn(ship)

    def spawn(self, ship):
        now = self.t
        self.n_entered += 1
        self.terminal_draught(ship)
        ship.arrival_draught = ship.draught
        ship.speed_factor = float(np.clip(math.exp(self.ship_rng(ship, "speed").normal(0.0, SPEED_SPREAD)), *SPEED_FACTOR_RANGE))
        ship.set_state(State.SPAWNED, now, source=ship.source, destination=ship.destination, cls=ship.cls)
        if getattr(ship, "slowed_min", 0.0):
            ship.note(now, "virtual_arrival", minutes=ship.slowed_min)
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
                # it lay at anchor before it asks (AIS: anchor stays of a median 11-24 h; asking at once made
                # three in four anchor stays last minutes)
                wait = getattr(ship, "anchor_wait_h", None)
                ship.anchor_until = now + 60.0 * (wait if wait is not None else ANCHOR_WAIT_FACTOR.get(ship.cls, 1.0)
                                                  * BT.sample_anchorage_wait(ship.cls, self.ship_rng(ship, "service")))
                self.vts.request(ship, now)            # it waits at anchor for its clearance like any arrival
            else:                                      # no pilot needed: it weighs anchor and sails
                self.anchorages[ship.anchorage].leave(ship.id, now)
                ship.anchorage = None
                ship.set_state(State.WAIT_CLEARANCE, now)
                self.go(ship, now)
            return
        if ship.source in NORTH_SOURCES and ship.needs_pilot and not self.north_gate_ok(ship):
            ship.note(now, "station_changed", to="pilot_station_wandelaar")
            ship.source = "sea_west"
            node = self.places["sea_west"]["node"]
        ship.at = node
        sea = self.mover.zone_label[node] == "sea" or self.graph.nodes[node]["region"] == "sea"
        if sea and ship.needs_pilot:
            name = STATION_OF_SOURCE.get(ship.source, "pilot_station_wandelaar")
            station = self.places[name]["node"]
            r = self.approach_route(node, station, ship)
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
        ship.infeasible = None
        route = self.plan_route(ship, now)
        if route is None:
            if ship.infeasible is None and ship.target is not None and ship.at is not None \
                    and not self.voyage_reachable(ship, ship.at, ship.target) and not self.unreachable_resolved(ship, now):
                ship.infeasible = "no route at high water"
            if ship.infeasible:                        # never: without this it asked again for the whole run
                ship.note(now, "infeasible", why=ship.infeasible)
                self.finish(ship, now, "infeasible")
                return
            ship.retries = getattr(ship, "retries", 0) + 1
            if ship.retries == 1 or ship.retries % 10 == 0:
                ship.note(now, "no_route_or_berth", tries=ship.retries)
            ship.retry_at = now + min(30.0 * 2 ** min(ship.retries - 1, 4), 480.0)
            if ship.state != State.WAIT_CLEARANCE:
                ship.set_state(State.WAIT_CLEARANCE, now)
            return
        self.reserve_destination(ship, now)
        if getattr(ship, "shift", None):
            self._leave_berth(ship, now)
            self._to_next_call(ship)
        self.start_voyage(ship, route, now)

    def _to_next_call(self, ship):
        """The ship has left its berth for its next call: from here on it is a ship on its way to a berth."""
        ship.destination, ship.berth_zone = ship.shift, None
        ship.berth, ship.next_berth, ship.shift, ship.departing = getattr(ship, "next_berth", None), None, None, False

    def _further_call(self, ship, zone, now):
        """Where a sea-going ship calls next after its call in this zone (NEXT_CALL, AIS: bulk carriers and
        tankers make two calls a visit), or None when it leaves the port."""
        if not ship.sea_going or ship.level == 1 or not zone or ship.cls not in BT.NEXT_CALL:
            return None
        ship.calls = getattr(ship, "calls", 1) + 1
        following = BT.sample_next_call(ship.cls, self.ship_rng(ship, "choice"), zone) if ship.calls <= INLAND_MAX_CALLS else None
        if following:
            ship.note(now, "next_call", destination=following)
            ship.shift_since = now
        return following

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
        ship.at_station = False
        if ship.state == State.ANCHORED:
            self.anchorages[ship.anchorage].leave(ship.id, now)
            ship.note(now, "anchor_up", anchorage=ship.anchorage)
            ship.at = self.anchorage_node[ship.anchorage]
            ship.anchorage = None
            route = self.voyage_route(ship, ship.at, ship.target) or route
        zone = self.first_pilot_zone(route)
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
        if self._inland_anchor_stop(ship, route, now):
            return
        self.sail(ship, route, State.SAILING, now)

    def _inland_anchor_stop(self, ship, route, now):
        """An inland craft whose route passes one of its class's anchorages may stop there on the way
        (INLAND_ANCHOR_STOP_P, once a visit): it sails to the anchorage, lies there for a fitted anchor stay and
        then sails on to the same target (_timers). True if it is on its way to anchor."""
        p = INLAND_ANCHOR_STOP_P.get(ship.cls, 0.0)
        if p <= 0.0 or ship.sea_going or getattr(ship, "anchor_stopped", False) or route is None or len(route) < 2:
            return False
        # the fit's zone names ("anchorage_everingen_a") -> the mesh's anchorages ("Everingen A")
        key = {"anchorage_" + "".join(ch if ch.isalnum() else "_" for ch in n.lower()): n for n in self.anchorage_node}
        shares = {key[z]: p_z for z, p_z in BT.P_ANCHORAGE_GIVEN_CLASS.get(ship.cls, {}).items() if z in key}
        if not shares:
            return False
        fg, r = self.fg, np.asarray(route, dtype=np.int64)
        near = []
        for a in shares:
            node = self.anchorage_node[a]
            if float(np.min(np.hypot(fg.x[r] - fg.x[node], fg.y[r] - fg.y[node]))) <= INLAND_ANCHOR_NEAR_M:
                near.append(a)
        if not near:
            return False
        ship.anchor_stopped = True                     # one draw a visit, on its first voyage past an anchorage
        if self.ship_rng(ship, "service").random() >= p:
            return False
        w = np.array([shares[a] for a in near], dtype=float)
        name = near[int(self.ship_rng(ship, "service").choice(len(near), p=w / w.sum()))]
        a = self.anchorages[name]
        if not a.has_room(ship.loa, ship.draught):
            return False
        to = self.route(route[0], self.anchorage_node[name], ship)
        if to is None or len(to) < 2:
            return False
        ship.anchor_target, ship.after_anchor_target = name, route[-1]
        ship.inland_anchor_h = float(BT.sample_anchorage_wait(ship.cls, self.ship_rng(ship, "service")))
        ship.note(now, "inland_anchor_stop", anchorage=name, hours=round(ship.inland_anchor_h, 2))
        self.sail(ship, to, State.TO_ANCHORAGE, now)
        return True

    def _inland_anchor_up(self, ship, now):
        """The anchor stay of an inland craft is over: on to the target it had."""
        if ship.anchorage:
            self.anchorages[ship.anchorage].leave(ship.id, now)
            ship.note(now, "anchor_up", anchorage=ship.anchorage)
        ship.anchorage, ship.inland_anchor_h = None, None
        target, ship.after_anchor_target = getattr(ship, "after_anchor_target", None), None
        ship.set_state(State.WAIT_CLEARANCE, now)
        r = self.voyage_route(ship, ship.at, target) if target is not None else None
        if r is None or len(r) < 2:
            self.go(ship, now)
            return
        self.sail(ship, r, State.SAILING, now)

    def sail(self, ship, route, state, now):
        free_from = getattr(route, "free_from", None)  # a voyage to a sea exit: the pilot leaves at the station
        ship.pilot_off_node = route[free_from - 1] if free_from else None
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
        """Sail to the nearest allowed anchorage with room that can be reached now; False if none (the
        ship keeps waiting where it is and the VTS tries again at its next round)."""
        pool = choose_anchorage(self.anchorages, ship.loa, ship.draught, dangerous_signals=ship.dg == "A",
                                tide_dependent=ship.tide_dependent, level_m=0.0)
        here = ship.at
        for a in sorted(pool, key=lambda a: (not a.sea_anchorage,
                                             math.hypot(self.fg.x[self.anchorage_node[a.name]] - self.fg.x[here],
                                                        self.fg.y[self.anchorage_node[a.name]] - self.fg.y[here]))):
            node = self.anchorage_node[a.name]
            r = self.route(here, node, ship) or self.route(here, node, ship, tide_bound=True)
            if r is None or not self.vts.tide_ok(ship, r, now):
                continue                               # not now: it would stop in the channel for the water
            # the sea anchorages lie outside the pilotage area; to any other it takes a sea pilot, who leaves
            # at the anchorage. No pilot free: another anchorage, or it waits (regs §1: LOA > 80 m)
            if ship.needs_pilot and not a.sea_anchorage and not ship.pilots:
                if not self.take_pilots(ship, "sea", now, boat=True):
                    continue
                ship.note(now, "pilot_to_anchorage", anchorage=a.name)
            ship.anchor_target = a.name
            self.sail(ship, r, State.TO_ANCHORAGE, now)
            return True
        if not ship.times.get("no_anchorage_noted"):
            ship.times["no_anchorage_noted"] = now
            ship.note(now, "no_anchorage")
        return False

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
        for stream in SHIP_STREAMS:                    # its own random streams are not needed any more
            ship.__dict__.pop("_rng_" + stream, None)
        if ship.anchorage:
            self.anchorages[ship.anchorage].leave(ship.id, now)
            ship.anchorage = None
        self.mover.release(ship)
        self.drop_pilots(ship, now)
        self.pilots.cancel(ship.id)
        if ship.berth:                                 # removed while holding a berth: it is free again
            self._leave_berth(ship, now)
        if getattr(ship, "next_berth", None):          # ... and so is the one reserved for its next call
            ship.berth, ship.next_berth = ship.next_berth, None
            self._leave_berth(ship, now)
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
            prio = 2 if ship.tide_dependent else 3 if ship.sea_going else 4     # (3: no lockage with it is held)
            # the least water over the sills during the passage: the lower of the two sides. (With the higher one a
            # ship of 7 to 10 m was sent to Terneuzen's 6 m chamber at high water on one side and lay at its gate
            # until the tide came, up to 7 h, with two deep chambers at work beside it)
            high = min(float(np.mean(self.level_now[d["nodes"]])) for d in lock.sides.values() if d["nodes"])
            request = ShipRequest(ship.id, ship.loa, ship.beam, ship.draught, side, prio,
                                  container=ship.cls == "container", ready_at=math.inf)
            try:
                chamber = lock.request(request, now, level_m=high)
            except ValueError:
                ship.note(now, "lock_does_not_fit", lock=lock.name)
                self.finish(ship, now, "lock_does_not_fit")
                return
            ship.lock = lock.name
            # it waits at the waiting place where it is, off the fairway and away from the lock, until its chamber
            # is called (_call_to_lock); from then on it lies at the gate
            ship.lock_request, ship.lock_chamber = request, chamber
            ship.queue_node = ship.cells[-1] if ship.cells else ship.route[-1]   # where it lies while queued
            ship.queue_gate = ship.route[-1]
            self.mover.release(ship)
            ship.set_state(State.LOCK_QUEUE, now, lock=lock.name, side=side)
            self._call_to_lock(ship, now)
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
            self.drop_pilots(ship, now)
            if getattr(ship, "inland_anchor_h", None) is not None:       # an inland craft stopping on its way
                if self.anchor(ship, ship.anchor_target, now):
                    ship.anchor_until = now + 60.0 * ship.inland_anchor_h
                else:                                  # no room after all: sails on
                    self._inland_anchor_up(ship, now)
                return
            if not self.anchor(ship, ship.anchor_target, now):
                ship.set_state(State.WAIT_CLEARANCE, now)
                if not self.send_to_anchorage(ship, now):
                    ship.at_station = True             # waits here; the VTS sends it on when one has room
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
            ship.timer = 60.0 * self.dwell_hours(ship, b["name"])
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
        # a berth stay runs out at its class's rate for the local day (BT.STAY_END_FACTOR): inland cargo craft lie
        # still over the weekend, so their stays end half as often then
        ts = self.now_ts(now)
        weekday = int((ts.tz_localize("UTC") if ts.tzinfo is None else ts).tz_convert(WEEK_TZ).dayofweek)
        stay_rate = {}
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
                    if T and not T.quay_clear(ship.id):        # the ship before it has not left yet
                        if not ship.times.get("quay_not_clear"):
                            ship.times["quay_not_clear"] = now
                            ship.note(now, "quay_not_clear")
                        continue
                    if T and not T.berthing_allowed(ship.loa, ship.berth["s0"], rising, after_hw):
                        continue
                    if not self._service_ready(ship, now, "arrival"):
                        continue
                    ship.timer = PI.mooring_minutes(ship.loa, "arrival", self._berth_area(ship), self.ship_rng(ship, "service"))
                ship.timer -= DT_MIN
                if ship.timer <= 0:
                    self._release_services(ship, now)
                    self.drop_pilots(ship, now)
                    self._moored(ship, now)
            elif st == State.AT_BERTH:
                if ship.timer is None:                 # container waiting for cranes
                    self._start_handling(ship, now)
                    continue
                if (ship.berth or {}).get("kind") == "terminal":
                    self._more_cranes(ship)
                if ship.terminal and cranes_stopped:   # STS cranes stopped by the wind
                    continue
                if (ship.berth or {}).get("kind") == "terminal":
                    ship.timer -= DT_MIN
                else:
                    ship.timer -= DT_MIN * self._stay_rate(stay_rate, ship.cls, weekday)
                if ship.timer <= 0:
                    self._ready_to_leave(ship, now)
            elif st == State.UNMOORING:
                if ship.timer is None:
                    T = self.terminals.get(ship.terminal) if (ship.berth or {}).get("kind") == "terminal" else None
                    if T and not T.departure_allowed(ship.id, rising, after_hw):
                        continue
                    if not self._service_ready(ship, now, "departure"):
                        continue
                    ship.timer = PI.mooring_minutes(ship.loa, "departure", self._berth_area(ship), self.ship_rng(ship, "service"))
                ship.timer -= DT_MIN
                if ship.timer <= 0:
                    self._release_services(ship, now)
                    self._leave_berth(ship, now)
                    if getattr(ship, "shift", None):
                        self._to_next_call(ship)
                    self.start_voyage(ship, ship.pending_route, now)
            elif st == State.DWELL_PORT:
                ship.timer -= DT_MIN * self._stay_rate(stay_rate, ship.cls, weekday)
                if ship.timer <= 0:
                    if self._next_call(ship, now):
                        continue
                    self._cargo_worked(ship, now)
                    following = self._further_call(ship, ship.berth["name"], now)
                    if following:                      # on to its next call: a ship on its way to a berth again
                        ship.destination, ship.berth_zone, ship.berth, ship.request_t = following, None, None, None
                        self.go(ship, now)
                        continue
                    ship.departing = True
                    ship.exit = (BT.sample_exit(ship.cls, self.ship_rng(ship, "choice"), ship.berth["name"], ship.source)
                                 if ship.cls in BT.P_EXIT_GIVEN_CLASS else "exit_sea_north")
                    ship.berth = None
                    self.go(ship, now)
            elif st == State.WAIT_CLEARANCE and not ship.needs_pilot and now >= getattr(ship, "retry_at", 0):
                self.go(ship, now)
            elif st == State.ANCHORED and getattr(ship, "inland_anchor_h", None) is not None and now >= ship.anchor_until:
                self._inland_anchor_up(ship, now)

    @staticmethod
    def _stay_rate(cache, cls, weekday):
        if cls not in cache:
            cache[cls] = BT.stay_end_factor(cls, weekday) if hasattr(BT, "stay_end_factor") else 1.0
        return cache[cls]

    def _moored(self, ship, now):
        b = ship.berth
        ship.set_state(State.AT_BERTH, now, berth=b.get("id") or ship.terminal)
        if b.get("kind") == "terminal":
            self.terminals[ship.terminal].ship(ship.id).arrived = True
            ship.timer = None
            self._start_handling(ship, now)
        else:
            hours = ship.dwell_h or self.dwell_hours(ship, b.get("zone"))
            ship.timer = 60.0 * hours

    def dwell_hours(self, ship, zone):
        """A drawn stay. An inland craft's is shortened for the trips the AIS missed (generator
        INLAND_TRIP_SCALE): the AIS stays of the calls it saw also hold those trips. The trips added for them make
        one call (generator: single_call), so the hours they add are one call's, not a visit's: with the trip
        scale s, the calls per visit grow by (s - 1) / INLAND_CALLS_PER_VISIT and the stays are divided by that."""
        hours = BT.sample_berth_dwell(ship.cls, self.ship_rng(ship, "service"), zone)
        scale = getattr(ship, "trip_scale", 1.0)
        return hours / (1.0 + (scale - 1.0) / INLAND_CALLS_PER_VISIT)

    def _start_handling(self, ship, now):
        T = self.terminals[ship.terminal]
        n = T.assign_cranes(ship.id, ship.cranes_wanted)
        # the ship is at the berth for its scheduled stay. The cranes are a placeholder (docs/PINNED.md): they
        # are shared out and shown, but do not set the stay. Making the stay depend on them (the work of the
        # scheduled stay with all the cranes a ship of its size gets) asked for more cranes than a terminal
        # has: at DP World, 13 cranes for three ships wanting 5 to 8 each, stays of 41 h for 30 h scheduled,
        # the quay full and nine in ten ships more than 12 h late (run 0039)
        # (so a ship that finds no crane free stays no longer either: waiting for one added 8 h to the 33 h
        # scheduled at DP World)
        stay_h = ship.stay_h or DEFAULT_STAY_H
        ship.moves = int(round(stay_h * n * T.moves_per_crane_h))
        # the hours it lies at the berth: its line's stay times the ratio drawn for it from the AIS calls matched
        # to their lines (generator: ZONE_OF_TERMINAL). The line's stay less an allowance for leaving, set on the
        # median, gave the AIS's median and too few ships at the berths: no long stays
        ship.timer = 60.0 * stay_h
        T.ship(ship.id).leaves = now + ship.timer + UNMOORING_PLAN_MIN
        ship.note(now, "handling", cranes=n, moves=ship.moves, hours=round(ship.timer / 60, 1))

    def _more_cranes(self, ship):
        """Cranes that have come free go to a ship working with fewer than it should have (it used to keep
        what it got when it moored: one crane for 9,000 moves, ten days at the quay)."""
        T = self.terminals[ship.terminal]
        have = T.ship(ship.id).cranes
        if have < ship.cranes_wanted:
            T.assign_cranes(ship.id, ship.cranes_wanted)     # shown, not timed (see _start_handling)

    def _next_call(self, ship, now):
        """An inland craft calls at several places on one visit (NEXT_CALL, AIS): after a call it may sail
        on to the next. True if it did; False if it leaves the port (or its next call cannot be reached
        now, when it leaves too). The unmooring of a hop is taken as part of the fitted stay."""
        if ship.sea_going or getattr(ship, "single_call", False):
            return False
        b = ship.berth or {}
        zone = b.get("zone") or b.get("name")
        ship.calls = getattr(ship, "calls", 1) + 1
        following = BT.sample_next_call(ship.cls, self.ship_rng(ship, "choice"), zone) if zone and ship.calls <= INLAND_MAX_CALLS else None
        if following is None:
            return False
        before = ship.destination, ship.berth_zone
        ship.destination, ship.berth_zone, ship.berth = following, None, None
        route = self.plan_route(ship, now)
        ship.berth = b
        if route is None or len(route) < 2:
            ship.destination, ship.berth_zone = before
            ship.candidate = None
            return False
        self._leave_berth(ship, now)
        ship.note(now, "next_call", destination=following)
        self.reserve_destination(ship, now)
        self.start_voyage(ship, route, now)
        return True

    def _cargo_worked(self, ship, now):
        """A ship leaves at another draught than it came in at (DRAUGHT_CHANGE, AIS), within the limit for
        leaving."""
        if not ship.sea_going:
            return
        ratio = min(max(BT.sample_draught_change(ship.cls, self.ship_rng(ship, "service"), ship.draught), 0.4), 1.6)
        before = ship.draught
        draught = round(min(before * ratio, DEPARTURE_MAX_DRAUGHT_M.get(ship.cls, math.inf)), 2)
        berth_limit = self.berths.get((ship.berth or {}).get("id"), {}).get("max_draught_m")
        if berth_limit and draught > before:
            draught = max(before, min(draught, float(berth_limit)))
        ship.draught = draught
        if draught > before and ship.at is not None and not self.reach(ship)[ship.at]:
            ship.draught = draught = before    # it loads only what it can sail away with
        if draught != before:
            ship.note(now, "draught_changed", drawn=before, new=draught)

    def _ready_to_leave(self, ship, now):
        if self._next_call(ship, now):
            return
        self._cargo_worked(ship, now)
        if (ship.berth or {}).get("kind") == "terminal":
            self.terminals[ship.terminal].assign_cranes(ship.id, 0)     # work done: the cranes go to the next ship
        ship.shift = self._further_call(ship, (ship.berth or {}).get("zone"), now)
        ship.departing = True
        zone = (ship.berth or {}).get("zone") or ("antwerp_deurganckdok" if ship.terminal in ("MPET", "DP World Antwerp Gateway") else "antwerp_river_quays")
        cls = ship.cls if ship.cls in BT.P_EXIT_GIVEN_CLASS else "bulk_general"
        ship.exit = BT.sample_exit(cls, self.ship_rng(ship, "choice"), zone, ship.source)
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
            self.reserve_destination(ship, now)        # (the berth of a further call; nothing for a ship leaving)
            self.start_unmooring(ship, now)

    def _leave_berth(self, ship, now):
        b = ship.berth or {}
        if b.get("kind") == "terminal":
            self.terminals[ship.terminal].unmoor(ship.id, now)
        elif b.get("id"):
            for i in b.get("across") or [b["id"]]:
                self.berth_ship.pop(i, None)
        elif b.get("stretch") is not None:
            self._stretch_ships.get(b["stretch"], set()).discard(ship.id)
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
        ship.lock, ship.lock_request, ship.lock_chamber = None, None, None
        # an inland craft through a lock on its way to anchor (_inland_anchor_stop) is still bound for the anchorage
        to_anchor = getattr(ship, "inland_anchor_h", None) is not None and not ship.anchorage
        ship.set_state(State.TO_ANCHORAGE if to_anchor else State.SAILING, t, lock_done=name)
        if not self.mover.place(ship):
            ship.waiting_space = True

    def _call_to_lock(self, ship, now):
        """A ship waiting for a lock is called when its chamber lies open at its side or is on its way there (it
        has closed at the other side). It then sails in from the waiting place (LOCK_SAIL_IN_KN) and may enter
        once it is at the gate."""
        request, c = getattr(ship, "lock_request", None), getattr(ship, "lock_chamber", None)
        if request is None or request.ready_at < math.inf:
            return
        side = request.from_side
        lock = self.locks[ship.lock][1]
        if request.priority <= HOLD_FREE_PRIORITY and not (c.side == side and c.state == "open"):
            c = self._free_chamber(ship, lock, request, c, now)
        fg = self.fg
        kn = LOCK_SAIL_IN_KN["sea_going" if ship.sea_going and ship.loa > lock.times.small_loa_m else "inland"]
        metres = math.hypot(fg.x[ship.queue_node] - fg.x[ship.queue_gate], fg.y[ship.queue_node] - fg.y[ship.queue_gate])
        minutes = metres / (kn * 1852.0 / 60.0) + (LOCK_SEA_COMING_IN_MIN.get(ship.lock, 0.0) if ship.sea_going else 0.0)
        coming = c.side != side and c.state != "open" and lock.minutes_to_open(c) <= minutes + LOCK_CALL_LEAD_MIN
        # a craft that would go in beside a sea-going ship called to this chamber and still sailing in is called
        # to be at the gate when that ship is: the barges go in after it. Called at once they went in first and lay
        # in the chamber while the ship came in, half an hour and more at the sea locks (inland craft 1.34 h to
        # pass Zandvliet-Berendrecht against 1.17 h, MODEL.md §19)
        ahead = [s.ready_at for s in c.queue[side] if s is not request and s.priority < request.priority
                 and now < s.ready_at < math.inf]
        if ahead and min(ahead) - now > minutes + LOCK_CALL_LEAD_MIN:
            return
        if (c.side == side and c.state == "open") or coming:
            request.ready_at = now + minutes
            ship.called_at = now
            ship.note(now, "lock_called", lock=ship.lock, chamber=c.name, sail_in_min=round(request.ready_at - now, 1))

    def _free_chamber(self, ship, lock, request, c, now):
        """A sea-going ship waiting for a chamber that is away from its side is moved to another chamber of the
        lock that lies open at its side, takes it at this water and has room for it in its next lockage, as the
        lock planner does. Its chamber otherwise. (A ship was held to the chamber it was queued at
        when it asked, and at Terneuzen (three chambers) waited for it while another stood open, sea-going
        passages 1.71 h at the 90th percentile against 1.33 h, MODEL.md §19.)"""
        side = request.from_side
        if request not in c.queue[side]:
            return c
        level = min(float(np.mean(self.level_now[d["nodes"]])) for d in lock.sides.values() if d["nodes"])
        for c2 in lock.chambers:
            if (c2 is c or c2.side != side or c2.state != "open" or not c2.fits_size(request.loa, request.beam)
                    or request.draught + lock.ukc_m > c2.sill_depth_m + level
                    or any(p.ship.from_side != side for p in c2.ships) or not in_next_lockage(lock, c2, request)):
                continue
            c.queue[side].remove(request)
            c2.queue[side].append(request)
            c2.queue[side].sort(key=lambda s: (s.priority, s.turn))
            ship.lock_chamber = c2
            ship.note(now, "lock_chamber_changed", lock=lock.name, old=c.name, new=c2.name)
            return c2
        return c

    def _locks(self, now):
        for ship in self.ships:
            if ship.state == State.LOCK_QUEUE:
                self._call_to_lock(ship, now)
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
        off = getattr(ship, "pilot_off_node", None)
        if ship.pilots and off is not None and \
                off in ship.full_route[:ship.seg_start + int(np.searchsorted(ship.s, ship.head, side="right"))]:
            # out at sea past the pilot station: the pilot leaves by pilot boat (if one is free; the ship does
            # not wait for it) and the ship sails the open-sea leg to its exit without one
            self.pilot_boats.take(now, PILOT_BOAT_MIN)
            self.drop_pilots(ship, now)
            ship.pilot_off_node = None
        if ship.needs_pilot and ship.pilots and ship.state == State.SAILING:
            zone = self.pilot_zone_at_head(ship)       # the pilot stretch, not the cell: no change for a short
            if zone != ship.pilot_zone:                # dip into another zone (pilot_stretches)
                self.drop_pilots(ship, now)
                ship.pilot_change_boat = zone == "river"          # boarding at Vlissingen by pilot boat
                # a change of pilot at a lock is made in the chamber during the lockage: it takes no time of its own
                # (the ship lay 10 min more beyond the gate, inside the kilometre a lock passage is timed over)
                at_lock = ship.seg_start > 0 and ship.full_route[ship.seg_start - 1] in self.lock_of_node and ship.head < 1500.0
                if at_lock and self.take_pilots(ship, zone, now, boat=False):
                    ship.note(now, "pilot_changed_in_lock", zone=zone)
                elif self.take_pilots(ship, zone, now, boat=ship.pilot_change_boat):
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
        due = [x for x in self.at_sea if x.spawn_t < now + DT_MIN]                # 2 arrivals
        if due:
            self.at_sea = [x for x in self.at_sea if x.spawn_t >= now + DT_MIN]
            for ship in due:
                self.spawn(ship)
        for ship in self.generator.arrivals(now, DT_MIN):
            self.enter(ship, now)
        if self.k % PLAN_EVERY == 0:                                              # 3 VTS
            self.vts.plan(now)
        self._locks(now)                                                          # 4 resources
        self._timers(now)
        for ship in self.ships:                                                   # ships waiting for room to start
            if getattr(ship, "waiting_space", False) and ship.state in MOVING + (State.SAILING,):
                if self.mover.place(ship):
                    ship.waiting_space = False
        sailing = [s for s in self.ships if s.state in MOVING and not getattr(s, "waiting_space", False)]
        arrived = self.mover.step(sailing, DT_MIN, self.k, self.streams["movement"])              # 5 movement
        for ship in sailing:
            if ship.state in MOVING and ship not in arrived:
                self._after_move(ship, now)
        for ship in arrived:                                                      # 6 ends of routes
            self._arrive_end(ship, now + DT_MIN)
        self._record(now)                                                         # 7 logging
        if self.checks:
            self.check_invariants(now)
        self.t += DT_MIN
        self.k += 1

    def check_invariants(self, now):
        """What must hold after every step, whatever the traffic (run with checks=True; tests/test_invariants.py).
        Raises AssertionError naming the first one broken."""
        def fail(what):
            raise AssertionError(f"step {self.k} (day {now / 1440:.2f}): {what}")

        # ships: every ship that entered is in the area or done, once
        if self.n_entered != len(self.ships) + len(self.done):
            fail(f"{self.n_entered} ships entered, {len(self.ships)} in the area + {len(self.done)} done")
        ids = [x.id for x in self.ships]
        if len(set(ids)) != len(ids):
            fail("a ship is in the area twice")
        active = set(ids)
        for x in self.ships:
            if x.state == State.EXITED:
                fail(f"{x.id} has exited but is still in the area")
        # berths: one ship per berth, and only ships in the area
        for b, sid in self.berth_ship.items():
            if sid not in active:
                fail(f"berth {b} is held by {sid}, which is not in the area")
        for x in self.ships:
            b = x.berth
            if b and b.get("kind") == "berth" and b.get("id") and x.state in (State.AT_BERTH, State.MOORING):
                for i in b.get("across") or [b["id"]]:
                    if self.berth_ship.get(i) != x.id:
                        fail(f"{x.id} lies at berth {i}, booked for {self.berth_ship.get(i)}")
        # terminals: moored ships do not overlap, lie on the quay, and the cranes add up
        for T in self.terminals.values():
            spans = sorted((m.s0, m.s1, m.ship_id) for m in T.ships if m.arrived)   # a booked quay may still be taken
            for (a0, a1, a), (b0, b1, b) in zip(spans, spans[1:]):
                if b0 < a1 - 1e-6:
                    fail(f"{T.name}: {a} ({a0:.0f}-{a1:.0f} m) and {b} ({b0:.0f}-{b1:.0f} m) overlap on the quay")
            for m in T.ships:
                if m.ship_id not in active:
                    fail(f"{T.name}: {m.ship_id} is moored but not in the area")
                if m.s0 < -1e-6 or m.s1 > T.quay_length_m + 1e-6:
                    fail(f"{T.name}: {m.ship_id} lies off the quay")
                if m.cranes > T.max_cranes(m.loa):
                    fail(f"{T.name}: {m.ship_id} has {m.cranes} cranes, more than fit on it")
            if sum(m.cranes for m in T.ships) > T.sts:
                fail(f"{T.name}: {sum(m.cranes for m in T.ships)} cranes at work, {T.sts} exist")
        # locks: the ships in a chamber lie inside it and apart
        for _, lock in self.locks.values():
            for c in lock.chambers:
                for q in c.ships:
                    if q.ship.ship_id not in active:
                        fail(f"{c.name}: {q.ship.ship_id} is in the chamber but not in the area")
                    if (q.x < -1e-6 or q.y < -1e-6 or q.x + q.ship.loa > c.length_m + 1e-6
                            or q.y + q.ship.beam > c.width_m + 1e-6):
                        fail(f"{c.name}: {q.ship.ship_id} does not lie inside the chamber")
                for i, q in enumerate(c.ships):
                    for r in c.ships[i + 1:]:
                        if (q.x < r.x + r.ship.loa and r.x < q.x + q.ship.loa
                                and q.y < r.y + r.ship.beam and r.y < q.y + q.ship.beam):
                            fail(f"{c.name}: {q.ship.ship_id} and {r.ship.ship_id} overlap in the chamber")
        # pilots: on board ships in the area only; anchorages hold ships in the area only
        for pl in self.pilots.pilots:
            if pl.ship is not None and pl.ship not in active:
                fail(f"pilot {pl.id} is on board {pl.ship}, which is not in the area")
        for name, a in self.anchorages.items():
            for x in a.ships:
                if x.ship_id not in active:
                    fail(f"anchorage {name} holds {x.ship_id}, which is not in the area")
        lying = {x.ship_id for a in self.anchorages.values() for x in a.ships}
        adrift = [x.id for x in self.ships if x.state == State.ANCHORED and x.anchorage and x.id not in lying]
        if adrift:
            fail(f"anchored but in no anchorage: {adrift[:3]}")
        # time: no ship has a negative time in a state
        for x in self.ships:
            if any(v < -1e-6 for v in x.durations.values()):
                fail(f"{x.id} has a negative time in a state")

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
        self.port_log.record(now)
        # positions for the viewer, every step: a ship under way as (route, distance of its bow along it,
        # sideways offset from the route's centre line, + = to starboard), so it can be drawn along the water
        # it sails; a ship lying still as its node, only when it changes
        for s in self.ships:
            if s.state in MOVING and s.cells and s.route and s.s is not None:
                self._last_pos[s.id] = None
                self.positions.append((self.k, s.id, s.state.value, self._route_id(s), round(float(min(s.head, s.s[-1])), 1),
                                       round(float(s.lateral_m), 1)))
                continue
            node = self._display_node(s)
            if node is None:
                continue
            state = s.state.value
            if s.state == State.LOCK_QUEUE and now < getattr(s.lock_request, "ready_at", 0.0) < math.inf:
                state = "lock_sail_in"                 # called to its chamber and sailing in from the waiting place
            key = (int(node), state)
            if self._last_pos.get(s.id) != key:
                self._last_pos[s.id] = key
                self.positions.append((self.k, s.id, state, -1, int(node), 0.0))

    def _display_node(self, s):
        """The node a ship off the mesh is drawn at. Every ship gets a record when its state changes, so the
        viewer never keeps showing a ship that left the water as sailing at its last position (ships in a
        lock queue or lock used to be drawn there, piled on each other in the lock approach)."""
        if s.cells:
            return s.cells[-1]
        if s.state == State.ANCHORED and s.anchorage:
            for a in self.anchorages[s.anchorage].ships:   # its own spot in the anchorage, not the anchorage node
                if a.ship_id == s.id:
                    return a.cell
        if s.state == State.IN_LOCK and s.lock in self.locks:
            return self.locks[s.lock][0]
        if s.state == State.LOCK_QUEUE:
            # called and sailing in: at whichever end of the way in it is nearer to (the waiting place, then the
            # gate). Put at the gate from the call, its whole way in from the waiting place (1,200 m, outside the
            # kilometre the lock times are read over) was counted as time at the lock: 3 min too many at every lock
            r = getattr(s, "lock_request", None)
            if r is not None and r.ready_at < math.inf and self.t >= (getattr(s, "called_at", r.ready_at) + r.ready_at) / 2:
                return getattr(s, "queue_gate", None)
            return getattr(s, "queue_node", None)
        if s.at is None and s.state in MOVING and s.route:  # waiting for room to start (not on the mesh yet)
            return s.route[0]
        return s.at

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
                         "draught": s.arrival_draught if s.arrival_draught is not None else s.draught,
                         "departure_draught": s.draught, "teu": s.teu, "source": s.source, "destination": s.destination,
                         "terminal": s.terminal, "exit": s.exit, "spawn_min": s.spawn_t,
                         "finished": s.state == State.EXITED, "end_min": s.times.get("exited"),
                         "scheduled_berth_min": s.schedule.get("arrival_min"), "planned_berth_min": s.schedule.get("berth_min"),
                         "slowed_at_sea_min": getattr(s, "slowed_min", 0.0), "moored_min": s.times.get("at_berth"),
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
        # release valves: how often a rule was given up to keep the model moving, in all and per 1,000 ships
        fired = pd.Series([e["event"] for s in self.done + self.ships for e in s.log if e["event"] in RELEASE_VALVES]
                          + [e["event"] for e in self.events if e.get("event") in RELEASE_VALVES], dtype=object).value_counts()
        valves = {v: int(fired.get(v, 0)) for v in RELEASE_VALVES}
        valves["total"] = int(sum(valves.values()))
        valves["per_1000_ships"] = round(1000.0 * valves["total"] / max(len(ships), 1), 1)
        out["release_valves"] = valves
        # ... and what else keeps it going (SILENT), after the warm-up; why ships were removed; where ships squeezed past
        notes = [e for s in self.done + self.ships for e in s.log if e["t"] >= self.warmup_min]
        n = pd.Series([e["event"] for e in notes if e["event"] in SILENT], dtype=object).value_counts()
        out["silent"] = {k: int(n.get(k, 0)) for k in SILENT}
        out["removed_why"] = pd.Series([str(e.get("why"))[:40] for e in notes if e["event"] == "infeasible"],
                                       dtype=object).value_counts().to_dict()
        where = []
        for e in notes:
            if e["event"] == "squeeze_past" and e.get("node") is not None:
                m = float(self.fg.chainage_m[e["node"]])
                km = 5 * int(m // 5000) if m == m else None
                where.append("docks" if self._behind_locks(e["node"]) else "off the river axis" if km is None
                             else f"km {km}-{km + 5}")
        out["squeeze_where"] = pd.Series(where, dtype=object).value_counts().to_dict()
        # lock passages a day after the warm-up, inland craft and sea-going ships (to set against the AIS counts,
        # port_infrastructure.LOCK_PASSAGES, and Rijkswaterstaat's)
        days = max(self.t - self.warmup_min, DT_MIN) / 1440.0
        passed = {}
        for s in self.done + self.ships:
            kind = "inland" if s.cls.startswith("inland") else "sea_going"
            for e in s.log:
                if e["event"] == "in_lock" and e["t"] >= self.warmup_min:
                    passed[f"{e['lock']}.{kind}"] = passed.get(f"{e['lock']}.{kind}", 0) + 1
        out["locks"] = {k: round(v / days, 1) for k, v in sorted(passed.items())}
        # container ships against their berth time (the schedule and its delay)
        c = done[(done["class"] == "container") & done.moored_min.notna() & done.planned_berth_min.notna()]
        if len(c):
            late = (c.moored_min - c.planned_berth_min) / 60.0
            out["containers"] = {"n": len(c), "berth_delay_h_mean": round(float(late.mean()), 2),
                                 "berth_delay_h_median": round(float(late.median()), 2),
                                 "early_over_1h_share": round(float((late < -1).mean()), 3),
                                 "late_over_2h_share": round(float((late > 2).mean()), 3),
                                 "late_over_12h_share": round(float((late > 12).mean()), 3),
                                 "slowed_at_sea_h_mean": round(float(c.slowed_at_sea_min.fillna(0).mean() / 60), 2)}
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
        # route = -1: the ship lies at node `value`; else it is `value` m along routes[route] (route.json),
        # `offset` m to starboard of the route's centre line (passing or overtaking in one lane, movement.py)
        self.positions.frame().to_csv(out / "positions.csv.gz", index=False)
        (out / "routes.json").write_text(json.dumps(self.routes_rec, separators=(",", ":")))
        # where the nodes of this run's routes lie: the viewer of a run must not take them from a graph built later
        # (a rebuilt mesh numbers its cells anew, and a viewer made again then drew the ships all over the map)
        z = np.load(GRAPH.with_suffix(".arrays.npz"), allow_pickle=False)
        np.savez_compressed(out / "nodes.npz", latitude=z["latitude"], longitude=z["longitude"])
        self.port_log.save(out / "port_state.json.gz")
        summary = self.summary(ships)
        (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
        return summary


def main():
    """Every run goes through the pipeline: a numbered folder in results/runs/ with its viewer."""
    import pipeline
    pipeline.main()


if __name__ == "__main__":
    main()
