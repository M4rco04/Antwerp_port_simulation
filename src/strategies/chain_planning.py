"""Strategy 2, chain planning: docs/strategies/port_management_strategies.md §5 (version 2, after runs 201-204).

A sea-going call is a chain of links: the ship before it leaves the quay, this ship is cleared and sails in, it
passes the locks with its pilots, it berths. The strategy keeps the links in step with the plan the port already
has (the quay bookings and planned departures, the lockages coming up) and uses that plan to time ships, never to
hold back a ship whose resources are free:

    order      every round, after ships in distress and tide-dependent ships: container ships late for their berth
               time first, then by request time; on request (departures_first) departures before arrivals
    clearance  a ship is cleared as soon as the engine's checks pass (route, weather, tide, pilots, destination)
    locks      strategy 1's lock rules (balancing twins and complexes, earliest-entry chambers; its look-ahead
               lockages only on request: holding a chamber open for a ship coming cost every ship in it more than
               the ship coming gained) and its just-in-time speeds to the lock entry, here for sea-going ships too
               (not for tide-dependent ships or ULCVs), which reach the lock with a larger margin
    quay       tier 3 chooses where along the quay a container ship lies (the stretch that leaves the longest free
               quay); on request (quay_jit) a container ship whose booked stretch is still taken at its ETA slows
               down to arrive as it comes free (in screening runs it cost container ships time and saved little
               once a ship waiting off a quay is counted at standby, MODEL.md §17.1)
    waiting    an arrival that is not cleared waits off the station when its wait is short, else at anchor
               (strategy 1); a departure waits at its berth

The first version cleared a ship only when its whole voyage fitted a 6-h table of time slots for pilots, pilot
boats, lockages and quay, with buffers, and fell back to strategy 1 when slots were missed. It held ships whose
resources were free: in the 60-day runs 201-204 container ships reached their quay 0.5 h later at normal traffic,
departures left 1.1-1.7 h later at 1.5 times the traffic, and the fuel did not fall. It is in the history (commit
f2fc5b2c).

Options: those of local_lookahead (here lookahead defaults to False and jit_sea_going to True), departures_first
False, quay_jit False, jit_margin_sea_min 30 and jit_margin_inland_min 10 (minutes before it can go in that a paced
ship aims to reach the lock), quay True (tier 3; False gives the tier-2 variant). Screening runs of each step:
docs/strategies/port_management_strategies.md §5.0.
"""

from __future__ import annotations

from strategies import _common as C
from strategies.local_lookahead import LocalLookahead

QUAY_GAP_M = 22.5            # kept between moored ships (terminals.MOORING_GAP_M, the mean)
CLEARING_MIN = 90.0          # a ship ready at the quay but not yet cleared: assumed gone after this (assumed)


class ChainPlanning(LocalLookahead):
    name = "chain_planning"
    description = ("S2: the call chain in step: clearance whenever the resources are free, late container ships "
                   "first, just-in-time speeds to the lock entry for sea-going ships and inland craft")
    levers = ("clearance", "anchorage", "speed", "lock_route", "lock_chamber", "lockage", "quay_position")

    def start(self):
        super().start()
        o = self.options
        # strategy 1's look-ahead lockages kept chambers open for ships coming: in screening runs at normal traffic
        # the sea-going ships gained in the queue what every ship lost in the chamber (inland craft 0.1 h a passage)
        self.on["lookahead"] = bool(o.get("lookahead", False))
        self.jit_sea_going = bool(o.get("jit_sea_going", True))
        # departures first: at 1.5 times the traffic it changed neither the time in the area nor the calls and cost
        # 5 t of fuel a day (screening runs); the departures that version 1 delayed were held by its slot gate
        self.departures_first = bool(o.get("departures_first", False))
        self.quay_jit = bool(o.get("quay_jit", False))
        self.margin_sea = float(o.get("jit_margin_sea_min", 30.0))
        self.margin_inland = float(o.get("jit_margin_inland_min", 10.0))
        self.use_quay = bool(o.get("quay", True))
        if not self.use_quay:
            self.levers = tuple(l for l in self.levers if l != "quay_position")
        self.quay_slowed = {}                  # ship id -> terminal whose quay it was slowed for

    # ------------------------------------------------------------------ the round
    def order(self, ship):
        """(priority class, departures before arrivals, lateness of a container ship, request time)."""
        base = self.view.default_priority(ship)
        if self.departures_first and ship.departing:
            return (base[0], 0, 0.0, base[1])
        late = 0.0
        if self.on["index"] and ship.cls == "container" and ship.scheduled_berth_min is not None and not ship.departing:
            late = max(self.view.now - ship.scheduled_berth_min, 0.0)
        return (base[0], 1, -late, base[1])

    def on_tick(self, now):
        super().on_tick(now)                   # strategy 1's round in this order, and its speeds to the locks
        if self.quay_jit:
            self.pace_quay()

    # ------------------------------------------------------------------ speeds
    def jit_ok(self, ship):
        if not ship.sea_going:
            return True
        return self.jit_sea_going and not ship.tide_dependent and not ship.ulcv

    def jit_margin(self, ship):
        return self.margin_sea if ship.sea_going else self.margin_inland

    def lock_entry(self, model, lock, side, ship, ahead, ahead_sea):
        """A sea-going ship goes into the lock before the inland craft queued at its side (lock priority 3 against
        4): only the sea-going ships before it hold it back. Counting the craft too (strategy 1's estimate) slowed
        sea-going ships for waits they did not have: container ships sailed 0.26 h longer in screening runs."""
        if not ship.sea_going:
            return super().lock_entry(model, lock, side, ship, ahead, ahead_sea)
        view = self.view

        def sea_going(sid):
            v = view.ship(sid)
            return v is not None and v.sea_going
        return model.entry_min(lock, side, ship.loa, ship.beam, ahead=ahead_sea, count=sea_going)

    def quay_free_at(self, ship, terminal):
        """Minute the stretch of quay booked for the ship is clear of the ships lying there now (their planned
        departures), or None when it has no booking."""
        now = self.view.now
        mine = next(((a, b) for i, a, b, arrived, _ in terminal["ships"] if i == ship.id and not arrived), None)
        if mine is None:
            return None
        free = now
        for i, a, b, arrived, leaves in terminal["ships"]:
            if i != ship.id and arrived and a - QUAY_GAP_M < mine[1] and b + QUAY_GAP_M > mine[0]:
                free = max(free, leaves if leaves is not None else now + CLEARING_MIN)
        return free

    def pace_quay(self):
        """A container ship sailing to a quay that will still be taken when it gets there slows down to arrive
        as it comes free (no lock left on its way: the lock speeds pace those)."""
        view, control = self.view, self.control
        now = view.now
        for sid in list(self.quay_slowed):
            s = view.ship(sid)
            if s is None or s.state != "sailing":
                del self.quay_slowed[sid]
        terminals = None
        for s in view.ships():
            if (s.state != "sailing" or s.departing or s.cls != "container" or not s.terminal
                    or s.tide_dependent or s.ulcv or s.next_lock is not None):
                continue
            b = s.berth
            if not b or b["kind"] != "terminal":
                continue
            if terminals is None:
                terminals = view.terminals()
            T = terminals.get(s.terminal)
            free = self.quay_free_at(s, T) if T is not None else None
            if free is None:
                continue
            wait = free - (now + C.eta_min(s))
            kn = C.jit_speed(s, wait, margin_min=self.margin_sea)
            if kn is not None:
                if control.set_speed(s, kn).ok:
                    self.quay_slowed[s.id] = s.terminal
            elif s.id in self.quay_slowed and wait <= 0:
                control.clear_speed(s)                 # its quay comes free sooner than planned
                del self.quay_slowed[s.id]

    # ------------------------------------------------------------------ quay (tier 3)
    def choose_quay_position(self, ship, terminal, options, default):
        if not self.use_quay or not options:
            return None
        best, best_key = None, None
        for a, b in options:
            for s0 in {a, b - ship.loa}:
                if s0 < a - 1e-6 or s0 + ship.loa > b + 1e-6:
                    continue
                left = max(s0 - a, b - (s0 + ship.loa))
                # the longest stretch left free in this interval; ties: the default's side
                key = (left, -abs(s0 - default))
                if best_key is None or key > best_key:
                    best, best_key = s0, key
        if best is None or abs(best - default) < 1e-6:
            return None
        return float(best)
