"""Strategy 4, equilibrium guidance with an evolutionary algorithm inside: docs/strategies/port_management_strategies.md §6b.

The same round, players, strategies and costs as strategy 3 (equilibrium_guidance), but the joint decision is searched
by a genetic algorithm, inside the VTS and within a fraction of a second, for the lowest total cost rather than for
an equilibrium. No extra simulation runs: candidates are scored on the game's fast cost model.

    chromosome   one strategy per player (start and speed), and an order of precedence: who goes first where ships
                 compete for the last free pilot or pilot boat, and the order the clearances are given in
    fitness      the social cost (every ship's own cost plus what the others cost it), averaged over K perturbed
                 futures: travel times x N(1, 0.1) per ship and lock cycles x U(0.8, 1.2). A plan that only works when
                 everything goes to plan loses to one with slack (the reading's warning about stiff plans)
    seeds        the PULSE equilibrium of strategy 3 (lam 1), every ship's default (start now, full speed), and last
                 round's best for the ships still in the game; the GA can only improve on these on its own model
    operators    uniform crossover and +-1 mutation on the strategies, order crossover (OX) and swaps on the order,
                 tournament selection, elitism

Each round writes an "eq_round" event with the fitness of the PULSE seed (sc_seed) and of the GA's best (sc), so the
value of the search can be read back.

Options: those of equilibrium_guidance, plus samples 3, population 30, generations 20, travel_sd 0.1, cycle_spread 0.2.
"""

from __future__ import annotations

import numpy as np

from strategies import _games as G
from strategies.equilibrium_guidance import EquilibriumGuidance


class EvolutionaryGuidance(EquilibriumGuidance):
    name = "evolutionary_guidance"
    description = "S4: strategy 3's guidance game, searched each round by a genetic algorithm on perturbed futures"

    def start(self):
        super().start()
        o = self.options
        self.samples = int(o.get("samples", 3))
        self.pop = int(o.get("population", 30))
        self.gens = int(o.get("generations", 20))
        self.travel_sd = float(o.get("travel_sd", 0.1))
        self.cycle_spread = float(o.get("cycle_spread", 0.2))
        self.last_best = {}                    # ship id -> (start, speed share) of last round's best

    def solve(self, game):
        rng = self.view.rng
        n = game.n
        # the nominal game and its equilibrium, as strategy 3 finds it (with the full toll: a social-cost seed)
        internal0 = game.internal()
        recs0 = game.records()
        default_rank = list(range(n))
        pairs0 = game.pairs(recs0, default_rank)
        pulse, pinfo = G.pulse_solve(internal0, G.internalise(pairs0, 1.0), rng, iters=self.iters)
        # K perturbed futures, each scored fast on padded arrays
        pads = []
        for k in range(max(self.samples, 1)):
            if k == 0:
                eps, tc = None, 1.0
            else:
                eps = np.clip(rng.normal(1.0, self.travel_sd, n), 0.6, 1.6)
                tc = float(rng.uniform(1.0 - self.cycle_spread, 1.0 + self.cycle_spread))
            pads.append(game.padded(game.internal(eps, tc), game.records(eps, tc)))

        def fitness(genes, order):
            rank = np.empty(n, dtype=int)
            rank[np.asarray(order, dtype=int)] = np.arange(n)
            return sum(game.score(p, genes, rank) for p in pads) / len(pads)

        seeds = [(pulse, default_rank), ([0] * n, default_rank)]
        warm = []
        for j, p in enumerate(game.players):
            prev = self.last_best.get(p["ship"].id)
            warm.append(p["strats"].index(prev) if prev in p["strats"] else pulse[j])
        seeds.append((warm, default_rank))
        sc_seed = fitness(pulse, default_rank)
        genes, order, best, history = G.ga_solve(game.m, fitness, rng, seeds=seeds, pop=self.pop, gens=self.gens)
        self.last_best = {p["ship"].id: p["strats"][genes[j]] for j, p in enumerate(game.players)}
        rank = [0] * n
        for pos, j in enumerate(order):
            rank[j] = pos
        pairs = game.pairs(recs0, rank)
        info = {"edges": pinfo["edges"], "sc": float(best), "sc_seed": float(sc_seed), "generations": len(history) - 1,
                "regret_selfish": self.selfish_regret(genes, internal0, pairs)}
        return list(genes), rank, info
