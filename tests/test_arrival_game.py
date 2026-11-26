"""Focused tests runnable with unittest as well as pytest."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for folder in ("src", "src\\agents", "src\\sim"):
    sys.path.insert(0, str(ROOT / folder))

from arrival_equilibrium import best_responses, cost_before_berth, run_experiment
from arrival_approach_analysis import analyse
from strategies.arrival_game import ArrivalGame


def vessel(ship_id, **changes):
    fields = dict(id=ship_id, cls="container", terminal="T", scheduled_berth_min=300,
                  needs_pilot=True, distress=False, tide_dependent=False, departing=False,
                  request_t=0, ready=True)
    fields.update(changes)
    return SimpleNamespace(**fields)


class Control:
    def __init__(self):
        self.cleared = []
        self.notes = []

    def clear(self, ship):
        self.cleared.append(ship.id)
        return SimpleNamespace(ok=True, removed=False, reason=None)

    def note(self, ship, event, **values):
        self.notes.append((ship.id, event, values))


class View:
    now = 0
    round_min = 15

    def __init__(self):
        self.waiting = []

    def requests(self):
        return self.waiting

    def approach_estimate(self, ship):
        return {"source": "sea_west", "station": getattr(ship, "station", "Wandelaar"), "minutes": 0}

    @staticmethod
    def default_priority(ship):
        return (0 if ship.distress else 1 if ship.tide_dependent else 3, ship.request_t)


class ArrivalGameTests(unittest.TestCase):
    def strategy(self, **options):
        strategy = ArrivalGame(**options)
        view, control = View(), Control()
        strategy.bind(view, control)
        strategy.start()
        return strategy, view, control

    def test_windows_capacity_early_and_late(self):
        strategy, view, control = self.strategy(service_rule="A2",
                                                ship_arrival_hours={"a": 1})
        a, b = vessel("a"), vessel("b")
        self.assertEqual(strategy.arrival_delay(a, 60), 0)
        self.assertIsNone(strategy.arrival_delay(b, 60))
        self.assertEqual(strategy.windows, {"a": ("Wandelaar", 1), "b": ("Wandelaar", 2)})
        view.waiting = [a, b]
        strategy.on_tick(0)
        self.assertEqual(control.cleared, [])
        strategy.on_tick(60)
        self.assertEqual(control.cleared, ["a"])
        view.waiting = [b]
        b.request_t = 180
        strategy.on_tick(180)
        self.assertEqual(control.cleared, ["a", "b"])
        self.assertEqual(control.notes[-1][2]["start"], 180)

    def test_safety_and_unscheduled_bypass_windows(self):
        strategy, view, control = self.strategy(service_rule="A2")
        normal = vessel("normal")
        emergency = vessel("emergency", distress=True, request_t=10)
        tide = vessel("tide", tide_dependent=True, request_t=20)
        background = vessel("background", cls="tanker", scheduled_berth_min=None)
        for ship in (normal, emergency, tide, background):
            strategy.arrival_delay(ship, 60)
        self.assertEqual(set(strategy.windows), {"normal"})
        view.waiting = [normal, background, tide, emergency]
        strategy.on_tick(0)
        self.assertEqual(control.cleared, ["emergency", "tide", "background"])

    def test_arrived_on_time_remains_eligible_after_window(self):
        strategy, view, control = self.strategy(service_rule="A2")
        a = vessel("a", request_t=90)
        strategy.arrival_delay(a, 60)
        view.waiting = [a]
        strategy.on_tick(135)
        self.assertEqual(control.cleared, ["a"])
        self.assertEqual(len([n for n in control.notes if n[1] == "arrival_window"]), 1)

    def test_capacity_is_per_station(self):
        strategy, _, _ = self.strategy(service_rule="A2")
        a, b = vessel("a", station="Wandelaar"), vessel("b", station="Steenbank")
        strategy.arrival_delay(a, 60)
        strategy.arrival_delay(b, 60)
        self.assertEqual(strategy.windows, {"a": ("Wandelaar", 1), "b": ("Steenbank", 1)})

    def test_a1_preserves_safety_fcfs(self):
        strategy, view, control = self.strategy(service_rule="A1")
        early = vessel("early", distress=True, request_t=1, scheduled_berth_min=500)
        late = vessel("late", distress=True, request_t=2, scheduled_berth_min=100)
        view.waiting = [late, early]
        strategy.on_tick(0)
        self.assertEqual(control.cleared, ["early", "late"])

    def test_a1_does_not_prioritize_departures_by_old_berth_plan(self):
        strategy, view, control = self.strategy(service_rule="A1")
        arriving = vessel("arriving", request_t=10, scheduled_berth_min=300)
        departing = vessel("departing", departing=True, request_t=0, scheduled_berth_min=100)
        view.waiting = [departing, arriving]
        strategy.on_tick(0)
        self.assertEqual(control.cleared, ["arriving", "departing"])

    def test_a0_fcfs_and_individual_lead(self):
        strategy, view, control = self.strategy(service_rule="A0", early_arrival_hours=1,
                                                ship_arrival_hours={"a": 2})
        a = vessel("a", request_t=10, scheduled_berth_min=100)
        b = vessel("b", request_t=0, scheduled_berth_min=500)
        self.assertEqual(strategy.arrival_delay(a, 180), 60)
        self.assertEqual(strategy.arrival_delay(b, 180), 120)
        view.waiting = [a, b]
        strategy.on_tick(0)
        self.assertEqual(control.cleared, ["b", "a"])

    def test_invalid_options(self):
        for options in ({"service_rule": "A3"}, {"early_arrival_hours": float("nan")},
                        {"ship_arrival_hours": {"a": -1}}, {"service_rule": "A2", "window_min": 20},
                        {"window_capacity": 0}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.strategy(**options)

    def test_best_response_and_final_regret(self):
        def evaluate(profile):
            return {"a": abs(profile["a"] - 2), "b": abs(profile["b"] - profile["a"])}
        result = best_responses(["a", "b"], [0, 2], evaluate, {"a": 0, "b": 0}, 4, 0)
        self.assertEqual(result["profile"], {"a": 2, "b": 2})
        self.assertEqual(result["epsilon"], 0)
        self.assertTrue(result["converged"])

    def test_cycle_is_not_reported_as_equilibrium(self):
        def evaluate(profile):
            equal = profile["a"] == profile["b"]
            return {"a": float(not equal), "b": float(equal)}
        result = best_responses(["a", "b"], [0, 1], evaluate, {"a": 0, "b": 0}, 10, 0)
        self.assertFalse(result["converged"])
        self.assertEqual(result["stop_reason"], "cycle")
        self.assertEqual(result["epsilon"], 1)

    def test_cost_excludes_wait_after_berth_and_unfinished_fails(self):
        ship = SimpleNamespace(id="a", times={"at_berth": 180}, schedule={"berth_min": 120},
                               log=[{"t": 0, "event": "spawned"},
                                    {"t": 30, "event": "wait_clearance"},
                                    {"t": 60, "event": "anchored"},
                                    {"t": 90, "event": "sailing"},
                                    {"t": 180, "event": "at_berth"},
                                    {"t": 240, "event": "wait_clearance"}])
        weights = {"waiting": 1, "early": 0.5, "late": 2}
        self.assertEqual(cost_before_berth(ship, weights), 3)
        ship.times = {}
        with self.assertRaises(ValueError):
            cost_before_berth(ship, weights)

    def test_experiment_uses_same_seeds_for_every_profile(self):
        calls = []

        class FakeSimulation:
            def __init__(self, **options):
                calls.append((options["seed"], dict(options["vts_options"]["ship_arrival_hours"])))
                self.positions = SimpleNamespace(close=lambda: None)
                self.ships = []
                berth = 120 + options["seed"] * 60 - options["vts_options"]["ship_arrival_hours"]["a"] * 60
                self.done = [SimpleNamespace(id="a", name="ship", cls="container", terminal="T", spawn_t=0,
                                             times={"at_berth": berth}, schedule={"berth_min": 120},
                                             log=[{"t": 0, "event": "spawned"},
                                                  {"t": berth, "event": "at_berth"}])]

            def run(self, **kwargs):
                pass

        args = SimpleNamespace(players=["a"], waiting=1, early=0.5, late=2, warmup=0, days=2,
                               container_rate=1, seed=1, seeds=[1, 2], rule="A0", window_min=60,
                               window_capacity=1, approach_buffer_min=0, containers="replay", actions=[0, 1],
                               start="2026-10-21 00:00", no_delays=False, no_background=False,
                               iterations=2, tolerance=0)
        with patch.dict(sys.modules, {"engine": SimpleNamespace(Simulation=FakeSimulation)}):
            result = run_experiment(args)
        self.assertEqual(result["profile"], {"a": 1})
        self.assertEqual(result["costs"]["a"], 1)
        self.assertEqual(result["epsilon"], 0)
        self.assertEqual(calls, [(1, {"a": 0}), (2, {"a": 0}), (1, {"a": 1}), (2, {"a": 1})])

    def test_approach_analysis_uses_first_station_arrival_and_reports_incomplete(self):
        events = pd.DataFrame([
            {"ship": "a", "event": "approach_estimate", "t": 0, "source": "sea_west",
             "station": "Wandelaar", "approach_min": 30},
            {"ship": "a", "event": "to_station", "t": 10},
            {"ship": "a", "event": "wait_clearance", "t": 60},
            {"ship": "a", "event": "wait_clearance", "t": 200},
            {"ship": "b", "event": "approach_estimate", "t": 0, "source": "sea_north",
             "station": "Steenbank", "approach_min": 40},
            {"ship": "b", "event": "to_station", "t": 20},
        ])
        rows, summary = analyse(events)
        self.assertEqual(rows.iloc[0].actual_min, 50)
        self.assertEqual(summary["overall"]["candidate_buffer_p90_min"], 20)
        self.assertEqual(summary["incomplete"], 1)


if __name__ == "__main__":
    unittest.main()
