"""Strategy 1, local look-ahead control ("VTS 1, done well"): docs/strategies/port_management_strategies.md §4.

Every resource decides on its own, from what it sees now and in the next hour; no plan, no reservation beyond the
engine's own. The components, each with an option to switch it off (all off: the baseline):

    balance     routing: a ship is sent through the twin lock or lock complex with the shorter expected wait
                (lock_route: the avoid_locks hook when its locks are first drawn, set_avoid_locks for later voyages)
    sea_wait    routing: an arrival that is not cleared waits off the station when its expected wait is short,
                rather than going to anchor
    index       resources: within the baseline's classes, container ships late for their berth window go first
    reserve     resources: a few river pilots and pilot boats are kept for tide-dependent ships whose high water is near
    lookahead   locks: an idle chamber waits for a ship really coming when that is cheaper than making it wait a cycle
    chamber     locks: an inland craft queues at the chamber it can enter earliest (sea-going ships: the engine)
    jit         speed: a ship heading for a long lock queue slows down to arrive when it can go in

Options (with their defaults): the switches above (True), horizon_min 30, hysteresis_min 15, complex_hysteresis_min 45,
sea_wait_max_min 120, reserve_pilots 2, reserve_boats 1, reserve_window_min 90, sea_weight 3.0, jit_sea_going False
(sea-going ships under pilotage have pilots and tugs booked for when they come out of the lock; slowing them is left
off unless asked).
"""

from __future__ import annotations

from strategies import _common as C
from strategies.baseline import Baseline

SWITCHES = ("balance", "sea_wait", "index", "reserve", "lookahead", "chamber", "jit")


class LocalLookahead(Baseline):
    name = "local_lookahead"
    description = "S1: each resource on its own with a short look-ahead (lock balancing, look-ahead lockages, JIT speeds)"
    levers = ("clearance", "anchorage", "speed", "lock_route", "lock_chamber", "lockage")

    def start(self):
        o = self.options
        self.on = {k: bool(o.get(k, True)) for k in SWITCHES}
        self.horizon = float(o.get("horizon_min", 30.0))
        self.hyst = float(o.get("hysteresis_min", 15.0))
        self.hyst_complex = float(o.get("complex_hysteresis_min", 45.0))
        self.sea_wait_max = float(o.get("sea_wait_max_min", 120.0))
        self.reserve_pilots = int(o.get("reserve_pilots", 2))
        self.reserve_boats = int(o.get("reserve_boats", 1))
        self.reserve_window = float(o.get("reserve_window_min", 90.0))
        self.sea_weight = float(o.get("sea_weight", 3.0))
        self.jit_sea_going = bool(o.get("jit_sea_going", False))
        self.slowed = {}                       # ship id -> lock it was slowed for
        self._step_cache = (None, None, None)  # (minute, LockModel, coming)

    # ------------------------------------------------------------------ shared per-step snapshots
    def snapshot(self):
        now = self.view.now
        if self._step_cache[0] != now:
            model = C.LockModel(self.view)
            self._step_cache = (now, model, C.coming(self.view, max(self.horizon, 180.0)))
        return self._step_cache[1], self._step_cache[2]

    def weight(self, ship):
        return self.sea_weight if ship.sea_going else 1.0

    # ------------------------------------------------------------------ routing: twin locks and complexes
    def best_avoid(self, ship, own):
        """A better avoid-set for this ship than its own, or None."""
        model, _ = self.snapshot()
        best, gain_best = None, 0.0
        for avoid, to in C.lock_alternatives(ship):
            frm = [l for l in own if l not in avoid]          # locks it would leave
            if not frm:
                continue
            gain = min(model.load(l) for l in frm) - min(model.load(l) for l in to)
            need = self.hyst_complex if len(to) + len(frm) > 2 or to[0] in ("Kallo", "Kieldrecht") else self.hyst
            if gain > need and gain > gain_best:
                best, gain_best = avoid, gain
        return best

    def avoid_locks(self, ship, default):
        if not self.on["balance"]:
            return None
        proxy = _WithAvoid(ship, default)
        best = self.best_avoid(proxy, default)
        return best

    def rebalance(self, ship):
        if not self.on["balance"] or ship.avoid_locks is None:
            return
        best = self.best_avoid(ship, tuple(ship.avoid_locks))
        if best is not None:
            self.control.set_avoid_locks(ship, best)

    # ------------------------------------------------------------------ clearance
    def on_request(self, ship):
        if ship.needs_pilot:
            return
        self.rebalance(ship)
        super().on_request(ship)

    def order(self, ship):
        base = self.view.default_priority(ship)
        late = 0.0
        if self.on["index"] and ship.cls == "container" and ship.scheduled_berth_min is not None and not ship.departing:
            late = max(self.view.now - ship.scheduled_berth_min, 0.0)
        return (base[0], -late, base[1])

    def tide_ship_due(self, waiting):
        """Is a waiting tide-dependent ship near its high water (so resources are kept for it)?"""
        if not self.on["reserve"]:
            return False
        now = self.view.now
        if not any(s.tide_dependent and s.ready for s in waiting):
            return False
        return any(0.0 <= hw - now <= self.reserve_window for hw in self.view.high_waters())

    def short_of(self):
        v = self.view
        return v.pilots_free("river") <= self.reserve_pilots or v.pilot_boats_free() <= self.reserve_boats

    def on_tick(self, now):
        view, control = self.view, self.control
        waiting = [s for s in view.requests() if s.needs_pilot]
        keep = self.tide_ship_due(waiting)
        for ship in sorted(waiting, key=self.order):
            if not ship.ready:
                continue
            if keep and not ship.tide_dependent and not ship.distress and self.short_of():
                continue                           # kept for the tide-dependent ship this round
            self.rebalance(ship)
            result = control.clear(ship)
            if result.ok or result.removed or result.reason == "pilot_lost":
                continue
            self.not_cleared(ship, result)
        if self.on["jit"]:
            self.pace()

    def expected_wait(self, ship, result):
        """Minutes an uncleared arrival can expect to wait, by the check it failed (None: unknown or long)."""
        view = self.view
        if result.reason == "pilot":
            return 30.0
        if result.reason == "destination" and ship.terminal:
            for k in range(1, 9):
                at = view.now + 30.0 * k
                if any(b - a >= ship.loa for a, b in view.terminal_free(ship.terminal, at)):
                    return 30.0 * k
            return None
        if result.reason == "tide" and result.route:
            for k in range(1, 9):
                if view.tide_ok(ship, result.route, view.now + 30.0 * k):
                    return 30.0 * k
            return None
        return None

    def not_cleared(self, ship, result):
        if self.on["sea_wait"] and not ship.departing and ship.state == "wait_clearance" and ship.at_station:
            w = self.expected_wait(ship, result)
            if w is not None and w <= self.sea_wait_max:
                if self.control.wait_at_sea(ship, self.sea_wait_max).ok:
                    return
        super().not_cleared(ship, result)

    # ------------------------------------------------------------------ speed: just in time to the lock
    def jit_ok(self, ship):
        """May the just-in-time speeds pace this ship? Inland craft always; sea-going ships when asked."""
        return not ship.sea_going or self.jit_sea_going

    def jit_margin(self, ship):
        """Minutes before it can go in that a paced ship is to reach the lock."""
        return 10.0

    def lock_entry(self, model, lock, side, ship, ahead, ahead_sea):
        """Minutes until the ship can go into the lock: every ship queued or coming before it counts (ahead: ships
        coming before it, ahead_sea: the sea-going ones among them)."""
        return model.entry_min(lock, side, ship.loa, ship.beam, ahead=ahead)

    def pace(self):
        model, com = self.snapshot()
        for sid, lock in list(self.slowed.items()):
            s = self.view.ship(sid)
            if s is None:
                del self.slowed[sid]
            elif s.state != "sailing" or s.next_lock != lock:
                self.control.clear_speed(s)
                del self.slowed[sid]
        for (lock, side), ships in com.items():
            ahead = ahead_sea = 0
            for t, s in ships:
                entry = self.lock_entry(model, lock, side, s, ahead, ahead_sea)
                ahead += 1
                ahead_sea += 1 if s.sea_going else 0
                if entry is None or not self.jit_ok(s):
                    continue
                kn = C.jit_speed(s, entry - t, margin_min=self.jit_margin(s))
                if kn is not None and self.control.set_speed(s, kn).ok:
                    self.slowed[s.id] = lock

    # ------------------------------------------------------------------ locks
    def choose_chamber(self, ship, lock, options, default):
        # inland craft only: a sea-going ship goes before the craft queued at its side (lock priority 3 against 4),
        # which the estimate does not see, so it would think the ship's wait longer than it is; the engine's lock
        # planner also moves a sea-going ship to a chamber open at its side (MODEL.md §14). Phase 0 (run 0048): a
        # tanker moved this way at Terneuzen waited 0.88 h against 0.23 h
        if not self.on["chamber"] or len(options) < 2 or ship.sea_going:
            return None
        model, _ = self.snapshot()
        side = ship.next_lock_side
        if side is None:
            return None
        t = {c: model.entry_min(lock, side, ship.loa, ship.beam, chamber=c) for c in options}
        t = {c: v for c, v in t.items() if v is not None}
        if not t:
            return None
        best = min(t, key=t.get)
        return best if t[best] + 5.0 < t.get(default, float("inf")) else None

    def keep_lock_open(self, lock, chamber, default):
        if not self.on["lookahead"] or default:
            return None
        model, com = self.snapshot()
        c = model.chambers(lock).get(chamber)
        if c is None or c["state"] != "open":
            return None
        inside = [self.view.ship(i) for i in c["inside"]]
        if any(s is not None and (s.tide_dependent or s.ulcv) for s in inside):
            return None
        side, tc = c["side"], C.cycle_min(lock)
        u_in = sum(self.weight(s) for s in inside if s is not None)
        u_in += sum(self.weight(s) for s in (self.view.ship(i) for i in c["waiting_" + C.other_side(side)]) if s is not None)
        for eta, s in com.get((lock, side), ()):
            if eta > self.horizon:
                break
            if not model.room_left(lock, chamber, s.loa, s.beam):
                continue
            if self.weight(s) * tc > max(u_in, 0.5) * eta:
                return True
        return None


class _WithAvoid:
    """A ShipView whose avoid-set is the one about to be drawn (for the avoid_locks hook)."""

    def __init__(self, ship, avoid):
        self._ship, self._avoid = ship, tuple(avoid)

    def __getattr__(self, name):
        return getattr(self._ship, name)

    @property
    def avoid_locks(self):
        return self._avoid
