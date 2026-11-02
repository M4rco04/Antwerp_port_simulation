def patch(path, pairs):
    s = open(path, encoding="utf-8").read()
    for a, b in pairs:
        assert a in s, (path, a[:70])
        s = s.replace(a, b, 1)
    open(path, "w", encoding="utf-8").write(s)


patch("src/sim/engine.py", [
# detours: round the other hulls
('''        k = mover._key(ship)
        avoid_set = set(avoid)
        while j > i + 1 and (mover.owner[ship.route[j]] not in (-1, k) or ship.route[j] in avoid_set):
            j -= 1
        if j <= i + 1:
            return
        rejoin = ship.route[j]
        near = np.hypot(fg.x - fg.x[here], fg.y - fg.y[here]) <= 1.2 * DETOUR_M
        mask = near & ((mover.owner == -1) | (mover.owner == k))''',
 '''        free = mover.free_mask(ship)                   # cells no other hull covers
        avoid_set = set(avoid)
        while j > i + 1 and (not free[ship.route[j]] or ship.route[j] in avoid_set):
            j -= 1
        if j <= i + 1:
            return
        rejoin = ship.route[j]
        near = np.hypot(fg.x - fg.x[here], fg.y - fg.y[here]) <= 1.2 * DETOUR_M
        mask = near & free'''),
('''        self._segment(ship)
        mover.place(ship)
        ship.blocked_steps = 0
        ship.note(self.t, "reroute")''',
 '''        self._segment(ship)
        if not mover.place(ship):
            ship.waiting_space = True
        ship.blocked_steps = 0
        ship.note(self.t, "reroute")'''),
# wide ships: only cells with room for their beam (else the narrow route, logged)
('''        import networkx as nx
        try:
            r = fg.route(start, target, ship.draught, ship.ukc_m, ship.loa, ship.beam, level=level, nodes_mask=mask,
                         keep_right=True)
        except nx.NetworkXNoPath:
            r = None''',
 '''        import networkx as nx
        r = None
        wide = ship.beam / 2 if ship.beam / 2 > MIN_CELL_CLEARANCE_M else None
        for clearance in ((wide, None) if wide else (None,)):
            try:
                r = fg.route(start, target, ship.draught, ship.ukc_m, ship.loa, ship.beam, level=level, nodes_mask=mask,
                             keep_right=True, min_clearance=clearance)
                if wide and clearance is None:
                    ship.note(self.t, "narrow_route", beam=ship.beam)    # no route with room for its beam
                break
            except nx.NetworkXNoPath:
                continue'''),
('''DETOUR_M = 3000.0''', '''DETOUR_M = 3000.0
MIN_CELL_CLEARANCE_M = 25.0            # every cell has at least this much water to each side (clearance.py)'''),
# the clearance of every cell, for routing wide ships
('''        self.fg = FastGraph.load(GRAPH.with_suffix(".arrays.npz"), self.graph)
        fg = self.fg''',
 '''        self.fg = FastGraph.load(GRAPH.with_suffix(".arrays.npz"), self.graph)
        fg = self.fg
        fg.clearance = node_clearance(fg)'''),
('''from fast_graph import FastGraph                          # noqa: E402''',
 '''from clearance import node_clearance                      # noqa: E402
from fast_graph import FastGraph                          # noqa: E402'''),
])

patch("src/agents/ship.py", [
('''    cells: list = field(default_factory=list)      # cells it occupies''',
 '''    cells: list = field(default_factory=list)      # route cells under its centre line (bow last)
    hull: list = field(default_factory=list)       # every cell its hull (beam + clearance) covers'''),
])
print("patched")
