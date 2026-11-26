"""Solvers for the guidance games of the equilibrium strategies (docs/strategies/port_management_strategies.md §6, §6b).

A game here is a polymatrix game in cost form:

    players j = 0..n-1, each with m_j strategies
    internal[j]           array (m_j,): the cost to j of its own strategy alone (fuel, its own delay)
    pairs[(j, k)]         array (m_j, m_k): the extra cost to j of strategy pair (s_j, s_k), the externality k puts on j

The cost to j of a pure profile s is internal[j][s_j] + sum_k pairs[(j, k)][s_j, s_k]; the social cost is the sum over
players. A pure Nash equilibrium is a profile where no player lowers its own cost by changing its strategy alone.

- pulse_solve: the random-edge replicator dynamics of PULSE (Grgičević & Coates 2026, eq. 15) on payoffs scaled to
  [0, 1], then a best-response polish and a regret check.
- ga_solve: a genetic algorithm over pure profiles (and an order of precedence) that minimises a fitness, used by the
  evolutionary strategy to search for low social cost rather than for an equilibrium.
"""

from __future__ import annotations

import numpy as np


def internalise(pairs, lam):
    """Each player also counts lam times the cost it puts on the others (the VTS's non-monetary toll, §6.3)."""
    if lam == 0:
        return dict(pairs)
    out = {key: m.astype(float).copy() for key, m in pairs.items()}
    for (j, k), m in pairs.items():
        if (k, j) not in out:
            out[(k, j)] = np.zeros((m.shape[1], m.shape[0]))
        out[(k, j)] += lam * m.T          # what k's choice costs j, counted by k
    return out


def player_cost(j, a, profile, internal, nbrs):
    """Cost to player j of strategy a, the others playing `profile`."""
    c = internal[j][a]
    for k, m in nbrs[j]:
        c += m[a, profile[k]]
    return c


def neighbours(n, pairs):
    nb = [[] for _ in range(n)]
    for (j, k), m in pairs.items():
        nb[j].append((k, m))
    return nb


def social_cost(profile, internal, pairs):
    c = sum(internal[j][s] for j, s in enumerate(profile))
    for (j, k), m in pairs.items():
        c += m[profile[j], profile[k]]
    return float(c)


def best_response_polish(profile, internal, pairs, eps=1e-9, passes=20):
    """Let every player switch to its best response until none gains more than eps. Returns (profile, regret,
    settled): regret is the largest gain still open to one player, settled whether the passes ended in a PNE."""
    n = len(internal)
    nb = neighbours(n, pairs)
    profile = list(profile)
    for _ in range(passes):
        changed = False
        for j in range(n):
            costs = [player_cost(j, a, profile, internal, nb) for a in range(len(internal[j]))]
            a = int(np.argmin(costs))
            if costs[profile[j]] - costs[a] > eps:
                profile[j] = a
                changed = True
        if not changed:
            return profile, 0.0, True
    regret = 0.0
    for j in range(n):
        costs = [player_cost(j, a, profile, internal, nb) for a in range(len(internal[j]))]
        regret = max(regret, costs[profile[j]] - min(costs))
    return profile, regret, regret <= eps


def pulse_solve(internal, pairs, rng, iters=1000, polish=True):
    """PULSE: uniform mixed strategies, then `iters` updates on random edges, each a replicator step for both of its
    players on their two-player game (payoffs in [0, 1]: 1 - cost / the player's largest cost). Each player's own cost
    is split over its edges (a polymatrix game has no vertex term). Isolated players take their cheapest strategy.
    Returns (profile, info) with info {"regret", "settled", "edges", "replicator_profile"}."""
    n = len(internal)
    edges = sorted({tuple(sorted(key)) for key in pairs})
    deg = np.zeros(n, dtype=int)
    for j, k in edges:
        deg[j] += 1
        deg[k] += 1
    x = [np.full(len(internal[j]), 1.0 / len(internal[j])) for j in range(n)]

    def matrix(j, k):
        m = pairs.get((j, k))
        own = internal[j][:, None] / max(deg[j], 1)
        cost = own + (m if m is not None else 0.0)
        return np.broadcast_to(cost, (len(internal[j]), len(internal[k])))

    scale = np.ones(n)
    mats = {}
    for j, k in edges:
        for a, b in ((j, k), (k, j)):
            mats[(a, b)] = matrix(a, b)
            scale[a] = max(scale[a], float(np.max(mats[(a, b)])) if mats[(a, b)].size else 1.0)
    pay = {key: 1.0 - m / scale[key[0]] for key, m in mats.items()}
    if edges:
        picks = rng.integers(0, len(edges), size=iters)
        for e in picks:
            j, k = edges[e]
            fj, fk = pay[(j, k)], pay[(k, j)]
            gj, gk = fj @ x[k], fk @ x[j]
            xj = x[j] + x[j] * (gj - x[j] @ gj)
            xk = x[k] + x[k] * (gk - x[k] @ gk)
            x[j], x[k] = xj / xj.sum(), xk / xk.sum()
    profile = [int(np.argmax(x[j])) if deg[j] else int(np.argmin(internal[j])) for j in range(n)]
    info = {"edges": len(edges), "replicator_profile": list(profile)}
    if polish:
        profile, regret, settled = best_response_polish(profile, internal, pairs)
    else:
        nb = neighbours(n, pairs)
        regret = max((player_cost(j, profile[j], profile, internal, nb)
                      - min(player_cost(j, a, profile, internal, nb) for a in range(len(internal[j])))
                      for j in range(n)), default=0.0)
        settled = regret <= 1e-9
    info.update(regret=float(regret), settled=bool(settled))
    return profile, info


def order_crossover(p1, p2, rng):
    """OX: a slice of the first parent, the rest in the second parent's order."""
    n = len(p1)
    if n < 2:
        return list(p1)
    a, b = sorted(rng.choice(n, 2, replace=False))
    child = [None] * n
    child[a:b + 1] = p1[a:b + 1]
    fill = [g for g in p2 if g not in set(child[a:b + 1])]
    it = iter(fill)
    return [c if c is not None else next(it) for c in child]


def ga_solve(sizes, fitness, rng, seeds=(), pop=40, gens=30, p_mut=None, elite=2, tournament=3):
    """A genetic algorithm over (genes, order): genes[j] in range(sizes[j]) is player j's strategy, order a permutation
    of the players (their precedence). `fitness(genes, order)` is minimised. `seeds` are (genes, order) pairs put in
    the first population (an equilibrium, the defaults, last cycle's best). Returns (best genes, best order, best
    fitness, history of the best per generation)."""
    n = len(sizes)
    sizes = np.asarray(sizes, dtype=int)
    if n == 0:
        return [], [], float(fitness([], [])), []
    p_mut = p_mut if p_mut is not None else 1.0 / n

    def random_ind():
        return [int(rng.integers(0, s)) for s in sizes], [int(i) for i in rng.permutation(n)]

    popn = [(list(g), list(o)) for g, o in seeds][:pop]
    while len(popn) < pop:
        popn.append(random_ind())
    fit = [fitness(g, o) for g, o in popn]
    history = [min(fit)]

    def pick():
        idx = rng.choice(len(popn), size=min(tournament, len(popn)), replace=False)
        return popn[min(idx, key=lambda i: fit[i])]

    for _ in range(gens):
        ranked = sorted(range(len(popn)), key=lambda i: fit[i])
        new = [popn[i] for i in ranked[:elite]]
        while len(new) < pop:
            (g1, o1), (g2, o2) = pick(), pick()
            mask = rng.random(n) < 0.5
            g = [a if m else b for a, b, m in zip(g1, g2, mask)]
            o = order_crossover(o1, o2, rng)
            for j in range(n):
                if rng.random() < p_mut and sizes[j] > 1:
                    if rng.random() < 0.5:             # a step to a neighbouring level (a little faster, later, ...)
                        step = int(rng.choice((-1, 1)))
                        g[j] = int(min(max(g[j] + step, 0), sizes[j] - 1))
                    else:                              # or any level: lets a gene jump past its neighbours
                        g[j] = int(rng.integers(0, sizes[j]))
            if n > 1 and rng.random() < 0.3:
                a, b = rng.choice(n, 2, replace=False)
                o[a], o[b] = o[b], o[a]
            new.append((g, o))
        popn = new
        fit = [fitness(g, o) for g, o in popn]
        history.append(min(fit))
    best = int(np.argmin(fit))
    return popn[best][0], popn[best][1], float(fit[best]), history
