import os
import pickle
import osmnx as ox
import geopandas as gpd
from shapely.geometry import Point
from shapely.prepared import prep
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
import networkx as nx
import math

bbox = (4.2200, 51.2100, 4.4500, 51.3800)
tags = {"natural": "water", "waterway": ["riverbank", "dock", "canal", "fairway"]}

water_gdf = ox.features_from_bbox(bbox=bbox, tags=tags)
water_proj = ox.projection.project_gdf(water_gdf)
water_geom = water_proj.unary_union
water_geom_prep = prep(water_geom)

G = nx.Graph()
step = 50
minx, miny, maxx, maxy = water_geom.bounds

x_coords = np.arange(minx, maxx, step)
y_coords = np.arange(miny, maxy, step)

grid_nodes = {} 
node_id = 0

for i, x in enumerate(x_coords):
    for j, y in enumerate(y_coords):
        if water_geom_prep.contains(Point(x, y)):
            G.add_node(node_id, x=x, y=y)
            grid_nodes[(i, j)] = node_id
            node_id += 1

directions = [
    (0, 1, 1), (0, -1, 1), (1, 0, 1), (-1, 0, 1),
    (1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)),
    (-1, 1, math.sqrt(2)), (-1, -1, math.sqrt(2))
]

for (i, j), current_node in grid_nodes.items():
    for di, dj, dist_mult in directions:
        neighbor_idx = (i + di, j + dj)
        if neighbor_idx in grid_nodes:
            neighbor_node = grid_nodes[neighbor_idx]
            weight = step * dist_mult
            G.add_edge(current_node, neighbor_node, weight=weight)

print(f"Stworzono relacje: |E| = {G.number_of_edges()} krawędzi.")

connected_components = list(nx.connected_components(G))
largest_cc = max(connected_components, key=len)
G = G.subgraph(largest_cc).copy()
print(f"|V| = {G.number_of_nodes()}, |E| = {G.number_of_edges()}")

lines = []
for u, v in G.edges():
    x1, y1 = G.nodes[u]['x'], G.nodes[u]['y']
    x2, y2 = G.nodes[v]['x'], G.nodes[v]['y']
    lines.append([(x1, y1), (x2, y2)])

lc = LineCollection(lines, colors="#0055ff", linewidths=0.5, alpha=0.5)

plt.figure(figsize=(12, 12), facecolor="#111111")
ax = plt.gca()
ax.set_facecolor("#111111")
ax.add_collection(lc)

water_x, water_y, lock_x, lock_y, unload_x, unload_y = [], [], [], [], [], []
for n, data in G.nodes(data=True):
    ntype = data.get('type', 'water')
    if ntype == 'lock':
        lock_x.append(data['x']); lock_y.append(data['y'])
    elif ntype == 'unloading':
        unload_x.append(data['x']); unload_y.append(data['y'])
    else:
        water_x.append(data['x']); water_y.append(data['y'])

ax.scatter(water_x, water_y, c="#00ffff", s=2, zorder=5, label='Woda')
if lock_x: ax.scatter(lock_x, lock_y, c="#ff00ff", s=12, zorder=6, label='Śluza')
if unload_x: ax.scatter(unload_x, unload_y, c="#ffff00", s=12, zorder=6, label='Rozładunek')

plt.legend(loc="upper right", facecolor="#222222", edgecolor="none", labelcolor="white")
plt.axis("equal")
plt.axis("off")
plt.tight_layout()
plt.show()
