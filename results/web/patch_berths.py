def patch(path, pairs):
    s = open(path, encoding="utf-8").read()
    for a, b in pairs:
        assert a in s, (path, a[:70])
        s = s.replace(a, b, 1)
    open(path, "w", encoding="utf-8").write(s)


# ---------------------------------------------------------------- builder
patch("src/environment/antwerp_port.py", [
('''SLOT_DATA = PROJECT_ROOT / "slots_cords" / "paczka_final.json"''',
 '''# berths: the harbour master's berth layer (src/environment/fetch_berth_data.py) with the allowed
# draught and depths per berth; the older slots_cords file (same berth ids, no depths) as a fallback
BERTH_DATA = PROJECT_ROOT / "data" / "berths" / "havenmeester_ligplaatsen.geojson"
SLOT_DATA = BERTH_DATA if BERTH_DATA.is_file() else PROJECT_ROOT / "slots_cords" / "paczka_final.json"
DEFAULT_BERTH_UKC_M = 0.5            # when the harbour master gives no minimum UKC'''),
('''def load_berths():
    berths = gpd.read_file(SLOT_DATA).to_crs(PROJECTED_CRS)
''',
 '''def load_berths():
    berths = gpd.read_file(SLOT_DATA).to_crs(PROJECTED_CRS)
    berths["LPL"] = berths.LPL.astype(str)
'''),
('''    build_berth_catalogue(graph, berths, berth_nodes, berth_zone, berth_use())
    build_terminals(graph)''',
 '''    build_berth_catalogue(graph, berths, berth_nodes, berth_zone, berth_use())
    apply_berth_data(graph)
    build_terminals(graph)'''),
('''def berth_zone(number):''', '''def _mean_high_water(model, days=30):
    """Mean high water (m above LAT) at every gauge over a month of predicted tide."""
    times = pd.date_range("2026-11-01", periods=int(days * 24 * 6), freq="10min", tz="UTC")
    out = {}
    for g in model.gauges:
        h = pd.Series(model.tide(g, times), index=times)
        out[g] = float(h.resample("745min").max().mean())        # one high water per 12 h 25 min
    return out


def apply_berth_data(graph):
    """Make the berths follow the harbour master's data and make every berth reachable.

    1. A berth's cells get its sounded depth (m TAW, converted to m below LAT at the nearest gauge).
    2. From the deepest cell of the main channel, the deepest way to every cell is found (one
       widest-path search: the path whose shallowest point is deepest), counting the water level a
       ship can expect: the fixed level in the docks, mean high water on tidal water, and at a lock
       its sill plus the level on the side the ship comes from.
    3. A berth whose way in is shallower than its allowed draught + minimum UKC gets that way
       deepened to exactly that (cells and edges marked depth_source "berth_access"). Locks are not
       deepened: a lock that limits a berth is reported (catalogue "access": "lock_limited").
    """
    import heapq

    from tide import TideModel

    berths = graph.graph["berths"]
    try:
        model = TideModel.load()
    except FileNotFoundError:
        log.warning("no tide model: berth depths and access not applied")
        return
    gauge_default = "antwerpen.loodsgebouw"
    mhw = _mean_high_water(model)
    nodes = graph.nodes

    def level(n):
        d = nodes[n]
        if d.get("tide") is not None:
            a, b, w = d["tide"]
            return (1 - w) * mhw[a] + w * mhw[b]
        if d.get("basin"):
            return model.basin_level_m(d["basin"], d.get("tide_gauge") or gauge_default)
        return 0.0

    lv = {n: level(n) for n in graph.nodes}

    # 1. sounded depths at the berths (overlapping berths: the deepest)
    official = {}
    for b in berths.values():
        taw = b.get("sounded_depth_taw_m")
        if taw is None or not b["nodes"]:
            continue
        gauge = nodes[b["nodes"][0]].get("tide_gauge") or gauge_default
        lat_depth = round(model.taw_to_lat_depth(-taw, gauge), 2)
        b["depth_m"] = lat_depth
        for n in b["nodes"]:
            official[n] = max(official.get(n, -99.0), lat_depth)
    for n, depth in official.items():
        nodes[n].update(depth_m=depth, depth_source="berth_sounding", drying=depth < 0)
    for n in official:
        for m in graph[n]:
            if m in official:
                graph.edges[n, m]["depth_m"] = round(min(official[n], official[m]), 2)

    # 2. widest-path tree from the main channel
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
        stats[b["access"]] += 1
    graph.graph["berth_access"] = {"stats": stats, "cells_deepened": len(cells_changed),
                                   "levels": "docks: fixed level; tidal: mean high water; locks: sill + level"}
    log.info("berths from the harbour master: %d with a sounded depth; access %s, %d cells deepened",
             sum(b.get("sounded_depth_taw_m") is not None for b in berths.values()), stats, len(cells_changed))


def berth_zone(number):'''),
])

# ---------------------------------------------------------------- catalogue
patch("src/environment/terminals.py", [
('''        u = use.get(row.LPL_UN)
        out[row.LPL_UN] = {''',
 '''        u = use.get(row.LPL_UN)
        hm = {k: _value(getattr(row, k, None)) for k in HARBOUR_MASTER_FIELDS}
        quay, kind = hm["quay_type"], hm["berth_type"] or ""
        official_tanker = None if quay is None and not kind else (quay == "Tanker" or "Tank" in kind or "Gas" in kind)
        out[row.LPL_UN] = {'''),
('''            "type_code": None if row.TYPE != row.TYPE else int(row.TYPE),''',
 '''            "type_code": _int(row.TYPE),'''),
('''            "tanker_berth": u["tanker_berth"] if u else None,
        }''',
 '''            # the harbour master's data (None where it gives none)
            **hm, "tanker_official": official_tanker,
            "tanker_berth": official_tanker if official_tanker is not None else (u["tanker_berth"] if u else None),
        }'''),
('''def build_berth_catalogue(graph, berths, berth_nodes, zone_of, use=None):''',
 '''HARBOUR_MASTER_FIELDS = ("max_draught_m", "sounded_depth_taw_m", "design_depth_taw_m", "min_ukc_m", "max_loa_m",
                         "max_beam_m", "max_moored_width_m", "max_moored_length_m", "mooring_side", "swing_min",
                         "berth_length_m", "category", "quay_type", "berth_type")


def _value(v):
    if v is None or (isinstance(v, float) and v != v):
        return None
    return v.item() if hasattr(v, "item") else v


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def build_berth_catalogue(graph, berths, berth_nodes, zone_of, use=None):'''),
('''    log.info("berth catalogue: %d berths (%d with nodes, %d tanker berths from AIS)", len(out),
             sum(bool(b["nodes"]) for b in out.values()), sum(bool(b["tanker_berth"]) for b in out.values()))''',
 '''    log.info("berth catalogue: %d berths (%d with nodes, %d with an allowed draught, %d tanker berths: %d official)",
             len(out), sum(bool(b["nodes"]) for b in out.values()),
             sum(b["max_draught_m"] is not None for b in out.values()), sum(bool(b["tanker_berth"]) for b in out.values()),
             sum(bool(b["tanker_official"]) for b in out.values()))'''),
('''"heading_deg": float(row.HOEK),''', '''"heading_deg": float(row.HOEK) if _value(row.HOEK) is not None else None,'''),
])
print("patched")
