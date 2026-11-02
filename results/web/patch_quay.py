def patch(path, pairs):
    s = open(path, encoding="utf-8").read()
    for a, b in pairs:
        assert a in s, (path, a[:70])
        s = s.replace(a, b, 1)
    open(path, "w", encoding="utf-8").write(s)


patch("src/environment/terminals.py", [
('''    def find_position(self, loa, near_s=None):
        """Quay metre where a ship of this length can lie (first fit, or the fit nearest near_s)."""
        fits = [(a, b) for a, b in self.free_intervals() if b - a >= loa]''',
 '''    def suitable_intervals(self, draught=None, sea_going=True):
        """Stretches of quay whose berth slots take this ship: sea-going slots (harbour master's
        category) allowing its draught; slots without data count as suitable."""
        spans = sorted((r["s0"], r["s1"]) for r in self.berths.values()
                       if (draught is None or r.get("max_draught") is None or r["max_draught"] >= draught)
                       and (not sea_going or r.get("category") in (None, "zeevaart")))
        out = []
        for a, b in spans:
            if out and a <= out[-1][1] + 1.0:
                out[-1] = (out[-1][0], max(out[-1][1], b))
            else:
                out.append((a, b))
        return out

    def find_position(self, loa, near_s=None, draught=None, sea_going=True):
        """Quay metre where a ship of this length can lie (first fit, or the fit nearest near_s):
        free quay that is also suitable for its draught and kind (suitable_intervals)."""
        free = self.free_intervals()
        if draught is not None or sea_going:
            ok = self.suitable_intervals(draught, sea_going)
            free = [(max(a, c), min(b, d)) for a, b in free for c, d in ok if min(b, d) > max(a, c)]
        fits = [(a, b) for a, b in free if b - a >= loa]'''),
('''            berths[b] = {"s0": round(s[0], 1), "s1": round(s[1], 1), "nodes": catalogue[b]["nodes"]}''',
 '''            berths[b] = {"s0": round(s[0], 1), "s1": round(s[1], 1), "nodes": catalogue[b]["nodes"],
                         "max_draught": catalogue[b].get("max_draught_m"), "category": catalogue[b].get("category")}'''),
])

patch("src/sim/engine.py", [
('''            s0 = T.find_position(ship.loa)''',
 '''            s0 = T.find_position(ship.loa, draught=ship.draught, sea_going=ship.sea_going)'''),
('''        self.terminals = {t["name"]: t["resource"] for t in self.graph.graph["terminals"]}''',
 '''        self.terminals = {t["name"]: t["resource"] for t in self.graph.graph["terminals"]}
        for T in self.terminals.values():              # the harbour master's limits of each quay slot
            for b, r in T.berths.items():
                r.setdefault("max_draught", self.graph.graph["berths"].get(b, {}).get("max_draught_m"))
                r.setdefault("category", self.graph.graph["berths"].get(b, {}).get("category"))'''),
])
print("patched")
