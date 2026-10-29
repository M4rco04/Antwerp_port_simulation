"""Build a metric navigation graph for the Scheldt approach.

The depth raster is used as the authoritative water mask and depth source.
The graph is deliberately built in UTM 31N so that the requested spacing
and edge weights are expressed in metres.
"""

from __future__ import annotations

import argparse
import json
import math
import pickle
import webbrowser
from pathlib import Path
from typing import Iterator

import networkx as nx
import numpy as np
import rasterio
from pyproj import Transformer
from shapely import transform as shapely_transform
from shapely.geometry import LineString, Polygon, Point


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEPTH_RASTER = PROJECT_ROOT / "data" / "charts" / "scheldt_depth_LAT_wgs84.tif"
DEFAULT_OUTPUT = PROJECT_ROOT / "cache" / "antwerp_scheldt_graph.pkl"
DEFAULT_HTML = PROJECT_ROOT / "cache" / "antwerp_scheldt_graph.html"
ORIGINAL_PORT_GRAPH = PROJECT_ROOT / "port_graph.pkl"
SLOT_DATA = PROJECT_ROOT / "slots_cords" / "paczka_final.json"
PROJECTED_CRS = "EPSG:32631"
GEOGRAPHIC_CRS = "EPSG:4326"

SCHELDT_CENTERLINE = (
    (4.4000, 51.2500),
    (4.2500, 51.3900),
    (4.0500, 51.4400),
    (3.8500, 51.3500),
    (3.6000, 51.4300),
    (3.2500, 51.4300),
    (2.8500, 51.3900),
    (2.4500, 51.3000),
    (2.3000, 51.2500),
)

PORT_TERMINALS = (
    {
        "name": "MPET",
        "position": (4.265, 51.315),
        "quay_m": 3700,
        "draft_m": 17.0,
        "capacity": "9 ULCV / 12-14 mieszanych",
    },
    {
        "name": "DP World Antwerp Gateway",
        "position": (4.285, 51.315),
        "quay_m": 2500,
        "draft_m": 17.0,
        "capacity": "6 ULCV / 8-10 mieszanych",
    },
    {
        "name": "PSA Noordzee Terminal",
        "position": (4.365, 51.300),
        "quay_m": 1225,
        "draft_m": 17.0,
        "capacity": "3 ULCV",
    },
    {
        "name": "PSA Europa Terminal",
        "position": (4.385, 51.285),
        "quay_m": 1180,
        "draft_m": 16.0,
        "capacity": "2-3 duże statki",
    },
)


def _projected_centerline() -> LineString:
    to_projected = Transformer.from_crs(
        GEOGRAPHIC_CRS, PROJECTED_CRS, always_xy=True
    ).transform
    return shapely_transform(
        LineString(SCHELDT_CENTERLINE), to_projected, interleaved=False
    )


def _candidate_points(
    bounds: tuple[float, float, float, float],
    corridor: LineString,
    width_step_m: float,
    length_step_m: float,
) -> Iterator[tuple[int, int, float, float]]:
    min_x, min_y, max_x, max_y = bounds
    x_coords = np.arange(
        math.floor(min_x / width_step_m) * width_step_m,
        max_x + width_step_m,
        width_step_m,
    )
    y_coords = np.arange(
        math.floor(min_y / length_step_m) * length_step_m,
        max_y + length_step_m,
        length_step_m,
    )

    from shapely import contains_xy

    for y_index, y in enumerate(y_coords):
        inside = contains_xy(corridor, x_coords, y)
        for x_index in np.flatnonzero(inside):
            yield int(x_index), y_index, float(x_coords[x_index]), float(y)


def _sample_depths(
    raster: rasterio.DatasetReader,
    projected_points: list[tuple[float, float]],
) -> np.ndarray:
    to_geographic = Transformer.from_crs(
        PROJECTED_CRS, GEOGRAPHIC_CRS, always_xy=True
    )
    longitudes, latitudes = to_geographic.transform(
        [point[0] for point in projected_points],
        [point[1] for point in projected_points],
    )
    samples = list(raster.sample(zip(longitudes, latitudes), masked=True))
    values = np.empty(len(samples), dtype=np.float64)
    for index, sample in enumerate(samples):
        values[index] = np.nan if np.ma.is_masked(sample[0]) else float(sample[0])
    return values


def _merge_original_port_graph(graph: nx.Graph) -> nx.Graph:
    if not ORIGINAL_PORT_GRAPH.is_file():
        raise FileNotFoundError(f"Original port graph not found: {ORIGINAL_PORT_GRAPH}")
    
    original = pickle.loads(ORIGINAL_PORT_GRAPH.read_bytes())["graph"]
    
    # Redukcja gęstości grafu portu z zachowaniem poprawnej topologii!
    edge_lengths = [
        math.hypot(original.nodes[u]["x"] - original.nodes[v]["x"], original.nodes[u]["y"] - original.nodes[v]["y"])
        for u, v in original.edges()
    ]
    median_len = np.median(edge_lengths) if edge_lengths else 50.0
    target_spacing = median_len * 2.0
    
    new_port = nx.Graph()
    bucket_to_node = {} 
    node_to_kept = {}   
    
    for n, data in original.nodes(data=True):
        bx = round(data["x"] / target_spacing)
        by = round(data["y"] / target_spacing)
        if (bx, by) not in bucket_to_node:
            bucket_to_node[(bx, by)] = n
            new_port.add_node(n, **data)
        node_to_kept[n] = bucket_to_node[(bx, by)]
        
    # Odtwarzamy stare krawędzie na nowych, rzadszych wierzchołkach
    for u, v, data in original.edges(data=True):
        ku = node_to_kept.get(u)
        kv = node_to_kept.get(v)
        if ku is not None and kv is not None and ku != kv:
            dist = math.hypot(
                new_port.nodes[ku]["x"] - new_port.nodes[kv]["x"],
                new_port.nodes[ku]["y"] - new_port.nodes[kv]["y"]
            )
            new_port.add_edge(ku, kv, weight=dist)
                
    original = new_port
    
    # Czyszczenie węzłów rzecznych wewnątrz basenów portowych
    bucket_size = max(100.0, target_spacing)
    port_buckets: dict[tuple[int, int], list[dict]] = {}
    for _, data in original.nodes(data=True):
        key = (round(data["x"] / bucket_size), round(data["y"] / bucket_size))
        port_buckets.setdefault(key, []).append(data)
        
    nodes_to_remove = []
    for node, data in graph.nodes(data=True):
        x, y = data["x"], data["y"]
        key = (round(x / bucket_size), round(y / bucket_size))
        conflict = False
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                for p_data in port_buckets.get((key[0] + dx, key[1] + dy), []):
                    if math.hypot(p_data["x"] - x, p_data["y"] - y) < 300.0:
                        conflict = True
                        break
                if conflict: break
            if conflict: break
        if conflict:
            nodes_to_remove.append(node)
            
    graph.remove_nodes_from(nodes_to_remove)
    
    if len(graph) > 0:
        largest_component = max(nx.connected_components(graph), key=len)
        graph = graph.subgraph(largest_component).copy()

    # Dołączanie przefiltrowanego grafu portu do głównego grafu
    offset = max(graph.nodes, default=-1) + 1
    old_to_new = {node: offset + index for index, node in enumerate(original.nodes)}
    original_nodes = list(original.nodes(data=True))
    transformer = Transformer.from_crs(
        PROJECTED_CRS, GEOGRAPHIC_CRS, always_xy=True
    )
    
    for node, data in original_nodes:
        longitude, latitude = transformer.transform(data["x"], data["y"])
        graph.add_node(
            old_to_new[node],
            x=float(data["x"]),
            y=float(data["y"]),
            longitude=float(longitude),
            latitude=float(latitude),
            depth_m=None,
            zanurzenie_m=0.0,
            depth_datum="not_available",
            type=data.get("type", "port_water"),
            source="original_port_graph",
        )
    graph.add_edges_from(
        (old_to_new[u], old_to_new[v], data)
        for u, v, data in original.edges(data=True)
    )

    # Łączenie krawędzi portu i rzeki z płynną strefą przejściową
    river_bucket_size = 500.0
    river_buckets: dict[tuple[int, int], list[int]] = {}
    for node, data in graph.nodes(data=True):
        if data.get("source") == "original_port_graph":
            continue
        key = (round(data["x"] / river_bucket_size), round(data["y"] / river_bucket_size))
        river_buckets.setdefault(key, []).append(node)
        
    connection_pairs: list[tuple[float, int, int]] = []
    for node, data in original_nodes:
        x, y = data["x"], data["y"]
        key = (round(x / river_bucket_size), round(y / river_bucket_size))
        nearby = [
            river_node
            for dx in range(-3, 4)
            for dy in range(-3, 4)
            for river_node in river_buckets.get((key[0] + dx, key[1] + dy), [])
        ]
        if nearby:
            river_node = min(
                nearby,
                key=lambda candidate: math.hypot(
                    graph.nodes[candidate]["x"] - x,
                    graph.nodes[candidate]["y"] - y,
                ),
            )
            distance = math.hypot(
                graph.nodes[river_node]["x"] - x,
                graph.nodes[river_node]["y"] - y,
            )
            connection_pairs.append((distance, old_to_new[node], river_node))
            
    if not connection_pairs:
        raise ValueError("Could not connect the original port graph to the river graph.")
        
    connection_pairs.sort(key=lambda item: item[0])
    
    connected_port_nodes = set()
    river_node_counts = {}
    added_edges = 0
    next_new_node_id = max(graph.nodes) + 1 if graph.nodes else 0
    
    for dist, port_node, river_node in connection_pairs:
        if dist > 1200.0 and added_edges > 0:
            continue
            
        r_count = river_node_counts.get(river_node, 0)
        if port_node not in connected_port_nodes and r_count < 3:
            num_steps = int(dist / 150.0)
            
            if num_steps <= 1:
                graph.add_edge(port_node, river_node, weight=dist, connection="port_to_river")
            else:
                p_data = graph.nodes[port_node]
                r_data = graph.nodes[river_node]
                
                prev_node = port_node
                for step in range(1, num_steps):
                    fraction = (step / num_steps) ** 1.5 
                    
                    mid_x = p_data["x"] + (r_data["x"] - p_data["x"]) * fraction
                    mid_y = p_data["y"] + (r_data["y"] - p_data["y"]) * fraction
                    
                    mid_lon = p_data["longitude"] + (r_data["longitude"] - p_data["longitude"]) * fraction
                    mid_lat = p_data["latitude"] + (r_data["latitude"] - p_data["latitude"]) * fraction
                    
                    new_node = next_new_node_id
                    next_new_node_id += 1
                    
                    graph.add_node(
                        new_node,
                        x=mid_x,
                        y=mid_y,
                        longitude=mid_lon,
                        latitude=mid_lat,
                        depth_m=r_data.get("depth_m"),
                        zanurzenie_m=r_data.get("zanurzenie_m", 0.0),
                        type="transition_water",
                        source="generated_transition"
                    )
                    
                    step_dist = math.hypot(
                        graph.nodes[prev_node]["x"] - mid_x,
                        graph.nodes[prev_node]["y"] - mid_y
                    )
                    graph.add_edge(prev_node, new_node, weight=step_dist, connection="port_to_river_transition")
                    prev_node = new_node
                
                final_dist = math.hypot(
                    graph.nodes[prev_node]["x"] - r_data["x"],
                    graph.nodes[prev_node]["y"] - r_data["y"]
                )
                graph.add_edge(prev_node, river_node, weight=final_dist, connection="port_to_river_transition")

            connected_port_nodes.add(port_node)
            river_node_counts[river_node] = r_count + 1
            added_edges += 1
            
    if added_edges == 0 and connection_pairs:
        dist, port_node, river_node = connection_pairs[0]
        graph.add_edge(port_node, river_node, weight=dist, connection="port_to_river")
            
    return graph


def _integrate_terminals(graph: nx.Graph) -> nx.Graph:
    transformer = Transformer.from_crs(GEOGRAPHIC_CRS, PROJECTED_CRS, always_xy=True)
    start_id = max(graph.nodes) + 1 if graph.nodes else 0
    
    water_nodes = [n for n, d in graph.nodes(data=True) if d.get("type") in ("water", "port_water", "transition_water")]
    
    for index, terminal in enumerate(PORT_TERMINALS):
        lon, lat = terminal["position"]
        x, y = transformer.transform(lon, lat)
        node_id = start_id + index
        
        graph.add_node(
            node_id,
            type="terminal",
            name=terminal["name"],
            x=float(x),
            y=float(y),
            longitude=float(lon),
            latitude=float(lat),
            zanurzenie_m=float(terminal["draft_m"]),
            quay_m=terminal["quay_m"],
            capacity=terminal["capacity"],
            depth_m=None,
            depth_datum="not_applicable",
        )
        
        if water_nodes:
            distances = [
                (math.hypot(graph.nodes[n]["x"] - x, graph.nodes[n]["y"] - y), n)
                for n in water_nodes
            ]
            distances.sort(key=lambda item: item[0])
            
            added = 0
            for dist, n in distances:
                if dist < 1500.0 and added < 15:
                    graph.add_edge(node_id, n, weight=dist, connection="terminal_access")
                    added += 1
            
    for node, data in graph.nodes(data=True):
        if data.get("type") != "terminal":
            data["zanurzenie_m"] = float(data.get("depth_m")) if data.get("depth_m") is not None else 0.0
            
    return graph


def _tag_berth_nodes(graph: nx.Graph) -> nx.Graph:
    """Oznacza wierzchołki znajdujące się wewnątrz stanowisk (berths).
    Jeśli stanowisko jest puste (brak wierzchołków wewnątrz), generuje
    nowy wierzchołek w jego środku ciężkości i łączy z grafem."""
    for n, d in graph.nodes(data=True):
        d["is_berth"] = False

    if not SLOT_DATA.is_file():
        return graph

    with SLOT_DATA.open(encoding="utf-8") as file:
        slot_data = json.load(file)

    berth_polygons = []
    for feature in slot_data.get("features", []):
        geom = feature.get("geometry", {})
        if geom.get("type") == "Polygon":
            coords = geom.get("coordinates", [[]])[0]
            if len(coords) >= 3:
                berth_polygons.append(Polygon(coords))

    if not berth_polygons:
        return graph

    poly_has_nodes = {i: False for i in range(len(berth_polygons))}

    for n, data in graph.nodes(data=True):
        if "longitude" in data and "latitude" in data:
            pt = Point(data["longitude"], data["latitude"])
            for i, poly in enumerate(berth_polygons):
                if poly.contains(pt):
                    data["is_berth"] = True
                    poly_has_nodes[i] = True

    transformer = Transformer.from_crs(GEOGRAPHIC_CRS, PROJECTED_CRS, always_xy=True)
    new_node_id = max(graph.nodes) + 1 if graph.nodes else 0
    
    existing_nodes = list(graph.nodes(data=True))
    
    for i, has_node in poly_has_nodes.items():
        if not has_node:
            poly = berth_polygons[i]
            centroid = poly.centroid
            lon, lat = centroid.x, centroid.y
            x, y = transformer.transform(lon, lat)
            
            graph.add_node(
                new_node_id,
                x=float(x),
                y=float(y),
                longitude=float(lon),
                latitude=float(lat),
                depth_m=None,
                zanurzenie_m=0.0,
                depth_datum="not_applicable",
                type="berth_center",
                is_berth=True
            )
            
            distances = [
                (math.hypot(d["x"] - x, d["y"] - y), n)
                for n, d in existing_nodes if d.get("type") != "terminal"
            ]
            distances.sort(key=lambda item: item[0])
            
            for dist, n in distances[:3]:
                graph.add_edge(new_node_id, n, weight=dist, connection="berth_access")
                
            new_node_id += 1

    return graph


def build_graph(
    depth_raster: Path = DEPTH_RASTER,
    width_step_m: float = 500.0,  
    length_step_m: float = 500.0, 
    corridor_width_m: float = 5000.0,
) -> nx.Graph:
    if width_step_m <= 0 or length_step_m <= 0 or corridor_width_m <= 0:
        raise ValueError("Grid spacing and corridor width must be positive.")
    if not depth_raster.is_file():
        raise FileNotFoundError(f"Depth raster not found: {depth_raster}")

    corridor = _projected_centerline().buffer(corridor_width_m)
    to_projected = Transformer.from_crs(
        GEOGRAPHIC_CRS, PROJECTED_CRS, always_xy=True
    ).transform

    with rasterio.open(depth_raster) as raster:
        raster_bounds = tuple(
            value
            for value in shapely_transform(
                LineString(
                    [
                        (raster.bounds.left, raster.bounds.bottom),
                        (raster.bounds.right, raster.bounds.top),
                    ]
                ),
                to_projected,
                interleaved=False,
            ).bounds
        )
        bounds = corridor.bounds
        clipped_bounds = (
            max(bounds[0], raster_bounds[0]),
            max(bounds[1], raster_bounds[1]),
            min(bounds[2], raster_bounds[2]),
            min(bounds[3], raster_bounds[3]),
        )
        if clipped_bounds[0] >= clipped_bounds[2] or clipped_bounds[1] >= clipped_bounds[3]:
            raise ValueError("The Scheldt corridor does not overlap the depth raster.")

        candidates = list(
            _candidate_points(
                clipped_bounds, corridor, width_step_m, length_step_m
            )
        )
        depths = _sample_depths(
            raster, [(candidate[2], candidate[3]) for candidate in candidates]
        )

    to_geographic = Transformer.from_crs(
        PROJECTED_CRS, GEOGRAPHIC_CRS, always_xy=True
    )
    graph = nx.Graph()
    grid_nodes: dict[tuple[int, int], int] = {}

    for candidate, depth in zip(candidates, depths):
        if not np.isfinite(depth):
            continue
        x_index, y_index, x, y = candidate
        longitude, latitude = to_geographic.transform(x, y)
        node_id = len(grid_nodes)
        grid_nodes[(x_index, y_index)] = node_id
        graph.add_node(
            node_id,
            x=x,
            y=y,
            longitude=float(longitude),
            latitude=float(latitude),
            depth_m=float(depth),
            depth_datum="LAT",
            type="water",
        )

    directions = (
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1),           (0, 1),
        (1, -1),  (1, 0),  (1, 1),
    )
    for (x_index, y_index), node_id in grid_nodes.items():
        for dx, dy in directions:
            neighbour = grid_nodes.get((x_index + dx, y_index + dy))
            if neighbour is not None:
                graph.add_edge(
                    node_id,
                    neighbour,
                    weight=math.hypot(
                        dx * width_step_m, dy * length_step_m
                    ),
                )

    if not graph:
        raise ValueError("No water cells were found in the Scheldt corridor.")
        
    largest_component = max(nx.connected_components(graph), key=len)
    graph = graph.subgraph(largest_component).copy()
    graph = _merge_original_port_graph(graph)
    
    graph = _integrate_terminals(graph)
    graph = _tag_berth_nodes(graph)
    
    graph.graph.update(
        {
            "crs": PROJECTED_CRS,
            "coordinate_crs": GEOGRAPHIC_CRS,
            "depth_raster": str(depth_raster.relative_to(PROJECT_ROOT)),
            "depth_datum": "LAT",
            "grid_width_m": width_step_m,
            "grid_length_m": length_step_m,
            "corridor_width_m": corridor_width_m,
            "terminals": PORT_TERMINALS,
            "port_graph_source": str(ORIGINAL_PORT_GRAPH.relative_to(PROJECT_ROOT)),
        }
    )
    return graph


def save_graph(graph: nx.Graph, output: Path = DEFAULT_OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as file:
        pickle.dump({"graph": graph, "crs": PROJECTED_CRS}, file, protocol=pickle.HIGHEST_PROTOCOL)
    return output


def save_web_visualization(
    graph: nx.Graph, output: Path = DEFAULT_HTML, edge_stride: int = 1
) -> Path:
    if edge_stride < 1:
        raise ValueError("edge_stride must be positive.")
        
    edges_to_display = []
    nodes_to_display = set()
    
    for index, (u, v, data) in enumerate(graph.edges(data=True)):
        conn_type = data.get("connection")
        is_important = conn_type in ("terminal_access", "port_to_river", "port_to_river_transition", "berth_access")
        is_port_edge = graph.nodes[u].get("source") == "original_port_graph" and graph.nodes[v].get("source") == "original_port_graph"
        
        if is_important or is_port_edge or index % edge_stride == 0:
            edges_to_display.append((u, v))
            nodes_to_display.add(u)
            nodes_to_display.add(v)
            
    for node, data in graph.nodes(data=True):
        if data.get("type") == "terminal" or data.get("is_berth"):
            nodes_to_display.add(node)
            
    display_nodes: dict[int, int] = {}
    nodes: list[list[float | int | None | bool]] = []
    
    for node in nodes_to_display:
        data = graph.nodes[node]
        display_nodes[node] = len(nodes)
        is_port = data.get("source") == "original_port_graph" or data.get("type") == "terminal"
        nodes.append([
            data["longitude"], 
            data["latitude"],
            data.get("zanurzenie_m", data.get("depth_m")), 
            1 if is_port else 0,
            1 if data.get("is_berth") else 0
        ])
        
    edges: list[list[int]] = []
    for u, v in edges_to_display:
        edges.append([display_nodes[u], display_nodes[v]])
        
    berths = []
    if SLOT_DATA.is_file():
        with SLOT_DATA.open(encoding="utf-8") as file:
            slot_data = json.load(file)
        berths = [
            feature["geometry"]["coordinates"][0]
            for feature in slot_data.get("features", [])
            if feature.get("geometry", {}).get("type") == "Polygon"
        ]
        
    payload = json.dumps(
        {
            "nodes": nodes,
            "edges": edges,
            "berths": berths,
            "terminals": PORT_TERMINALS,
            "stats": {
                "nodes": graph.number_of_nodes(),
                "edges": graph.number_of_edges(),
                "display_nodes": len(nodes),
                "display_edges": len(edges),
            },
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )
    
    html = """<!doctype html>
<html lang="pl"><head><meta charset="utf-8">
<title>Graf portu Antwerpia i Skaldy</title>
<style>
html,body{margin:0;height:100%;overflow:hidden;background:#10141b;color:#e8eef5;font:14px system-ui}
canvas{display:block;width:100%;height:100%;cursor:grab} canvas.dragging{cursor:grabbing}
#info{position:fixed;left:12px;top:12px;background:#18212dcc;padding:10px 12px;border:1px solid #43546a;border-radius:6px;line-height:1.45}
#info b{color:#65d8ff} #legend{color:#ffb347}
</style></head><body><canvas id="map"></canvas><div id="info"></div>
<script>
const data=__PAYLOAD__, canvas=document.getElementById("map"), ctx=canvas.getContext("2d");
let scale=1, ox=0, oy=0, dragging=false, px=0, py=0;
const all=data.nodes;
let minLon = Infinity, maxLon = -Infinity, minLat = Infinity, maxLat = -Infinity;
for(let i=0; i<all.length; i++){
    if(all[i][0] < minLon) minLon = all[i][0];
    if(all[i][0] > maxLon) maxLon = all[i][0];
    if(all[i][1] < minLat) minLat = all[i][1];
    if(all[i][1] > maxLat) maxLat = all[i][1];
}
function resize(){canvas.width=innerWidth*devicePixelRatio;canvas.height=innerHeight*devicePixelRatio;ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);draw()}
function project(x,y){return [(x-minLon)/(maxLon-minLon)*innerWidth*scale+ox,(maxLat-y)/(maxLat-minLat)*innerHeight*scale+oy]}
function fit(){scale=Math.min(innerWidth/(maxLon-minLon)/111000*111000,innerHeight/(maxLat-minLat)/111000*111000);scale=0.95;ox=innerWidth*.025;oy=innerHeight*.025}
function draw(){ctx.clearRect(0,0,innerWidth,innerHeight);ctx.lineWidth=.45;ctx.strokeStyle="#4a8fbd88";ctx.beginPath();
 for(const e of data.edges){const a=project(all[e[0]][0],all[e[0]][1]),b=project(all[e[1]][0],all[e[1]][1]);ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1])}ctx.stroke();
 for(const ring of data.berths){ctx.strokeStyle="#ffad3d99";ctx.beginPath();ring.forEach((p,i)=>{const q=project(p[0],p[1]);i?ctx.lineTo(q[0],q[1]):ctx.moveTo(q[0],q[1])});ctx.closePath();ctx.stroke()}
 for(const n of all){
     const p=project(n[0],n[1]);
     if(n[4]){ ctx.fillStyle="#ffb347"; }
     else { ctx.fillStyle=n[3]?"#ff3b30":"#35c8e8"; }
     ctx.fillRect(p[0]-1,p[1]-1,n[3]||n[4]?3:1.5,n[3]||n[4]?3:1.5)
 }
 for(const t of data.terminals){const p=project(t.position[0],t.position[1]);ctx.fillStyle="#ff453a";ctx.beginPath();ctx.arc(p[0],p[1],5,0,Math.PI*2);ctx.fill();ctx.fillStyle="#fff";ctx.font="12px system-ui";ctx.fillText(t.name,p[0]+7,p[1]-22);ctx.font="10px system-ui";ctx.fillText(`Nabrzeże: ${t.quay_m} m | zanurzenie: ${t.draft_m} m`,p[0]+7,p[1]-9);ctx.fillText(`Pojemność: ${t.capacity}`,p[0]+7,p[1]+4)}
}
canvas.onwheel=e=>{e.preventDefault();const k=e.deltaY<0?1.15:.87;ox=e.offsetX-(e.offsetX-ox)*k;oy=e.offsetY-(e.offsetY-oy)*k;scale*=k;draw()};
canvas.onpointerdown=e=>{dragging=true;px=e.clientX;py=e.clientY;canvas.classList.add("dragging")};
canvas.onpointermove=e=>{if(dragging){ox+=e.clientX-px;oy+=e.clientY-py;px=e.clientX;py=e.clientY;draw()}};
canvas.onpointerup=canvas.onpointerleave=()=>{dragging=false;canvas.classList.remove("dragging")};
window.onresize=resize;fit();resize();
document.getElementById("info").innerHTML="<b>Graf portu Antwerpia i Skaldy</b><br>"+
`Węzły: ${data.stats.nodes.toLocaleString()} | Krawędzie: ${data.stats.edges.toLocaleString()}<br>`+
`Widok: ${data.stats.display_nodes.toLocaleString()} węzłów | ${data.stats.display_edges.toLocaleString()} krawędzi<br>`+
"<span id='legend'>Niebieski: rzeka i port | czerwony: terminale | pomarańczowy: stanowiska i ich węzły</span><br>Przeciągnij, użyj kółka myszy do powiększenia";
</script></body></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html.replace("__PAYLOAD__", payload), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Generate the HTML without opening a browser.",
    )
    args = parser.parse_args()

    graph = build_graph()
    output = save_graph(graph, args.output)
    html_output = save_web_visualization(graph, args.html)
    print(
        f"Stworzono graf: |V| = {graph.number_of_nodes()}, "
        f"|E| = {graph.number_of_edges()}. Zapisano w {output}\n"
        f"Wizualizacja HTML: {html_output}"
    )
    if not args.no_browser:
        webbrowser.open(html_output.resolve().as_uri())


if __name__ == "__main__":
    main()