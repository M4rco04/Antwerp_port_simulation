"""Estimate a finite arrival game by unilateral best responses.

Example (ship IDs must exist and berth in the observation):
    py src\\sim\\arrival_equilibrium.py --players C0001 C0002 --rule A2 --days 14 --warmup 2 --output results\\arrival_game.json

The other ships retain the default lead. This is a sample-path game for the
selected ships, not a population-wide equilibrium. Each profile is evaluated
with the same seeds, and each player's costs are averaged across seeds.
Ship IDs, names and terminals must identify the same ships across seeds.
Incomplete outcomes are errors, not zero costs. Early-arrival choices only
reduce the model's existing sea hold.

Pick IDs from a comparable run's ships.csv and allow enough time for every
selected ship to berth after warmup under every tested profile. The JSON
records the final profile, costs, per-player regrets, epsilon, iteration
history, and whether epsilon met the tolerance. A cycle or iteration limit
does not imply convergence. Costs use pre-berth anchorage and clearance
waiting, and early/late berth time; weights are adjustable, and fuel is not
included. Each tested profile requires one full simulation per seed.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def _finite_nonnegative(value, name):
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return number


def best_responses(players, actions, evaluate, initial, max_iterations, tolerance):
    """Sequential best responses followed by a fresh unilateral regret check."""
    players = tuple(players)
    actions = tuple(sorted(set(actions)))
    if not players or len(set(players)) != len(players):
        raise ValueError("players must be a nonempty list of distinct IDs")
    if not actions or any(not math.isfinite(x) or not 0 <= x <= 48 for x in actions):
        raise ValueError("actions must contain finite values from 0 to 48 hours")
    if max_iterations < 1 or tolerance < 0 or not math.isfinite(tolerance):
        raise ValueError("invalid iteration limit or tolerance")
    if set(initial) != set(players) or any(initial[p] not in actions for p in players):
        raise ValueError("initial profile must provide an available action for every player")
    profile = dict(initial)
    cache = {}

    def costs(candidate):
        key = tuple(candidate[p] for p in players)
        if key not in cache:
            result = evaluate(dict(candidate))
            if set(result) != set(players) or any(not math.isfinite(result[p]) for p in players):
                raise ValueError("simulation must return a finite cost for every player")
            cache[key] = dict(result)
        return cache[key]

    def response(player):
        current_cost = costs(profile)[player]
        best_action, best_cost = profile[player], current_cost
        for action in actions:
            candidate = {**profile, player: action}
            cost = costs(candidate)[player]
            if cost < best_cost:
                best_action, best_cost = action, cost
        return best_action, max(0.0, current_cost - best_cost)

    history = []
    seen = set()
    reason = "iteration_limit"
    for iteration in range(1, max_iterations + 1):
        key = tuple(profile[p] for p in players)
        if key in seen:
            reason = "cycle"
            break
        seen.add(key)
        for player in players:
            action, gain = response(player)
            if gain > tolerance:
                profile[player] = action
        regrets = {player: response(player)[1] for player in players}
        epsilon = max(regrets.values())
        history.append({"iteration": iteration, "profile": dict(profile),
                        "costs": costs(profile), "regrets": regrets, "epsilon": epsilon})
        if epsilon <= tolerance:
            reason = "tolerance"
            break
    regrets = {player: response(player)[1] for player in players}
    return {"profile": profile, "costs": costs(profile), "regrets": regrets,
            "epsilon": max(regrets.values()), "converged": max(regrets.values()) <= tolerance,
            "stop_reason": reason, "profiles_simulated": len(cache), "history": history}


def cost_before_berth(ship, weights):
    """Hours spent waiting before first berth plus early/late berth penalties."""
    berth = ship.times.get("at_berth")
    planned = (ship.schedule or {}).get("berth_min")
    if berth is None or planned is None:
        raise ValueError(f"{ship.id}: no observed berth time or planned berth time")
    waiting = 0.0
    state, since = None, None
    states = {"spawned", "to_station", "wait_clearance", "to_anchorage", "anchored", "boarding",
              "sailing", "pilot_change", "wait_pilot", "lock_queue", "in_lock", "mooring", "at_berth"}
    for event in ship.log:
        if event["event"] not in states:
            continue
        t = float(event["t"])
        if since is not None and state in {"anchored", "wait_clearance"}:
            waiting += max(0.0, min(t, berth) - since)
        if t >= berth:
            break
        state, since = event["event"], t
    else:
        raise ValueError(f"{ship.id}: berth event missing from ship log")
    difference = (float(berth) - float(planned)) / 60.0
    return (weights["waiting"] * waiting / 60.0
            + weights["early"] * max(-difference, 0.0)
            + weights["late"] * max(difference, 0.0))


def run_experiment(args):
    import engine

    players = tuple(args.players)
    weights = {name: _finite_nonnegative(getattr(args, name), name)
               for name in ("waiting", "early", "late")}
    if not math.isfinite(args.days) or not math.isfinite(args.warmup) or args.warmup < 0 or args.days <= args.warmup:
        raise ValueError("days must exceed a nonnegative warmup")
    if not math.isfinite(args.container_rate) or args.container_rate <= 0:
        raise ValueError("container_rate must be finite and positive")
    seeds = args.seeds if args.seeds is not None else [args.seed]
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("seeds must be nonempty and distinct")
    reference = {}
    identities = {}

    def evaluate(profile):
        options = {"service_rule": args.rule, "ship_arrival_hours": profile,
                   "window_min": args.window_min, "window_capacity": args.window_capacity,
                   "approach_buffer_min": args.approach_buffer_min}
        totals = dict.fromkeys(players, 0.0)
        for seed in seeds:
            sim = engine.Simulation(start=args.start, days=args.days, warmup_days=args.warmup, seed=seed,
                                    delays=not args.no_delays, background=not args.no_background,
                                    container_mode=args.containers, container_rate=args.container_rate,
                                    vts="arrival_game", vts_options=options)
            try:
                sim.run(progress_hours=1e9)
                ships = {ship.id: ship for ship in sim.done + sim.ships}
                missing = set(players) - ships.keys()
                if missing:
                    raise ValueError(f"seed {seed}: players not observed: {', '.join(sorted(missing))}")
                for player in players:
                    ship = ships[player]
                    if ship.cls != "container" or ship.terminal is None or ship.spawn_t < args.warmup * 1440:
                        raise ValueError(f"seed {seed}, {player}: must be a container with a terminal entering after warmup")
                    identity = (ship.name, ship.terminal)
                    if player in identities and identities[player] != identity:
                        raise ValueError(f"{player}: ship identity differs between seeds; use stable IDs or one seed")
                    identities[player] = identity
                    plan = (identity, ship.schedule.get("berth_min"))
                    if (seed, player) in reference and reference[seed, player] != plan:
                        raise ValueError(f"seed {seed}, {player}: ship identity or plan changed between profiles")
                    reference[seed, player] = plan
                    totals[player] += cost_before_berth(ship, weights)
            finally:
                sim.positions.close()
        return {player: totals[player] / len(seeds) for player in players}

    result = best_responses(players, args.actions, evaluate,
                            {player: args.actions[0] for player in players},
                            args.iterations, args.tolerance)
    result["settings"] = {"rule": args.rule, "players": players, "actions_hours": args.actions,
                          "seeds": seeds, "days": args.days, "warmup_days": args.warmup,
                          "containers": args.containers, "container_rate": args.container_rate,
                          "window_min": args.window_min, "window_capacity": args.window_capacity,
                          "approach_buffer_min": args.approach_buffer_min, "weights": weights,
                          "start": args.start, "delays": not args.no_delays, "background": not args.no_background,
                          "tolerance": args.tolerance, "iterations": args.iterations}
    result["limitations"] = ("Sample mean over specified seeds and selected ships only; all other ships use zero lead. "
                             "No fuel cost. Epsilon covers only the supplied discrete actions. "
                             "A2 uses estimated approach time and has no advance ETA announcements.")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--players", nargs="+", required=True, help="IDs of scheduled container ships")
    parser.add_argument("--rule", choices=("A0", "A1", "A2"), default="A2")
    parser.add_argument("--actions", nargs="+", type=float, default=[0, 2, 4, 6, 8])
    parser.add_argument("--start", default="2026-10-21 00:00")
    parser.add_argument("--days", type=float, default=14)
    parser.add_argument("--warmup", type=float, default=2)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--seeds", nargs="+", type=int, help="paired seeds for all profiles (overrides --seed)")
    parser.add_argument("--containers", choices=("replay", "weeks", "nhpp"), default="weeks")
    parser.add_argument("--container-rate", type=float, default=1)
    parser.add_argument("--no-delays", action="store_true")
    parser.add_argument("--no-background", action="store_true")
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--tolerance", type=float, default=0.01)
    parser.add_argument("--waiting", type=float, default=1)
    parser.add_argument("--early", type=float, default=0.5)
    parser.add_argument("--late", type=float, default=2)
    parser.add_argument("--window-min", type=float, default=60)
    parser.add_argument("--window-capacity", type=int, default=1)
    parser.add_argument("--approach-buffer-min", type=float, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_experiment(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(f"epsilon={result['epsilon']:.6g}; converged={result['converged']}; saved to {args.output}")


if __name__ == "__main__":
    main()
