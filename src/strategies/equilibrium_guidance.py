"""Strategy 3, equilibrium guidance ("PULSE at the port level"): docs/strategies/port_management_strategies.md §6.

Every planning round the VTS builds a guidance game among the ships whose next decisions interact, finds an approximate
pure Nash equilibrium with PULSE's random-edge replicator dynamics (Grgičević & Coates 2026) and gives each ship its
part of it as orders. Such advice is self-enforcing: no ship lowers its own cost by deviating alone.

Players and their strategies (m <= 9, as in PULSE):

    waiting pilot ships that would pass the checks now:   start {now, in 15 min, in 45 min} x speed {1.0, 0.85, 0.7}
    inland craft sailing to a lock within 2 h:            speed {1.0, 0.85, 0.7} (sea-going ships too with jit_sea_going)

A ship's own cost (kg of fuel-equivalent): its value of time x the minutes until it reaches its lock (or destination),
plus the fuel of sailing at that speed and of waiting (the emissions module's formulas, strategies/_common.FuelModel).
The costs ships put on each other, pairwise:

    same lock side, arriving within half a cycle of each other: the later one waits its share of a return trip
    two ships starting now that need the same pilot zone when it has fewer pilots free than they need: the later one
    (by precedence) waits for a pilot to come back; the same for pilot boats

The VTS's lever is lam: each ship also counts lam times the cost it puts on the others (a non-monetary toll). lam 0 is
the selfish equilibrium, lam 1 approaches the round's social optimum. Each round the strategy writes an event
"eq_round" with the players, edges, the regret of the applied profile and the price of anarchy SC(lam 0) / SC(lam 1).

Locks and routing between rounds are as in strategy 1 (look-ahead lockages, earliest-entry chamber, lock balancing,
waiting off the station), so strategies 1 and 3 use the same levers.

Options: those of local_lookahead, plus lam 0.5, iters 1000, starts [0, 15, 45], speeds [1.0, 0.85, 0.7],
mover_horizon_min 120, max_movers_per_lock 12, measure_poa True.
"""

from __future__ import annotations

import numpy as np

from strategies import _common as C
from strategies import _games as G
from strategies.local_lookahead import LocalLookahead
from vts_api import Result

PILOT_WAIT_MIN = 45.0
BOAT_WAIT_MIN = 30.0


class GameModel:
    """The players of one round and their costs, built from the view. Times are minutes from now.

    records: one per pair of players that can meet, (j, k, A_j_first, B_j_first, A_k_first, B_k_first), with A the
    (m_j, m_k) cost to j and B the (m_k, m_j) cost to k, in the two orders of precedence (equal for lock pairs, where
    arrival times decide). Padded arrays (padded_*) let a whole profile be scored in a few numpy operations."""

    def __init__(self, strategy, players):
        self.s = strategy
        self.players = players                 # dicts: ship, kind, strats, and the times each needs
        self.n = len(players)
        self.m = [len(p["strats"]) for p in players]

    # -------------------------------------------------------------- per player
    def lock_arrival(self, p, a, eps=1.0):
        start, f = p["strats"][a]
        if p["t_lock"] is None:
            return None
        return start + eps * p["t_lock"] / f

    def internal(self, eps=None, tc_scale=1.0):
        out = []
        for j, p in enumerate(self.players):
            e = 1.0 if eps is None else eps[j]
            vot, ship = p["vot"], p["ship"]
            costs = np.empty(self.m[j])
            for a, (start, f) in enumerate(p["strats"]):
                kn = p["kn"] * f
                sail = e * p["t_sail"] / f                     # minutes under way to the lock or the destination
                arrive = start + e * (p["t_lock"] if p["t_lock"] is not None else p["t_sail"]) / f
                wait = 0.0
                if p["entry"] is not None:
                    wait = max(p["entry"] * tc_scale - arrive, 0.0)
                time = start + sail + wait
                fuel = p["fuel_sail"](kn) * sail + p["fuel_wait"] * (start + wait)
                costs[a] = vot * time + fuel
            out.append(costs)
        return out

    # -------------------------------------------------------------- pairs
    def records(self, eps=None, tc_scale=1.0):
        out = []
        P = self.players
        by_lock = {}
        for j, p in enumerate(P):
            if p["lock_key"] is not None:
                by_lock.setdefault(p["lock_key"], []).append(j)
        for key, js in by_lock.items():
            lock = key[0]
            half = C.cycle_min(lock) * tc_scale / 2.0
            arr = {j: np.array([self.lock_arrival(P[j], a, 1.0 if eps is None else eps[j]) for a in range(self.m[j])])
                   for j in js}
            for x, j in enumerate(js):
                for k in js[x + 1:]:
                    tj, tk = arr[j][:, None], arr[k][None, :]
                    if np.min(np.abs(tj - tk)) > half:
                        continue
                    close = np.abs(tj - tk) <= half
                    share_j = 2.0 * C.cycle_min(lock) * tc_scale / P[j]["cap"]
                    share_k = 2.0 * C.cycle_min(lock) * tc_scale / P[k]["cap"]
                    a_jk = np.where(close & (tj > tk), P[j]["vot"] * share_j, 0.0)
                    b_kj = np.where(close & (tk >= tj), P[k]["vot"] * share_k, 0.0).T
                    out.append((j, k, a_jk, b_kj, a_jk, b_kj))
        view = self.s.view
        starters = [j for j, p in enumerate(P) if p["kind"] == "wait"]
        for x, j in enumerate(starters):
            for k in starters[x + 1:]:
                pj, pk = P[j], P[k]
                same = np.array([[sj == sk for sk, _ in pk["strats"]] for sj, _ in pj["strats"]], dtype=float)
                cost_j = np.zeros((self.m[j], self.m[k]))
                cost_k = np.zeros((self.m[j], self.m[k]))
                if pj["zone"] and pj["zone"] == pk["zone"] and view.pilots_free(pj["zone"]) < pj["pilots"] + pk["pilots"]:
                    cost_j += same * pj["vot"] * PILOT_WAIT_MIN
                    cost_k += same * pk["vot"] * PILOT_WAIT_MIN
                if pj["boat"] and pk["boat"] and view.pilot_boats_free() < 2:
                    cost_j += same * pj["vot"] * BOAT_WAIT_MIN
                    cost_k += same * pk["vot"] * BOAT_WAIT_MIN
                if not cost_j.any():
                    continue
                zero_j, zero_k = np.zeros_like(cost_j), np.zeros_like(cost_k).T
                # j first: k pays; k first: j pays
                out.append((j, k, zero_j, cost_k.T, cost_j, zero_k))
        return out

    @staticmethod
    def pairs(records, rank):
        """The cost matrices of one order of precedence (rank[j] < rank[k]: j goes first)."""
        out = {}
        for j, k, a1, b1, a2, b2 in records:
            a, b = (a1, b1) if rank[j] < rank[k] else (a2, b2)
            if a.any():
                out[(j, k)] = out.get((j, k), 0.0) + a
            if b.any():
                out[(k, j)] = out.get((k, j), 0.0) + b
        return out

    # -------------------------------------------------------------- fast scoring (strategy 4)
    def padded(self, internal, records):
        n, mm = self.n, max(self.m) if self.m else 1
        big = 1e12
        I = np.full((n, mm), big)
        for j, c in enumerate(internal):
            I[j, :len(c)] = c
        E = len(records)
        J = np.array([r[0] for r in records], dtype=int)
        K = np.array([r[1] for r in records], dtype=int)
        mats = []
        for idx in range(2, 6):
            arr = np.zeros((E, mm, mm))
            for e, r in enumerate(records):
                m = r[idx]
                arr[e, :m.shape[0], :m.shape[1]] = m
            mats.append(arr)
        return {"I": I, "J": J, "K": K, "A1": mats[0], "B1": mats[1], "A2": mats[2], "B2": mats[3]}

    @staticmethod
    def score(pad, genes, rank):
        g = np.asarray(genes, dtype=int)
        r = np.asarray(rank)
        sc = pad["I"][np.arange(len(g)), g].sum()
        if len(pad["J"]):
            J, K = pad["J"], pad["K"]
            e = np.arange(len(J))
            gj, gk = g[J], g[K]
            first = r[J] < r[K]
            sc += np.where(first, pad["A1"][e, gj, gk] + pad["B1"][e, gk, gj],
                           pad["A2"][e, gj, gk] + pad["B2"][e, gk, gj]).sum()
        return float(sc)


class EquilibriumGuidance(LocalLookahead):
    name = "equilibrium_guidance"
    description = "S3: each round, an approximate Nash equilibrium of the ships' guidance game (PULSE), given as orders"
    levers = ("clearance", "anchorage", "speed", "lock_route", "lock_chamber", "lockage")

    def start(self):
        super().start()
        o = self.options
        self.lam = float(o.get("lam", 0.5))
        self.iters = int(o.get("iters", 1000))
        self.starts = [float(x) for x in o.get("starts", [0, 15, 45])]
        self.speeds = [float(x) for x in o.get("speeds", [1.0, 0.85, 0.7])]
        self.mover_horizon = float(o.get("mover_horizon_min", 120.0))
        self.max_movers = int(o.get("max_movers_per_lock", 12))
        self.measure_poa = bool(o.get("measure_poa", True))
        self.fuel = C.FuelModel()
        self.ordered = {}                      # ship id -> kn this strategy ordered

    # ------------------------------------------------------------------ the players
    @staticmethod
    def speed_order(ship, kn):
        """A speed the engine accepts: from 3 kn (vts_api.MIN_SPEED_KN) to the ship's own top speed (its planning speed
        times its own spread can be below the planning speed, and an order above its top is refused)."""
        top = max(ship.max_speed_kn("sea"), ship.max_speed_kn("river"))
        return min(max(kn, 3.0), top)

    def floor_kn(self, ship):
        return max(0.6 * ship.planning_speed_kn("river"), 4.0, 3.0)

    def players(self, model):
        view, control = self.view, self.control
        out, blocked = [], []
        waiting = [s for s in view.requests() if s.needs_pilot and s.ready]
        for ship in sorted(waiting, key=self.order):
            self.rebalance(ship)
            check = control.check(ship)
            if check.removed:
                continue
            if not check.ok:
                blocked.append((ship, check))
                continue
            route = check.route
            tm = view.travel_minutes(ship, route)
            locks = view.route_locks(route)
            zones = view.pilot_zones(route)
            zone = zones[0][0] if zones else None
            lock_key, t_lock, entry, cap = None, None, None, 1
            if locks:
                name, i = locks[0]
                t_lock = tm[i]
                entry = min((model.entry_min(name, s, ship.loa, ship.beam) or 0.0) for s in ("a", "b"))
                lock_key = (name, None)
                cap = max((C.capacity(c, ship.loa, ship.beam) for c in model.chambers(name).values()
                           if C.fits(c, ship.loa, ship.beam)), default=1) or 1
            out.append(self._player(ship, "wait", [(st, f) for st in self.starts for f in self.speeds],
                                    t_sail=tm[-1] if tm else 0.0, t_lock=t_lock, entry=entry, lock_key=lock_key,
                                    cap=cap, zone=zone, pilots=ship.pilots_needed(zone) if zone else 0,
                                    boat=bool(ship.at_station and not ship.departing)))
        _, com = self.snapshot()
        for (lock, side), ships in com.items():
            ahead = 0
            for t, ship in ships[:self.max_movers]:
                if t > self.mover_horizon:
                    break
                entry = model.entry_min(lock, side, ship.loa, ship.beam, ahead=ahead)
                ahead += 1
                if entry is None or (ship.sea_going and not self.jit_sea_going):
                    continue
                kn = ship.planning_speed_kn("river")       # strategies are shares of it: 1.0 lifts an order
                t = C.eta_min(ship, kn)
                speeds = sorted({min(max(f * kn, self.floor_kn(ship)), kn) / kn for f in self.speeds}, reverse=True)
                cap = max((C.capacity(c, ship.loa, ship.beam) for c in model.chambers(lock).values()
                           if C.fits(c, ship.loa, ship.beam)), default=1) or 1
                out.append(self._player(ship, "move", [(0.0, f) for f in speeds], t_sail=t, t_lock=t, entry=entry,
                                        lock_key=(lock, side), cap=cap, zone=None, pilots=0, boat=False, kn=kn))
        return out, blocked

    def _player(self, ship, kind, strats, t_sail, t_lock, entry, lock_key, cap, zone, pilots, boat, kn=None):
        kn = kn or ship.planning_speed_kn("river")
        return {"ship": ship, "kind": kind, "strats": strats, "t_sail": t_sail, "t_lock": t_lock, "entry": entry,
                "lock_key": lock_key, "cap": cap, "zone": zone, "pilots": pilots, "boat": boat, "kn": kn,
                "vot": C.vot(ship), "fuel_sail": (lambda v, s=ship: self.fuel.sail(s, v)),
                "fuel_wait": self.fuel.wait(ship)}

    # ------------------------------------------------------------------ solving (strategy 4 overrides)
    def solve(self, game):
        """Returns (profile, order of precedence, info)."""
        rank = list(range(game.n))
        internal = game.internal()
        recs = game.records()
        pairs = game.pairs(recs, rank)
        profile, info = G.pulse_solve(internal, G.internalise(pairs, self.lam), self.view.rng, iters=self.iters)
        info["sc"] = G.social_cost(profile, internal, pairs)
        # regret under the ships' own (selfish) costs: how much one ship would gain by ignoring the advice
        info["regret_selfish"] = self.selfish_regret(profile, internal, pairs)
        if self.measure_poa and game.n:
            p0, _ = G.pulse_solve(internal, pairs, self.view.rng, iters=self.iters)
            p1, _ = G.pulse_solve(internal, G.internalise(pairs, 1.0), self.view.rng, iters=self.iters)
            sc0, sc1 = G.social_cost(p0, internal, pairs), G.social_cost(p1, internal, pairs)
            info["poa"] = sc0 / sc1 if sc1 > 0 else 1.0
        return profile, rank, info

    @staticmethod
    def selfish_regret(profile, internal, pairs):
        nb = G.neighbours(len(internal), pairs)
        worst = 0.0
        for j in range(len(internal)):
            costs = [G.player_cost(j, a, profile, internal, nb) for a in range(len(internal[j]))]
            worst = max(worst, costs[profile[j]] - min(costs))
        return float(worst)

    # ------------------------------------------------------------------ the round
    def on_tick(self, now):
        model, _ = self.snapshot()
        players, blocked = self.players(model)
        for ship, check in blocked:
            self.not_cleared(ship, check)
        game = GameModel(self, players)
        if game.n == 0:
            return
        profile, rank, info = self.solve(game)
        self.apply(game, profile, rank)
        self.control.note(None, "eq_round", strategy=self.name, players=game.n,
                          **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in info.items()
                             if k in ("edges", "regret", "regret_selfish", "settled", "poa", "sc", "sc_seed", "generations")})

    def apply(self, game, profile, rank):
        control = self.control
        order = sorted(range(game.n), key=lambda j: rank[j])
        for j in order:
            p = game.players[j]
            ship = p["ship"]
            start, f = p["strats"][profile[j]]
            if p["kind"] == "wait":
                if start > 0:
                    if not ship.departing and ship.state == "wait_clearance" and ship.at_station:
                        if not control.wait_at_sea(ship, self.sea_wait_max).ok:
                            control.send_to_anchorage(ship)
                    continue
                result = control.clear(ship)
                if result.ok:
                    if f < 1.0:
                        kn = self.speed_order(ship, max(f * ship.planning_speed_kn("river"), self.floor_kn(ship)))
                        if control.set_speed(ship, kn).ok:
                            self.ordered[ship.id] = kn
                elif not (result.removed or result.reason == "pilot_lost"):
                    self.not_cleared(ship, result)
            else:
                kn = self.speed_order(ship, p["kn"] * f)
                if f < 0.999:
                    if control.set_speed(ship, kn).ok:
                        self.ordered[ship.id] = kn
                        self.slowed[ship.id] = ship.next_lock
                elif ship.id in self.ordered:
                    control.clear_speed(ship)
                    self.ordered.pop(ship.id, None)
                    self.slowed.pop(ship.id, None)
        # lift speed orders of craft that have reached their lock
        for sid, lock in list(self.slowed.items()):
            s = self.view.ship(sid)
            if s is None or s.state != "sailing" or s.next_lock != lock:
                if s is not None:
                    control.clear_speed(s)
                self.slowed.pop(sid, None)
                self.ordered.pop(sid, None)
