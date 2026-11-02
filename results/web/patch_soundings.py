def patch(path, pairs):
    s = open(path, encoding="utf-8").read()
    for a, b in pairs:
        assert a in s, (path, a[:70])
        s = s.replace(a, b, 1)
    open(path, "w", encoding="utf-8").write(s)


patch("src/environment/antwerp_port.py", [
('''    build_berth_catalogue(graph, berths, berth_nodes, berth_zone, berth_use())
    apply_berth_data(graph)''',
 '''    apply_port_soundings(graph)
    build_berth_catalogue(graph, berths, berth_nodes, berth_zone, berth_use())
    apply_berth_data(graph)'''),
('''DEFAULT_BERTH_UKC_M = 0.5            # when the harbour master gives no minimum UKC''',
 '''DEFAULT_BERTH_UKC_M = 0.5            # when the harbour master gives no minimum UKC
# the port's sounded bed levels (src/environment/fetch_port_soundings.py): docks and Zeeschelde
PORT_SOUNDINGS = PROJECT_ROOT / "data" / "charts" / "antwerp_port_soundings_taw.tif"
SOUNDING_HALF_WINDOW_M = 25.0        # a cell's depth: the median bed level within this of its centre
SOUNDING_MIN_VALID = 0.3             # ... where at least this share of those pixels has a sounding'''),
('''def _mean_high_water(model, days=30):''', '''def apply_port_soundings(graph):
    """Measured depths for every cell the port's sounding raster covers (docks, Zeeschelde): the
    median bed level within SOUNDING_HALF_WINDOW_M of the cell centre (m TAW), as a depth below LAT
    at the cell's gauge. Replaces the nominal and charted depths there (depth_source
    "port_sounding"); edges touching such a cell get the shallower of their two cells."""
    import rasterio

    from tide import TideModel

    if not PORT_SOUNDINGS.is_file():
        log.warning("%s missing: run src/environment/fetch_port_soundings.py", PORT_SOUNDINGS)
        return
    model = TideModel.load()
    nodes = graph.nodes
    ids = np.array([n for n, d in graph.nodes(data=True) if d["type"] not in ("lock", "anchorage", "approach")])
    to_bl = Transformer.from_crs(PROJECTED_CRS, "EPSG:31370", always_xy=True).transform
    bx, by = to_bl(np.array([nodes[n]["x"] for n in ids]), np.array([nodes[n]["y"] for n in ids]))
    with rasterio.open(PORT_SOUNDINGS) as src:
        bed = src.read(1).astype(np.float32)
        nodata, inv = src.nodata, ~src.transform
        res = src.res[0]
    bed[(bed == nodata) | ~np.isfinite(bed)] = np.nan
    cols, rows = inv * (bx, by)
    rows, cols = np.floor(rows).astype(int), np.floor(cols).astype(int)
    k = int(round(SOUNDING_HALF_WINDOW_M / res))
    inside = (rows >= k) & (rows < bed.shape[0] - k) & (cols >= k) & (cols < bed.shape[1] - k)
    off = np.arange(-k, k + 1)
    rr = rows[inside][:, None, None] + off[None, :, None]
    cc = cols[inside][:, None, None] + off[None, None, :]
    win = bed[rr, cc].reshape(int(inside.sum()), -1)
    valid = np.isfinite(win).mean(axis=1) >= SOUNDING_MIN_VALID
    med = np.full(len(win), np.nan)
    med[valid] = np.nanmedian(win[valid], axis=1)
    changed = {}
    for n, b in zip(ids[inside][valid], med[valid]):
        d = nodes[n]
        gauge = d.get("tide_gauge") or "antwerpen.loodsgebouw"
        depth = round(float(model.taw_to_lat_depth(-b, gauge)), 2)
        changed[int(n)] = (d["depth_m"], depth)
        d.update(depth_m=depth, depth_source="port_sounding", drying=depth < 0)
    for n in changed:
        for m in graph[n]:
            if nodes[m]["type"] in ("lock", "anchorage", "approach"):
                continue
            graph.edges[n, m]["depth_m"] = round(min(nodes[n]["depth_m"], nodes[m]["depth_m"]), 2)
    diff = np.array([new - old for old, new in changed.values()])
    graph.graph.setdefault("sources", {})["port_soundings"] = str(PORT_SOUNDINGS.relative_to(PROJECT_ROOT))
    graph.graph["port_soundings"] = {"cells": len(changed), "median_change_m": round(float(np.median(diff)), 2) if len(diff) else None}
    log.info("port soundings: %d cells get measured depths (change: median %+.1f m, p10 %+.1f, p90 %+.1f)",
             len(changed), np.median(diff), np.percentile(diff, 10), np.percentile(diff, 90))


def _mean_high_water(model, days=30):'''),
# berth cells: the cell soundings win where they exist
('''        lat_depth = round(model.taw_to_lat_depth(-taw, gauge), 2)
        b["depth_m"] = lat_depth
        for n in b["nodes"]:
            official[n] = max(official.get(n, -99.0), lat_depth)''',
 '''        lat_depth = round(model.taw_to_lat_depth(-taw, gauge), 2)
        b["berth_sounding_m"] = lat_depth
        for n in b["nodes"]:
            if nodes[n]["depth_source"] != "port_sounding":    # the cell's own soundings are better
                official[n] = max(official.get(n, -99.0), lat_depth)'''),
])
print("patched")
