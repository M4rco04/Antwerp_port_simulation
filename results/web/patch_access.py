def patch(path, pairs):
    s = open(path, encoding="utf-8").read()
    for a, b in pairs:
        assert a in s, (path, a[:70])
        s = s.replace(a, b, 1)
    open(path, "w", encoding="utf-8").write(s)


patch("src/environment/antwerp_port.py", [
# Zeebrugge berths are not part of the model
('''    berths = gpd.read_file(SLOT_DATA).to_crs(PROJECTED_CRS)
    berths["LPL"] = berths.LPL.astype(str)
''', '''    berths = gpd.read_file(SLOT_DATA).to_crs(PROJECTED_CRS)
    berths = berths[~berths.LPL_UN.astype(str).str.startswith("ZEEBR")].copy()     # Zeebrugge: outside the model
    berths["LPL"] = berths.LPL.astype(str)
'''),
# step 2 and 3: one widest-path search per draught class, through locks deep enough for it
('''    # 2. widest-path tree from the main channel
    skip = {n for n, d in graph.nodes(data=True) if d["type"] in ("anchorage", "approach")}
    river = [n for n, d in graph.nodes(data=True) if d["region"] == "river"]
    source = max(river, key=lambda n: nodes[n]["depth_m"])

    def capacity(u, v):
        e = graph.edges[u, v]["depth_m"]
        if nodes[u]["type"] == "lock":
            return e + lv[v]
        if nodes[v]["type"] == "lock":
            return e + lv[u]
        return e + min(lv[u], lv[v])

    best, parent = {source: float("inf")}, {}
    heap, done = [(-float("inf"), source)], set()
    while heap:
        negw, n = heapq.heappop(heap)
        if n in done:
            continue
        done.add(n)
        for m in graph[n]:
            if m in done or m in skip:
                continue
            w = min(-negw, capacity(n, m))
            if w > best.get(m, -float("inf")):
                best[m], parent[m] = w, n
                heapq.heappush(heap, (-w, m))

    # 3. deepen the way to every berth that cannot be reached at its allowed draught
    stats = {"ok": 0, "deepened": 0, "lock_limited": 0, "no_draught": 0, "no_nodes": 0}
    cells_changed = set()
    for b in berths.values():
        d = b.get("max_draught_m")
        if not b["nodes"]:
            b["access"] = "no_nodes"
            stats["no_nodes"] += 1
            continue
        if d is None:
            b["access"] = "no_draught"
            stats["no_draught"] += 1
            continue
        need = d + (b.get("min_ukc_m") or DEFAULT_BERTH_UKC_M)
        b["need_m"] = round(need, 2)
        for n in b["nodes"]:                                   # the berth itself holds the ship
            if nodes[n]["depth_m"] + lv[n] < need:
                nodes[n].update(depth_m=round(need - lv[n], 2), depth_source="berth_access", drying=False)
                cells_changed.add(n)
        target = b["nodes"][len(b["nodes"]) // 2]
        if best.get(target, -float("inf")) >= need - 1e-6:
            b["access"] = "ok"
            stats["ok"] += 1
            continue
        limited, n = False, target
        while n != source and n in parent:
            p = parent[n]
            if capacity(p, n) < need - 1e-6:
                if nodes[p]["type"] == "lock" or nodes[n]["type"] == "lock":
                    limited = True
                else:
                    for m in (p, n):
                        if nodes[m]["depth_m"] + lv[m] < need:
                            nodes[m].update(depth_m=round(need - lv[m], 2), depth_source="berth_access", drying=False)
                            cells_changed.add(m)
                    graph.edges[p, n]["depth_m"] = round(need - min(lv[p], lv[n]), 2)
            n = p
        b["access"] = "lock_limited" if limited else "deepened"
        stats[b["access"]] += 1''',
'''    # 2. + 3. per draught class (deepest first): the deepest way to the berths through locks deep
    # enough for that draught (a lock cannot be dredged, the docks behind it can), then deepen the
    # cells and edges on that way that are too shallow
    skip = {n for n, d in graph.nodes(data=True) if d["type"] in ("anchorage", "approach")}
    river = [n for n, d in graph.nodes(data=True) if d["region"] == "river"]
    source = max(river, key=lambda n: nodes[n]["depth_m"])

    def lock_capacity(u, v):
        """A lock passage: its deepest chamber's sill plus the level on the water side."""
        lock_node, water = (u, v) if nodes[u]["type"] == "lock" else (v, u)
        return nodes[lock_node]["lock"].max_sill_depth_m + lv[water]

    def capacity(u, v):
        if nodes[u]["type"] == "lock" or nodes[v]["type"] == "lock":
            return lock_capacity(u, v)
        return graph.edges[u, v]["depth_m"] + min(lv[u], lv[v])

    def deepen(n, need):
        depth = math.ceil((need - lv[n]) * 100 + 1) / 100            # rounded up, 1 cm margin
        if nodes[n]["depth_m"] < depth:
            nodes[n].update(depth_m=depth, depth_source="berth_access", drying=False)
            cells_changed.add(n)

    def widest(need):
        best, parent = {source: float("inf")}, {}
        heap, done = [(-float("inf"), source)], set()
        while heap:
            negw, n = heapq.heappop(heap)
            if n in done:
                continue
            done.add(n)
            for m in graph[n]:
                if m in done or m in skip:
                    continue
                if (nodes[n]["type"] == "lock" or nodes[m]["type"] == "lock") and lock_capacity(n, m) < need:
                    continue                                          # this lock cannot take the ship
                w = min(-negw, capacity(n, m))
                if w > best.get(m, -float("inf")):
                    best[m], parent[m] = w, n
                    heapq.heappush(heap, (-w, m))
        return best, parent

    stats = {"ok": 0, "deepened": 0, "lock_limited": 0, "no_draught": 0, "no_nodes": 0}
    cells_changed = set()
    groups = {}
    for bid, b in berths.items():
        if not b["nodes"]:
            b["access"] = "no_nodes"
            stats["no_nodes"] += 1
        elif b.get("max_draught_m") is None:
            b["access"] = "no_draught"
            stats["no_draught"] += 1
        else:
            need = b["max_draught_m"] + (b.get("min_ukc_m") or DEFAULT_BERTH_UKC_M)
            b["need_m"] = round(need, 2)
            groups.setdefault(math.ceil(need * 10) / 10, []).append(bid)   # 10 cm draught classes
    for need in sorted(groups, reverse=True):
        best, parent = widest(need)
        for bid in groups[need]:
            b = berths[bid]
            for n in b["nodes"]:                                   # the berth itself holds the ship
                deepen(n, need)
            target = b["nodes"][len(b["nodes"]) // 2]
            if target not in parent and target != source:
                b["access"] = "lock_limited"                        # only through a lock too shallow for it
                stats["lock_limited"] += 1
                continue
            if best.get(target, -float("inf")) >= need:
                b["access"] = "ok"
                stats["ok"] += 1
                continue
            n = target
            while n != source:
                p = parent[n]
                if capacity(p, n) < need and nodes[p]["type"] != "lock" and nodes[n]["type"] != "lock":
                    deepen(p, need)
                    deepen(n, need)
                    graph.edges[p, n]["depth_m"] = math.ceil((need - min(lv[p], lv[n])) * 100 + 1) / 100
                n = p
            b["access"] = "deepened"
            stats["deepened"] += 1'''),
])
print("patched")
