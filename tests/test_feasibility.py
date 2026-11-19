"""The rules that put a draw right instead of removing the ship (MODEL.md §10.2, §15.2, fifth round of §19).

Each builds one Simulation (a few seconds) and asks it about ships made by hand, without running it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
for d in ("sim", "agents", "environment", "data"):
    sys.path.insert(0, str(ROOT / "src" / d))

from ship import Ship  # noqa: E402


@pytest.fixture(scope="module")
def sim():
    import engine

    return engine.Simulation(start="2026-10-21 00:00", days=1, seed=1, warmup_days=0.0, container_mode="weeks")


def ship(cls, loa, beam, draught, source="sea_west", destination="exit_sea_west", **kw):
    s = Ship(id=f"T-{cls}-{loa}-{beam}-{draught}", cls=cls, loa=loa, beam=beam, draught=draught, level=2, source=source,
             destination=destination, spawn_t=0.0, **kw)
    s.arrival_draught = draught
    return s


def node(sim, place):
    return sim.places[place]["node"]


def events(s, name):
    return [e for e in s.log if e["event"] == name]


# ------------------------------------------------------------------ reach by the ship's own size
def test_a_craft_of_23_m_beam_passes_the_24_m_chambers(sim):
    """Kreekrak and Hansweert have 24 m chambers. The search per size class takes the beam to the next 5 m, so a
    craft of 23 m counts as 25 m there; asked again by its own size it reaches the canal (it used to leave by the
    sea instead, 83 craft a run)."""
    canal, river = node(sim, "zuid_beveland_canal"), node(sim, "vlissingen")
    wide = ship("inland_cargo", 110.0, 23.0, 3.0)
    by_class = sim.reach(wide)
    assert not (by_class[canal] and by_class[river])           # the class alone says no
    assert sim.reachable_between(canal, river, wide)          # its own beam says yes
    too_wide = ship("inland_cargo", 110.0, 25.0, 3.0)
    assert not sim.reachable_between(canal, river, too_wide)  # 25 m does not fit 24 m chambers


# ------------------------------------------------------------------ draught of a container ship to a zone
def _deepest(sim, s, ids):
    """The deepest draught, in half metres, at which a berth of `ids` takes a ship of the size of `s`."""
    drawn = s.draught
    try:
        for t in [20.0 - 0.5 * k for k in range(36)]:
            s.draught = t
            if any(sim._berth_fits(sim.berths[b], s, ignore_tanker=True) for b in ids):
                return t
        return None
    finally:
        s.draught = drawn


def test_a_container_ship_is_loaded_to_what_the_berth_allows(sim):
    """Bound for a zone whose berths allow less than its draught (drawn from its TEU), a container ship comes at
    the deepest draught a berth there takes, in half metres (it used to be removed)."""
    s = ship("container", 150.0, 25.0, 0.0)
    zone = "antwerp_river_quays"
    ids = sim.destinations[zone]["berths"]
    deepest = _deepest(sim, s, ids)
    assert deepest is not None and deepest >= 8.0
    s.draught = deepest + 1.2                                  # drawn deeper than any berth there allows
    assert sim._cap_draught_to_zone(s, zone, ids)
    assert s.draught == deepest
    assert events(s, "draught_capped")[0]["allowed"] == deepest


def test_a_container_ship_is_not_capped_below_8_m(sim):
    """A berth that takes the ship only under 8 m: no cap (a container ship of the schedule is not that light)."""
    s = ship("container", 100.0, 15.0, 0.0)
    shallow = [b for b in sim.berths if (t := _deepest(sim, s, [b])) is not None and t < 8.0][:1]
    assert shallow
    s.draught = 12.0
    assert not sim._cap_draught_to_zone(s, "test", shallow)
    assert s.draught == 12.0 and not events(s, "draught_capped")


# ------------------------------------------------------------------ voyages with no route at high water
def test_a_further_call_that_cannot_be_reached_is_left_out(sim):
    s = ship("tanker", 150.0, 25.0, 9.5)
    s.shift, s.at, s.target = "zuid_beveland_canal", node(sim, "vlissingen"), node(sim, "zuid_beveland_canal")
    assert sim.unreachable_resolved(s, 0.0)
    assert s.shift is None and events(s, "next_call_unfit")


def test_a_ship_from_a_canal_comes_at_the_draught_the_canal_carries(sim):
    """A sea-going ship entering from the Schelde-Rijn canal with a draught drawn deeper than the canal carries
    came through it: its draught is lowered, in half metres, to the deepest that gets it to its target."""
    s = ship("bulk_general", 100.0, 14.0, 9.5, source="schelde_rijn_canal", destination="vlissingen")
    s.at, s.target = node(sim, "schelde_rijn_canal"), node(sim, "vlissingen")
    if sim.voyage_reachable(s, s.at, s.target):
        pytest.skip("9.5 m passes the canal: pick a deeper draught")
    assert sim.unreachable_resolved(s, 0.0)
    assert s.draught < 9.5 and sim.voyage_reachable(s, s.at, s.target)
    capped = s.draught
    s.draught = capped + 0.5
    assert not sim.voyage_reachable(s, s.at, s.target)
    s.draught = capped
    assert events(s, "draught_capped")


def test_a_ship_on_the_river_with_no_route_is_not_put_right(sim):
    """Only the two causes above are put right: a sea-going ship on the river with no route keeps its draught."""
    s = ship("bulk_general", 100.0, 14.0, 30.0)
    s.at, s.target = node(sim, "vlissingen"), node(sim, "zuid_beveland_canal")
    assert not sim.unreachable_resolved(s, 0.0)
    assert s.draught == 30.0


# ------------------------------------------------------------------ waits for a berth
def test_a_next_call_is_dropped_only_after_a_day(sim):
    import engine

    assert engine.NEXT_CALL_WAIT_MIN == 24 * 60.0
    s = ship("bulk_general", 100.0, 14.0, 6.0)
    s.shift, s.shift_since, s.departing, s.exit = "zone", 0.0, True, "exit_sea_west"
    s.at = node(sim, "vlissingen")
    t0 = sim.t
    try:
        sim.t = engine.NEXT_CALL_WAIT_MIN + 5.0
        sim.choose_target(s)
    finally:
        sim.t = t0
    assert s.shift is None and events(s, "next_call_dropped")


def test_inland_craft_lie_alongside_only_while_there_is_room(sim):
    """A zone's berths all taken: an inland craft lies beside one, one craft per berth it could take
    (ALONGSIDE_PER_BERTH); when those places are taken too it waits (berth_wait) instead of lying there anyway."""
    import engine

    craft = ship("inland_cargo", 80.0, 9.5, 2.5)
    zone = "antwerp_river_quays"
    ids = [b for b in sim.destinations[zone]["berths"] if sim._berth_fits(sim.berths[b], craft)]
    assert ids
    craft.destination = craft.berth_zone = zone
    saved_berths, saved_ships = dict(sim.berth_ship), list(sim.ships)
    try:
        for b in sim.destinations[zone]["berths"]:
            sim.berth_ship[b] = "taken"
        others = []
        for k in range(engine.ALONGSIDE_PER_BERTH * len(ids) - 1):
            o = ship("inland_cargo", 80.0, 9.5, 2.5)
            o.id, o.berth = f"alongside-{k}", {"alongside": zone}
            others.append(o)
        sim.ships[:] = saved_ships + others
        assert sim.choose_target(craft) is not None                 # one place left beside the berths
        assert craft.candidate["alongside"] == zone
        extra = ship("inland_cargo", 80.0, 9.5, 2.5)
        extra.id, extra.berth = "alongside-last", {"alongside": zone}
        sim.ships[:] = saved_ships + others + [extra]
        craft.candidate = None
        assert sim.choose_target(craft) is None                     # all taken: it waits
        assert events(craft, "berth_wait")
    finally:
        sim.berth_ship.clear()
        sim.berth_ship.update(saved_berths)
        sim.ships[:] = saved_ships


# ------------------------------------------------------------------ random streams per ship
def test_each_ship_draws_from_its_own_stream(sim):
    """A ship's choices, durations and speed come from a stream of its own (Simulation.ship_rng): what another ship
    draws, or whether it draws at all, does not move them. With one stream for all, one more draw for one ship moved
    every later draw of every other ship (MODEL.md §1)."""
    mk = lambda i: Ship(id=i, cls="inland_cargo", loa=80.0, beam=9.5, draught=2.5, level=2, source="sea_west",
                        destination="exit_sea_west", spawn_t=0.0)
    first = sim.ship_rng(mk("A00001"), "choice").random(5)
    sim.ship_rng(mk("B00002"), "choice").random(100)            # another ship draws a hundred times
    again = sim.ship_rng(mk("A00001"), "choice").random(5)      # the same ship (by id) in another configuration
    assert (first == again).all()
    assert not (sim.ship_rng(mk("A00001"), "service").random(5) == first).all()   # streams differ by kind
    assert not (sim.ship_rng(mk("B00002"), "choice").random(5) == first).all()    # and by ship


# ------------------------------------------------------------------ the week in the stays
def test_inland_cargo_stays_run_out_slower_at_the_weekend(sim):
    """BT.STAY_END_FACTOR: an inland cargo craft's berth stay counts down at its class's rate for the local day,
    so stays end about half as often on a Sunday as on a weekday (AIS: inland cargo craft lie still over the
    weekend; MODEL.md §2.1)."""
    import background_traffic as BT
    import engine
    from ship import State

    f = BT.STAY_END_FACTOR["inland_cargo"]
    assert f[6] < 0.75 < 1.0 < f[0] and BT.STAY_END_FACTOR["tanker"] == [1.0] * 7
    t0 = sim.now_ts(0.0)
    t0 = t0.tz_localize("UTC") if t0.tzinfo is None else t0
    at = lambda local: (pd.Timestamp(local, tz="Europe/Brussels") - t0).total_seconds() / 60.0
    craft = ship("inland_cargo", 80.0, 9.5, 2.5)
    craft.id = "stay-week"
    saved = list(sim.ships)
    try:
        sim.ships[:] = [craft]
        used = {}
        for name, local in (("monday", "2026-10-26 12:00"), ("sunday", "2026-11-01 12:00")):
            craft.state, craft.timer, craft.berth = State.DWELL_PORT, 600.0, {"name": "antwerp_other", "kind": "place"}
            sim._timers(at(local))
            used[name] = 600.0 - craft.timer
        assert used["monday"] == pytest.approx(engine.DT_MIN * f[0])
        assert used["sunday"] == pytest.approx(engine.DT_MIN * f[6])
    finally:
        sim.ships[:] = saved


# ------------------------------------------------------------------ pilots and pilot boats
def test_a_pilot_boat_is_not_spent_when_no_pilot_is_free(sim):
    """take_pilots takes the pilot boat only once the pilots are certain: a ship waiting for a pilot tries again
    every step, and taking the boat first spent one for 30 min at each try, so that a shortage of pilots took
    all the boats too (the stress test at 1.5 times today's traffic, 18 November 2026)."""
    craft = ship("bulk_general", 180.0, 30.0, 9.0)
    craft.id = "pilot-boat-test"
    now = 600.0
    river = [p for p in sim.pilots.pilots if p.zone == "river"]
    saved = [(p.ship, p.free_at, dict(p.bookings)) for p in river]
    boats = list(sim.pilot_boats.busy_until)
    try:
        for p in river:
            p.ship = "someone-else"
        free_before = sim.pilot_boats.available(now)
        assert free_before > 0
        for _ in range(3):                                          # three steps of waiting
            assert not sim.take_pilots(craft, "river", now, boat=True)
        assert sim.pilot_boats.available(now) == free_before        # no boat spent
        river[0].ship = None
        river[0].free_at = 0.0
        river[0].bookings.clear()
        assert sim.take_pilots(craft, "river", now, boat=True)       # a pilot is free: it goes, with a boat
        assert sim.pilot_boats.available(now) == free_before - 1
    finally:
        for p, (s, f, b) in zip(river, saved):
            p.ship, p.free_at, p.bookings = s, f, b
        sim.pilot_boats.busy_until[:] = boats
        craft.pilots = []
