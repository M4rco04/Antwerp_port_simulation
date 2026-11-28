"""The port strategies (docs/strategies/port_management_strategies.md): their solvers and estimators, without a model.

What they do in a run is checked by running them; here: the game solvers find equilibria and optima where brute force
can check them, the toll lowers the social cost, and the fuel and lock estimates behave.
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for d in ("sim", "agents", "environment", "data"):
    sys.path.insert(0, str(ROOT / "src" / d))
sys.path.append(str(ROOT / "src"))

import strategies  # noqa: E402
from strategies import _common as C  # noqa: E402
from strategies import _games as G  # noqa: E402
from vts_api import LEVERS  # noqa: E402

PORT = ("local_lookahead", "chain_planning", "equilibrium_guidance", "evolutionary_guidance")


def test_the_four_port_strategies_are_found_with_known_levers():
    found = strategies.available()
    for name in PORT:
        assert name in found
        cls = found[name]
        assert set(cls.levers) <= set(LEVERS)
        s = strategies.load(name)
        assert s.name == name and s.description


def random_game(rng, n, m):
    internal = [rng.uniform(0, 10, m) for _ in range(n)]
    pairs = {}
    for j, k in itertools.combinations(range(n), 2):
        if rng.random() < 0.7:
            pairs[(j, k)] = rng.uniform(0, 10, (m, m))
            pairs[(k, j)] = rng.uniform(0, 10, (m, m))
    return internal, pairs


def pure_equilibria(internal, pairs):
    n, m = len(internal), len(internal[0])
    nb = G.neighbours(n, pairs)
    out = []
    for prof in itertools.product(range(m), repeat=n):
        if all(G.player_cost(j, prof[j], prof, internal, nb) <= min(G.player_cost(j, a, prof, internal, nb)
                                                                   for a in range(m)) + 1e-9 for j in range(n)):
            out.append(prof)
    return out


def test_pulse_finds_a_pure_equilibrium_where_one_exists():
    rng = np.random.default_rng(7)
    tried = found = 0
    for _ in range(200):
        internal, pairs = random_game(rng, int(rng.integers(2, 5)), int(rng.integers(2, 5)))
        eqs = pure_equilibria(internal, pairs)
        if not eqs:
            continue
        tried += 1
        prof, info = G.pulse_solve(internal, pairs, rng, iters=500)
        found += info["settled"] and tuple(prof) in eqs
    assert tried > 50 and found / tried >= 0.95


def test_two_ships_one_lockage():
    # two craft, strategies (full speed, slow); only one fits the next lockage, the later one waits a return trip
    # (cost 60) when both come at once. Ship 0 is in a hurry (slowing costs it 30), ship 1 not (slowing costs it 5)
    internal = [np.array([0.0, 30.0]), np.array([0.0, 5.0])]
    pairs = {(1, 0): np.array([[60.0, 0.0], [0.0, 0.0]]),     # cost to 1 of (s1, s0): both full speed -> 1 waits
             (0, 1): np.zeros((2, 2))}
    prof, info = G.pulse_solve(internal, pairs, np.random.default_rng(1), iters=500)
    assert prof == [0, 1] and info["settled"]                  # the craft in no hurry slows down


def test_the_toll_lowers_the_social_cost():
    rng = np.random.default_rng(3)
    lower = []
    for _ in range(60):
        internal, pairs = random_game(rng, 4, 3)
        p0, _ = G.pulse_solve(internal, pairs, rng)
        p1, _ = G.pulse_solve(internal, G.internalise(pairs, 1.0), rng)
        lower.append(G.social_cost(p1, internal, pairs) <= G.social_cost(p0, internal, pairs) + 1e-9)
    assert np.mean(lower) >= 0.8


def test_the_genetic_algorithm_reaches_the_optimum_of_small_games():
    rng = np.random.default_rng(11)
    hits = 0
    for _ in range(30):
        internal, pairs = random_game(rng, 5, 3)
        best = min(G.social_cost(p, internal, pairs) for p in itertools.product(range(3), repeat=5))
        genes, order, fit, hist = G.ga_solve([3] * 5, lambda g, o: G.social_cost(g, internal, pairs), rng,
                                             pop=30, gens=30)
        hits += abs(fit - best) < 1e-9
        assert all(b <= a + 1e-12 for a, b in zip(hist, hist[1:]))      # elitism: the best never gets worse
        assert sorted(order) == list(range(5))
    assert hits / 30 >= 0.9


def test_the_genetic_algorithm_never_loses_its_seed():
    rng = np.random.default_rng(5)
    internal, pairs = random_game(rng, 8, 4)
    seed = [0] * 8
    f = lambda g, o: G.social_cost(g, internal, pairs)
    _, _, fit, _ = G.ga_solve([4] * 8, f, rng, seeds=[(seed, list(range(8)))], pop=10, gens=0)
    assert fit <= f(seed, None) + 1e-9


class FakeShip:
    def __init__(self, cls="inland_cargo", loa=110.0, beam=11.4, draught=3.0, sea_going=False, teu=None, avoid=None):
        self.id = f"F-{cls}-{loa}"
        self.cls, self.loa, self.beam, self.draught, self.sea_going, self.teu, self.dg = cls, loa, beam, draught, sea_going, teu, None
        self.avoid_locks = avoid


def test_fuel_rises_with_speed_and_waiting_costs_a_sea_going_ship():
    fm = C.FuelModel()
    inland = FakeShip()
    assert 0 < fm.sail(inland, 6.0) < fm.sail(inland, 9.0)
    assert fm.wait(inland) == 0.0                               # a craft lying still burns nothing (MODEL.md §17.1)
    box = FakeShip("container", 366.0, 51.0, 14.0, True, teu=14000)
    assert fm.sail(box, 10.0) < fm.sail(box, 14.0)
    assert fm.wait(box) > 0.0                                   # auxiliaries and boiler at anchor
    # per mile, slower is cheaper for the container ship (the cube of the speed against the hours at sea)
    assert fm.sail(box, 10.0) / 10.0 < fm.sail(box, 14.0) / 14.0


def test_lock_alternatives_swap_twins_and_respect_sills_and_beams():
    s = FakeShip(avoid=("Zandvliet", "Van Cauwelaert", "Royers", "Kattendijk"))
    alts = C.lock_alternatives(s)
    to = sorted(t for _, t in alts)
    assert ("Zandvliet",) in to and ("Van Cauwelaert",) in to
    deep = FakeShip("tanker", 250.0, 40.0, 12.0, True, avoid=("Boudewijn", "Van Cauwelaert", "Kallo", "Royers", "Kattendijk"))
    assert all(not set(t) & {"Boudewijn", "Van Cauwelaert", "Kallo"} for _, t in C.lock_alternatives(deep))
    assert C.lock_alternatives(FakeShip(beam=45.0, avoid=("Zandvliet",))) == []
    assert C.lock_alternatives(FakeShip(avoid=None)) == []


class FakeView:
    def __init__(self, locks):
        self._locks = locks

    def locks(self):
        return self._locks

    def ship(self, sid):
        return None


def chamber(state="open", side="a", waiting_a=(), waiting_b=(), inside=(), length=320.0, width=24.0, timer=0.0):
    return {"state": state, "side": side, "length_m": length, "width_m": width, "inside": list(inside),
            "waiting_a": list(waiting_a), "waiting_b": list(waiting_b), "timer_min": timer}


def test_lock_wait_grows_with_the_queue_and_the_chamber_being_away():
    tc = C.cycle_min("Kreekrak")
    m = C.LockModel(FakeView({"Kreekrak": {"east": chamber()}}))
    assert m.entry_min("Kreekrak", "a", 110, 11.4) == 0.0
    assert m.entry_min("Kreekrak", "b", 110, 11.4) == pytest.approx(tc)
    cap = C.capacity(chamber(), 110, 11.4)
    busy = C.LockModel(FakeView({"Kreekrak": {"east": chamber(waiting_a=[f"s{i}" for i in range(2 * cap)])}}))
    assert busy.entry_min("Kreekrak", "a", 110, 11.4) == pytest.approx(2 * 2 * tc)
    assert m.entry_min("Kreekrak", "a", 400, 11.4) is None      # too long for the chamber


class SpeedShip(FakeShip):
    def __init__(self, sea=9.5, river=8.6, plan=9.0, **kw):
        super().__init__(**kw)
        self._top = {"sea": sea, "river": river}
        self._plan = plan
        self.next_lock_side = "a"

    def max_speed_kn(self, leg="river"):
        return self._top[leg]

    def planning_speed_kn(self, leg="river"):
        return self._plan


def test_speed_orders_stay_within_what_the_engine_accepts():
    from strategies.equilibrium_guidance import EquilibriumGuidance
    # its own top speed is below its class's planning speed (its spread): an order at the planning speed is clamped
    slow = SpeedShip(sea=8.2, river=8.0, plan=9.0)
    assert EquilibriumGuidance.speed_order(slow, 9.0) == pytest.approx(8.2)
    assert EquilibriumGuidance.speed_order(slow, 1.0) == pytest.approx(3.0)     # vts_api.MIN_SPEED_KN
    assert EquilibriumGuidance.speed_order(slow, 6.5) == pytest.approx(6.5)


def test_local_lookahead_leaves_sea_going_ships_chambers_to_the_engine():
    s = strategies.load("local_lookahead")
    s.start()
    tanker = SpeedShip(cls="tanker", loa=180.0, beam=28.0, draught=10.0, sea_going=True)
    assert s.choose_chamber(tanker, "Terneuzen", ["Terneuzen west lock", "Terneuzen east lock"], "Terneuzen west lock") is None


def test_a_quay_position_at_the_end_of_a_free_stretch_can_be_booked():
    # strategy 2 lies a ship at the end of a free stretch, s0 = b - loa; s0 + loa then rounds past b. Run 200: the
    # booking failed, the ship was cleared with no quay booked and the run stopped when it moored
    from terminals import Moored, Terminal
    T = Terminal("T", "T", [(0.0, 0.0), (2000.0, 0.0)], 2000.0, 2000.0, 16.0, 8, 25.0)
    T.ships.append(Moored("A", 280.0, 1370.7, 1650.7, 0.0))        # free quay before it: 0 .. 1348.2 (gap 22.5 m)
    a, b = T.free_intervals()[0]
    assert (a, b) == (0.0, pytest.approx(1348.2))
    loa = 261.4
    s0 = b - loa
    assert s0 + loa > b                                             # the rounding the booking has to allow for
    assert T.moor("B", loa, 0.0, s0=s0, arrived=False) is not None
    assert T.moor("C", 10.0, 0.0, s0=b + 1.0, arrived=False) is None   # a position off the free quay is still refused


class OrderView:
    """What strategy 2's order and quay planning read of the view."""
    now = 600.0

    @staticmethod
    def default_priority(ship):
        from vts_api import View
        return View.default_priority(ship)


class QueueShip:
    def __init__(self, sid, departing=False, cls="bulk_general", request_t=0.0, berth_min=None, tide=False):
        self.id, self.departing, self.cls, self.request_t = sid, departing, cls, request_t
        self.scheduled_berth_min, self.tide_dependent, self.distress = berth_min, tide, False


def test_chain_planning_clears_late_container_ships_first_and_departures_first_on_request():
    ships = [QueueShip("arrival", request_t=10.0), QueueShip("box late", cls="container", request_t=50.0, berth_min=100.0),
             QueueShip("box early", cls="container", request_t=5.0, berth_min=900.0),
             QueueShip("departure", departing=True, request_t=40.0), QueueShip("tide", request_t=60.0, tide=True)]
    s = strategies.load("chain_planning")
    s.start()
    s.view = OrderView()
    assert [x.id for x in sorted(ships, key=s.order)] == ["tide", "box late", "box early", "arrival", "departure"]
    first = strategies.load("chain_planning", {"departures_first": True})
    first.start()
    first.view = OrderView()
    assert [x.id for x in sorted(ships, key=first.order)] == ["tide", "departure", "box late", "box early", "arrival"]


def test_chain_planning_paces_sea_going_ships_but_not_tide_dependent_ones_or_ulcvs():
    s = strategies.load("chain_planning")
    s.start()
    s1 = strategies.load("local_lookahead")
    s1.start()
    barge, tanker = FakeShip(), FakeShip("tanker", 180.0, 28.0, 10.0, True)
    deep, big = FakeShip("bulk_general", 290.0, 45.0, 14.5, True), FakeShip("container", 400.0, 61.0, 15.5, True, teu=24000)
    for x in (barge, tanker, deep, big):
        x.tide_dependent, x.ulcv = x is deep, x is big
    assert s.jit_ok(barge) and s.jit_ok(tanker)
    assert not s.jit_ok(deep) and not s.jit_ok(big)            # their tide windows and rules come first
    assert s1.jit_ok(barge) and not s1.jit_ok(tanker)          # strategy 1 paces sea-going ships only when asked
    assert s.jit_margin(tanker) > s1.jit_margin(tanker)


def test_the_booked_quay_comes_free_when_the_ships_lying_on_it_leave():
    from strategies.chain_planning import CLEARING_MIN
    s = strategies.load("chain_planning")
    s.start()
    s.view = OrderView()
    me = QueueShip("me", cls="container")
    T = {"ships": [("me", 500.0, 800.0, False, None),          # its booking, quay metres 500-800
                   ("A", 300.0, 520.0, True, 650.0),            # lies across its stretch, planned to leave at 650
                   ("B", 830.0, 1100.0, True, 2000.0),          # beyond the gap kept between ships
                   ("C", 1200.0, 1500.0, True, None)]}
    assert s.quay_free_at(me, T) == pytest.approx(650.0)
    T["ships"].append(("D", 700.0, 790.0, True, None))         # ready to leave, not yet cleared
    assert s.quay_free_at(me, T) == pytest.approx(OrderView.now + CLEARING_MIN)
    assert s.quay_free_at(QueueShip("no booking"), T) is None


class ClassView(FakeView):
    """A lock snapshot whose queued ships have a class (sea-going or not)."""
    def __init__(self, locks, sea_going_ids):
        super().__init__(locks)
        self._sea = set(sea_going_ids)

    def ship(self, sid):
        return SpeedShip(cls="tanker", sea_going=True) if sid in self._sea else SpeedShip()


def test_a_sea_going_ship_counts_only_the_sea_going_ships_queued_before_it():
    # lock priority 3 against 4: the inland craft queued at its side go in after it. Counting them slowed sea-going
    # ships for waits they did not have (screening runs, 2026-11-27)
    tc = C.cycle_min("Kreekrak")
    queue = [f"barge{i}" for i in range(12)] + ["tanker"]
    view = ClassView({"Kreekrak": {"east": chamber(waiting_a=queue, length=320.0, width=24.0)}}, ["tanker"])
    m = C.LockModel(view)
    s = strategies.load("chain_planning")
    s.start()
    s.view = view
    ship = SpeedShip(cls="bulk_general", loa=150.0, beam=20.0, draught=8.0, sea_going=True)
    cap = C.capacity(chamber(length=320.0, width=24.0), 150.0, 20.0)
    assert m.entry_min("Kreekrak", "a", 150.0, 20.0) == pytest.approx((len(queue) // cap) * 2 * tc)
    assert s.lock_entry(m, "Kreekrak", "a", ship, ahead=3, ahead_sea=0) == pytest.approx((1 // cap) * 2 * tc)
    barge = SpeedShip()
    s1 = strategies.load("local_lookahead")
    s1.start()
    assert s.lock_entry(m, "Kreekrak", "a", barge, 3, 0) == s1.lock_entry(m, "Kreekrak", "a", barge, 3, 0)
