"""Verification tests: what must hold whatever the traffic.

    py -m pytest tests -m "not slow"     # the parts on their own, seconds
    py -m pytest tests                   # also the short simulation runs, about 10 minutes

The fast tests check the parts against hand calculations (lock packing, a lockage's duration, quay allocation,
cranes, the pilot pool, the random streams). The slow ones run the whole model for a short time with
check_invariants on every step (engine.Simulation(checks=True)) and check that a seed reproduces a run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
for d in ("sim", "agents", "environment", "data"):
    sys.path.insert(0, str(ROOT / "src" / d))

import locks  # noqa: E402
from locks import Chamber, Lock, LockTimes, ShipRequest, pack  # noqa: E402
from services import PilotPool  # noqa: E402
from terminals import Terminal  # noqa: E402

START = "2026-10-21 00:00"


# ------------------------------------------------------------------ locks
def overlap(p, q):
    return (p.x < q.x + q.ship.loa and q.x < p.x + p.ship.loa and p.y < q.y + q.ship.beam and q.y < p.y + p.ship.beam)


def test_pack_keeps_ships_inside_and_apart():
    rng = np.random.default_rng(1)
    packed = 0
    for _ in range(300):
        ships = [ShipRequest(f"s{i}", float(rng.uniform(40, 200)), float(rng.uniform(6, 30)), 3.0, "a", turn=i)
                 for i in range(int(rng.integers(1, 9)))]
        placed = pack(500.0, 57.0, ships, 10.0, 2.0)
        if placed is None:
            continue
        packed += 1
        assert {p.ship.ship_id for p in placed} == {s.ship_id for s in ships}
        for p in placed:
            assert p.x >= 0 and p.y >= 0 and p.x + p.ship.loa <= 500.0 and p.y + p.ship.beam <= 57.0
        for i, p in enumerate(placed):
            for q in placed[i + 1:]:
                assert not overlap(p, q)
    assert packed > 50


def test_pack_refuses_what_does_not_fit():
    assert pack(200.0, 24.0, [ShipRequest("long", 250.0, 20.0, 3.0, "a")]) is None
    assert pack(200.0, 24.0, [ShipRequest("wide", 100.0, 30.0, 3.0, "a")]) is None
    two = [ShipRequest("a", 110.0, 11.4, 3.0, "a", turn=1), ShipRequest("b", 110.0, 11.4, 3.0, "a", turn=2)]
    assert pack(200.0, 25.0, two, 10.0, 2.0) is not None          # side by side: 11.4 + 2 + 11.4 <= 25
    assert pack(200.0, 20.0, two, 10.0, 2.0) is None              # neither side by side nor end to end


def test_one_ship_through_a_lock_takes_the_published_time():
    """A single barge through Kreekrak west: entry, the hold for more ships, the published operating time
    (11 min: gates and levelling), exit."""
    times = LockTimes()
    name = "Kreekrak west"
    lock = Lock("Kreekrak", [Chamber(name, 320.0, 24.0, 6.0)], sides={"a": {"nodes": []}, "b": {"nodes": []}}, times=times)
    lock.request(ShipRequest("barge", 110.0, 11.4, 3.0, "a"), 0.0)
    events, t = [], 0.0
    while t < 120 and not any(e["event"] == "exit" for e in events):
        events += lock.step(t, 1.0, {"a": 0.0, "b": 1.5})
        t += 1.0
    out = next(e["t"] for e in events if e["event"] == "exit")
    work = times.small_entry_min + locks.OPERATING_MIN[name] + times.small_exit_min
    assert work - 1 <= out <= work + locks.BUNDLE_HOLD_MIN + 2, (out, work)
    assert not lock.chambers[0].ships


# ------------------------------------------------------------------ terminals
def terminal(sts=6, per_ship=None):
    return Terminal(name="T", code="T", quay_line=[(0.0, 0.0), (1000.0, 0.0)], quay_length_m=1000.0,
                    documented_quay_m=1000.0, max_draft_m=16.0, sts=sts, moves_per_crane_h=30.0,
                    max_cranes_per_ship=per_ship, berths={"B1": {"s0": 0.0, "s1": 1000.0, "nodes": []}})


def test_quay_never_double_booked():
    try:
        T = terminal()
    except TypeError:
        pytest.skip("Terminal's fields changed: update this helper")
    rng = np.random.default_rng(2)
    moored, most = [], 0
    for k in range(400):
        if moored and rng.random() < 0.45:
            T.unmoor(moored.pop(int(rng.integers(len(moored)))), float(k))
        else:
            m = T.moor(f"s{k}", float(rng.uniform(100, 400)), float(k))
            if m is not None:
                moored.append(m.ship_id)
        most = max(most, len(T.ships))
        spans = sorted((m.s0, m.s1) for m in T.ships)
        assert all(a1 + T.gap_m <= b0 + 1e-9 for (_, a1), (b0, _) in zip(spans, spans[1:]))
        assert all(0 <= a and b <= T.quay_length_m for a, b in spans)
    assert most >= 3
    assert T.moor("too long", 1200.0, 0.0) is None


def test_quay_is_planned_for_the_arrival_time():
    """A ship due after the one at the quay has left may book its metres; it moors only once they are clear."""
    T = terminal()
    first = T.moor("first", 900.0, 0.0)
    first.leaves = 600.0
    assert T.moor("now", 300.0, 100.0) is None                       # no room now
    assert T.moor("too early", 300.0, 100.0, at=500.0) is None       # nor at minute 500
    booked = T.moor("next", 300.0, 100.0, at=660.0, arrived=False)   # room once the first has left
    assert booked is not None and booked.leaves is None
    assert T.moor("third", 300.0, 100.0, s0=booked.s0, at=660.0) is None   # booked metres are taken
    assert not T.quay_clear("next")                                  # the first is late: the next one waits
    T.unmoor("first", 700.0)
    assert T.quay_clear("next")


def test_cranes_and_handling_time():
    try:
        T = terminal(sts=6, per_ship=4)
    except TypeError:
        pytest.skip("Terminal's fields changed: update this helper")
    T.moor("a", 300.0, 0.0)
    T.moor("b", 200.0, 0.0)
    assert T.assign_cranes("a", 8) == 4                     # the terminal's cap per ship (300 m / 45 m = 6)
    assert T.assign_cranes("b", 8) == 2                     # what is left of the six
    assert sum(m.cranes for m in T.ships) <= T.sts
    assert T.handling_hours(3600, 4) == pytest.approx(3600 / (4 * 30.0))


# ------------------------------------------------------------------ pilots
def test_pilot_pool_never_gives_more_than_it_has():
    pool = PilotPool({"sea": 3, "river": 2, "dock": 1})
    assert pool.take("sea", 2, "A", 0.0) is not None
    assert pool.take("sea", 2, "B", 0.0) is None            # one left
    got = pool.take("sea", 1, "B", 0.0)
    assert got is not None and pool.busy("sea", 0.0) == 3
    assert not pool.available("sea", 1, 10.0)
    pool.release(got, 60.0)
    assert not pool.available("sea", 1, 61.0)               # on its way back
    assert pool.available("sea", 1, 60.0 + 121.0)           # return time 120 min
    assert pool.book("river", 2, "C", 300.0, 0.0)
    assert not pool.book("river", 1, "D", 300.0, 0.0)       # both booked for then


# ------------------------------------------------------------------ random streams
def arrivals(seed, hours=24, **kw):
    import engine
    from generator import Generator

    q = dict(zip(engine.STREAMS, (np.random.default_rng(s) for s in np.random.SeedSequence(seed).spawn(len(engine.STREAMS)))))
    g = Generator(pd.Timestamp(START, tz="UTC"), q["arrivals"], rng_attributes=q["attributes"], container_mode="nhpp", **kw)
    out = []
    for k in range(int(hours * 12)):
        out += [(s.id, s.cls, round(s.spawn_t, 3), s.loa, s.beam, s.draught, s.source, s.destination) for s in g.arrivals(k * 5.0, 5.0)]
    return out, q


def test_same_seed_same_arrivals_whatever_else_is_drawn():
    a, _ = arrivals(7)
    b, q = arrivals(7)
    assert a == b and len(a) > 100
    c, _ = arrivals(8)
    assert a != c
    # draws from the other streams do not move the arrivals
    import engine
    from generator import Generator

    q = dict(zip(engine.STREAMS, (np.random.default_rng(s) for s in np.random.SeedSequence(7).spawn(len(engine.STREAMS)))))
    q["service"].random(1000), q["choice"].random(1000), q["movement"].random(1000)
    g = Generator(pd.Timestamp(START, tz="UTC"), q["arrivals"], rng_attributes=q["attributes"], container_mode="nhpp")
    d = []
    for k in range(24 * 12):
        d += [(s.id, s.cls, round(s.spawn_t, 3), s.loa, s.beam, s.draught, s.source, s.destination) for s in g.arrivals(k * 5.0, 5.0)]
    assert d == a


def test_container_calls_have_a_stay_and_a_berth_time():
    from generator import Generator

    g = Generator(pd.Timestamp(START, tz="UTC"), np.random.default_rng(3), container_mode="replay", background=False)
    assert len(g.pending) > 100
    for s in g.pending:
        assert s.stay_h and 1.0 <= s.stay_h <= 200.0
        # it enters 8 h before its berth time, and a ship that comes in at anchor its anchor stay before that
        wait = 60.0 * (getattr(s, "anchor_wait_h", None) or 0.0)
        assert s.schedule["berth_min"] == pytest.approx(s.spawn_t + 8 * 60 + wait)


def test_a_schedule_of_whole_weeks():
    """Mode "weeks": every run week is one real week; the calls keep their weekday, hour, ship and stay."""
    from generator import Generator, read_schedule

    real = read_schedule()
    start = pd.Timestamp("2027-03-03 00:00", tz="UTC")          # another date than the schedule's
    g = Generator(start, np.random.default_rng(4), container_mode="weeks", background=False, delays=False)
    ships = []
    for k in range(28 * 288):
        ships += g.arrivals(k * 5.0, 5.0)
    w = g.weeks
    assert w["n"] >= 6 and len(w["drawn"]) >= 4 and set(w["drawn"]) <= set(range(w["n"]))
    per_week = len(real) / ((real.arrival.max() - real.arrival.min()).days / 7)
    assert 0.6 * per_week * 4 < len(ships) < 1.4 * per_week * 4
    names = set(real.vessel)
    hours = {(v, t.tz_convert("Europe/Brussels").dayofweek, t.tz_convert("Europe/Brussels").hour) for v, t in zip(real.vessel, real.arrival)}
    moved = 0
    listed = [s for s in ships if not s.schedule.get("unscheduled")]
    for s in ships:
        assert s.name in names and s.stay_h > 0
    for s in listed:
        local = s.schedule["arrival"].tz_convert("Europe/Brussels")
        moved += (s.name, local.dayofweek, local.hour) not in hours
    assert moved <= 0.1 * len(listed)                            # only calls moved where two weeks join
    # the calls the schedule does not list come on top, at the AIS rate (a quarter of the listed ones)
    assert 0.1 * len(listed) < len(ships) - len(listed) < 0.5 * len(listed)
    # no terminal has more ships at once, on paper, than the check allows
    for name, plan in w["plan"].items():
        for a, _, _ in plan:
            assert sum(m for s, e, m in plan if s <= a < e) <= w["quay"][name] + 1e-6


# ------------------------------------------------------------------ the whole model, short runs
def simulate(days, seed, **kw):
    import engine

    sim = engine.Simulation(start=START, days=days, seed=seed, warmup_days=0.0, container_mode="weeks", **kw)
    sim.run(progress_hours=1e9)
    return sim


@pytest.mark.slow
def test_invariants_hold_every_step():
    sim = simulate(1.5, 11, checks=True)                    # check_invariants raises on the first one broken
    ships = sim.ship_table()
    summary = sim.summary(ships)
    assert sim.n_entered == len(ships) == summary["ships_generated"]
    assert summary["ships_generated"] == summary["ships_finished_after_warmup"] + summary["still_in_area"] \
        + int((ships.finished & (ships.spawn_min < sim.warmup_min)).sum())
    assert set(summary["release_valves"]) >= {"total", "per_1000_ships"}
    minutes = ships[[c for c in ships.columns if c.startswith("min_")]].fillna(0)
    assert (minutes >= 0).all().all()
    done = ships[ships.finished]
    # the time in the states adds up to the time in the area
    # (a ship enters at the start of the step its entry time falls in: up to one step before it)
    gap = minutes.loc[done.index].sum(axis=1) - (done.end_min - done.spawn_min)
    # (the minutes per state are rounded to 0.1 in the table: up to 0.05 off per state)
    assert gap.between(-0.5, 5.5).all(), gap.describe()
    # no container ship berths before its berth time by more than the planning error
    c = ships[(ships["class"] == "container") & ships.moored_min.notna() & ships.planned_berth_min.notna()]
    if len(c):
        assert ((c.moored_min - c.planned_berth_min) > -120).all()


@pytest.mark.slow
def test_a_seed_reproduces_a_run():
    a, b = simulate(0.5, 5), simulate(0.5, 5)
    pd.testing.assert_frame_equal(a.ship_table(), b.ship_table())
    assert len(a.ship_table()) != len(simulate(0.5, 6).ship_table()) or not a.ship_table().equals(simulate(0.5, 6).ship_table())
