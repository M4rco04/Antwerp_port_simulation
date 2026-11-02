# Antwerp Port Simulation

The model itself (its mathematics, every mechanic, and what is taken from each dataset) is described,
independent of the code, in [docs/MODEL.md](docs/MODEL.md).

## Viewing a run

`src/viz/build_viewer.py` turns a run folder into one self-contained page (`<run>/viewer.html`; open it
in a browser, no server needed, internet for the map tiles and chart library):

```
py src/sim/engine.py --days 7 --out results/my_run
py src/viz/build_viewer.py results/my_run --open
```

- **Live:** the ships on the map, animated (play / pause, speed, time slider; space and the arrow
  keys work too), coloured by activity or kind of ship, with anchorages, locks, terminals, pilot
  points and the simulation mesh as layers. The charts beside it (ships by activity, pilots on duty,
  tugs / pilot boats / boatmen, wind, visibility) follow the playhead; click one to jump there. Click
  a ship for its track, its state timeline and every event it logged.
- **Live depth:** the water over every cell at the playhead (charted depth below LAT + the water level
  there, or the basin level behind the locks), coloured by depth class; optionally the water too shallow
  for a chosen draught (+10 % under-keel clearance) in red, and the depth of a cell on hover. Runs save
  their gauge levels (`levels.csv.gz`, tide + surge); for older runs the viewer uses the astronomical tide.
- **Analysis:** time in the area by phase and class, container delays against the schedule, why ships
  waited for VTS clearance, lock passages, traffic-rule events, free quay at the container terminals,
  and a searchable, sortable table of all ships (click a row to see that ship on the map).

Runs saved before the summary recorded the warm-up need `--warmup <days>`.

## Live AIS data

`src/data/ais_collector.py` streams ship positions from [aisstream.io](https://aisstream.io) for the
Scheldt approach (51 23.33N 002 31.03E, 51 43.08N 002 36.68E, 51 28.02N 004 17.98E, 51 10.81N 004 26.03E).
Every 5 minutes it writes a snapshot to `data/ais/<date>/<time>Z.json` (plus `data/ais/latest.json`)
and commits + pushes it.

```
pip install -r requirements.txt
echo AISSTREAM_API_KEY=your-key > .env              # .env is gitignored
py src/data/ais_collector.py --once --no-push       # 60 s test run, no git
py src/data/ais_collector.py                        # run forever, push every 5 min
```

## Schedules with TEU data

`data/schedules` contains csv files with data regarding Vessel, TEU, Voyage, Arrival, Departure, Terminal.

A TEU (Twenty-foot Equivalent Unit) is the standard international unit used to measure shipping container capacity and cargo volume, based on a metal intermodal container that is 20 feet long (6.1 meters).

- Dimensions: A standard 20-foot TEU container measures roughly 20 feet long, 8 feet wide, and 8.5 to 9.5 feet tall.
- Capacity Equivalents:
	- 1 standard 20-foot container = 1 TEU
	- 1 standard 40-foot container = 2 TEUs (also called an FEU, or Forty-foot Equivalent Unit)
## Entry probabilities from AIS

`src/data/fit_entry_probabilities.py` reads all snapshots in `data/ais/`, classifies the ships
(container, bulk/general, tanker, inland cargo, inland tanker, passenger, service, unknown) and finds
where each visit entered: open sea (west / north / south-west edge), an anchorage (Westhinder,
Everingen, ...) or a port/canal feeding the Scheldt (Antwerp docks, Albert Canal, Upper Sea Scheldt,
Schelde-Rijn canal, Hansweert, Terneuzen, Ghent canal, Vlissingen, Breskens). It writes the fitted
tables to `src/data/entry_probabilities.py`; re-run it when more AIS data is in.

```
py src/data/fit_entry_probabilities.py --plot entries.png
```

```python
import entry_probabilities as E
E.p_source("container")                  # P(source | class), Scheldt-bound traffic
E.p_category("tanker")                   # P(sea / anchorage / port_channel / non_scheldt | class)
E.arrival_rate("inland_cargo", "albert_canal", hour=14)   # entries per hour
E.sample_source("bulk_general", rng)     # rng: numpy Generator or random.Random
```

## Background traffic and container calls from AIS

Two more fits share the visit pipeline in `src/data/ais_pipeline.py` (visits, entries, stops at
berths and anchorages; Antwerp split by quay number from `slots_cords/`):

```
py src/data/fit_background_traffic.py   # -> src/data/background_traffic.py
py src/data/fit_container_calls.py      # -> src/data/container_calls.py
```

- `background_traffic.py`: whole ships to bootstrap (LOA, beam, draught, DG category), destination
  per class and entry source (origin-destination), exit after the berth stay, lognormal time at
  berth and at anchor (censoring-aware), anchorage choice, lock passage times.
- `container_calls.py`: TEU -> LOA / beam / draught power laws with correlated residuals, berth
  arrival/departure delay versus the schedule CSV, time from entering the area to berthing, and
  where each schedule terminal code berths.

```python
import background_traffic as B, container_calls as C
B.sample_destination("tanker", rng, source="sea_north")   # e.g. "antwerp_right_bank_docks"
B.sample_berth_dwell("inland_tanker", rng)                 # hours
C.dimensions_for_teu(14000, rng)                           # {"loa": ..., "beam": ..., "draught": ...}
C.sample_arrival_delay(rng)                                # hours late against the schedule
```


## Port Equipment

`data/equipment` contains csv files with data regarding the port equipment, such as pilots, tugs, etc.

### Tugs

`data/equipment/tugs.csv` contains the list of tugs operating in the port of Antwerp, with their name, IMO number, Bollard Pull (in tons), dimensions, and max draft. Data about some tugs is not publicly available for free, so some fields are left empty.

### MDK Pilotage

`data/equipment/pilots_mdk.csv`

The pilots of the Agency for Maritime Services and Coast (MDK in Dutch) bring the largest ships safely to and from the port. They are active in Bruges as well as in Antwerp, on the North Sea and on the Scheldt. The pilot comes on board via a fast boat or a helicopter.

### Brabo Group dock pilots

`data/equipment/pilots_brabo.csv`

Once you pass the lock in Antwerp, you can call on the Brabo Group dock pilots. These pilots have an excellent knowledge of the port regulations and the port infrastructure. They know the depth of the water, the channels and the moorings of pipelines.
## Navigation graph

`src/environment/antwerp_port.py` builds `cache/antwerp_scheldt_graph.pkl` (+ an HTML viewer):
a 250 x 250 m grid at sea (only where Scheldt-bound AIS traffic sails, plus anchorages),
a 200 x 50 m grid along the fairway centreline of the Western Scheldt / Zeeschelde and the
canals, and a 50 x 50 m grid in the ports. No edge crosses land. Nodes carry lon/lat, region,
zone and depth (m below LAT, negative = drying); edges carry length and their shallowest depth.

```
py src/environment/antwerp_port.py --no-browser      # ~3 min; --refresh-osm re-downloads OSM water
```

```python
from antwerp_port import find_route, nearest_node
path = find_route(G, nearest_node(G, 2.62, 51.42), G.graph["terminals"][0]["access_node"],
                  draught_m=14.0, ukc_m=0.5)      # never uses an edge shallower than 14.5 m
```

### Locks

Every lock is a single graph node (`type="lock"`) joined to both sides by `lock_gate` edges;
`G.graph["locks"]` maps a lock name to its node, and `G.nodes[n]["lock"]` is a
`src/environment/locks.py` `Lock` object holding the chambers (length x width, sill), the two
sides (zone, tidal or not, gate nodes), a queue per chamber, 2-D packing (LOA x beam, greedy
first fit, biggest at the front), the ULCV empty-chamber rule and the level-changing cycle
(PLAN.md §7). Load the pickle with `src/environment` on `sys.path`.

```python
lock = G.nodes[G.graph["locks"]["Berendrecht"]]["lock"]
lock.request(ShipRequest("MSC X", loa=366, beam=51, draught=14.0, from_side="b", container=True), now=0)
events = lock.step(now=0, dt=5, levels={"a": 4.3, "b": 4.5})   # water levels above datum, m
```

### Anchorages

Every anchorage is a single node (`type == "anchorage"`) whose `anchorage` attribute is an
`Anchorage` object (`src/environment/anchorages.py`); `graph.graph["anchorages"]` maps a name to its node.

- Comes from the chart polygons (Westhinder, Wielingen N/Z, Vlissingen Roads, Everingen A–E, Put van
  Terneuzen A–B, ...) plus Schaar van Ouden Doel (one Rijkswaterstaat point, 400 m radius). Oostdyck and
  Schouwenbank lie outside the graph and hang on a `virtual` edge.
- **Capacity:** anchor berths take one ship whose swing circle (LOA + 5 × depth of chain) fits their
  radius. Areas take ships while swing circles cover ≤ 55 % of the area; the first ship always fits.
  A ship lies on the free cell farthest from the others, deep enough at the current tide.
- **Queue:** `request_pilot()`, then `departure_queue()` orders by priority (distress, tide-dependent,
  ordered ahead, FCFS), then by pilot request time. `step(now)` reports ships over 24 h in the Western Scheldt.
- `choose_anchorage(pool, loa, draught, ...)` applies the type rules of regs §11.3 (dangerous goods with
  signals: Wielingen Noord only; tide-dependent T ≥ 14 m: Wielingen Zuid; ...).
- Routes never pass through an anchorage node, only start or end there.
- Not yet placed: Liefkenshoek, Meestoof, Oosterweel, Rede van Antwerpen (positions needed from the NtM).

### Coarse routing graph

`graph.graph["coarse"]` (`src/environment/coarse_graph.py`) is what the VTS plans on: 583 regions
(seeds every 4 km at sea, 2 km on the river and canals, 800 m in the docks, plus every lock, anchorage
and terminal) and about 1,000 edges. Each fine node has `coarse_node` (its region); each fine edge
across a border has `coarse_edge`, so a reservation on a coarse edge covers those cells.

```python
import coarse_graph as CG
C = graph.graph["coarse"]
cpath = CG.coarse_route(C, graph.nodes[a]["coarse_node"], graph.nodes[b]["coarse_node"],
                        draught_m, ukc_m, loa_m, beam_m, G=graph, level=water_level)
fine = CG.refine(graph, C, cpath, a, b, draught_m, ukc_m, loa_m, beam_m, water_level=water_level)
cache = CG.RouteCache(C, graph)      # coarse routes by (start, end, draught class, size class)
```

The coarse search is optimistic (`crossing_depth_m`: the deepest edge across a region border).
`refine` then finds the fine path inside the corridor of regions along the coarse route, and falls back
to the whole graph if the corridor is too shallow. On test routes it gives the same lengths, locks and
refusals as `find_route`. A coarse route takes about 2.5 ms (fine A* over the whole estuary takes 150–300 ms); a cached one about 30 µs.

### Cell attributes and traffic rules

`src/environment/navigation_rules.py` gives every node:
- `lane_offset_m` and `lane`: the signed distance from the estuary axis (canals: their centreline) and the
  lane number (50 m lanes). Positive is the right bank looking upstream, so starboard for an inbound ship.
- `fairway`, by area:

  | Area | How the fairway is defined |
  |---|---|
  | Western Scheldt | Inside the Rijkswaterstaat lateral buoys of the main fairway |
  | Zeeschelde | ±150 m of the axis (assumed; no buoy data) |
  | Vlissingen precautionary area | ±500 m (assumed) |
  | Sea | Hulls of the Wielingen, Oostgat and Sardijngeul buoys, plus the Belgian deep-water route and traffic lanes |
  | Canals | All cells |
  | Docks | None |
- `speed_zone`: `sea`, `river`, `canal` or `dock`. These are the legs of the JA22 planning speeds
  (`planning_speed_kn()`); the sea leg ends at Vlissingen.
- `speed_limit_kn`: none on the river (only "safe speed" applies there). No published dock limit was found,
  so it is the 95th percentile of sea-going ships under way in AIS: 8.8 kn in the right-bank docks,
  6.8 kn in the left-bank docks, 7.7 kn within 600 m of a lock (`lock_precaution` cells, HPV 8.3.6).
- `main_waterway`: `right_bank` (kanaaldok B3 past Zandvliet/Berendrecht, B2, B1, Hansadok, 5th Havendok,
  Amerikadok, Albertdok) or `left_bank` (Verrebroekdok, Waaslandkanaal to Kallo), regs §2.5. Each is traced
  through the dock basin, ±100 m. `dock_priority(a, b)` gives the right of way:
  1. a ship not under command;
  2. a dock-oversized ship (two oversized ships follow the standard rules);
  3. a ship on the main waterway, over one coming out of a side dock or a lock.
- `stretches`: the regulated stretches (regs §6) the cell lies in: Sardijngeul, Vlissingen Roads,
  Pas van Borssele, Walsoorden harbour mouth, Nauw and Bocht van Bath, buoy 35 to CP.
  `encounter_conflicts(stretches, a, b, "meet" | "overtake")` names the rules that forbid an encounter;
  `min_spacing_m()` gives the 3 nm rule.
  - **Limits set by charted buoys:** Pas van Borssele (buoys 9–15, around buoy 13), Nauw van Bath (66–77, around
    buoy 75) and Bocht van Bath (77–83). The regulations name these stretches but give no limits, so the end buoys are my choice.
  - **Still approximate:** Vlissingen Roads and the Walsoorden harbour mouth (±1 km).

### Places, sources and destinations

`graph.graph["places"]` (`src/environment/places.py`):
- every entry source of `entry_probabilities.py`, snapped to a node; exits use the same node;
- virtual `approach` nodes beyond the three sea gates (virtual arrival);
- the Wandelaar and Steenbank pilot stations (Steenbank approximate);
- pilot changes at Vlissingen and at every lock;
- 15 tug bases and 7 pilot-boat bases from AIS;
- reference points: CP, buoy 35, De Nolle–Nieuwe Sluis, Antwerp Roads.

`graph.graph["destinations"]` maps every destination of `background_traffic.py` to a node, plus, for the
Antwerp berth zones, the berths in them.

### Depths in the docks and the Zeeschelde

`py src/environment/fetch_port_soundings.py` downloads the port authority's sounded bed levels (`gepeilde_diepte`
ImageServer, m TAW, exported at 5 m) to `data/charts/antwerp_port_soundings_taw.tif`. Every cell the raster covers
takes the median bed level within 25 m of its centre, converted to depth below LAT at its gauge (depth_source
`port_sounding`, about 10,300 cells). This replaces the nominal dock and Zeeschelde depths. Those were a median
1.7 m too deep, and up to 10 m in places. A check against the raster at random cells: median difference 0.01 m,
96 % within 1 m.

Depth sources of the water cells after a build:

| Source | Cells | Where |
|---|---|---|
| `chart_LAT` | ~46,200 | sea and Dutch Western Scheldt (Rijkswaterstaat 20 m / EMODnet) |
| `port_sounding` | ~10,300 | Antwerp docks and Zeeschelde (port soundings) |
| `nominal` | ~6,900 | canals, Dutch ports (Vlissingen, Terneuzen), corners outside the soundings |
| `berth_sounding` | ~140 | berth cells without a cell sounding: the harbour master's berth value |
| `berth_access` | ~80 | deepened so a berth's permitted draught can get in: median 1.9 m (max 6.3 m) deeper than the measured bed |
| `lock_approach` | 35 | Hansweert, Walcheren and Terneuzen approaches, which the chart shows as drying: unmeasured, to replace with real data |

Lock chambers in the berth layer (type `Sluis`) are not treated as berths.

### Berth data from the harbour master

`py src/environment/fetch_berth_data.py` downloads the Port of Antwerp-Bruges harbour master's berth layer
(`havenmeesterkaart` MapServer, layer 58) to `data/berths/havenmeester_ligplaatsen.geojson`. The graph builder
uses it as its berth source; Zeebrugge berths are left out, and `slots_cords/` remains only as a fallback.

- **What each berth gets:** permitted draught, sounded and design depth (m TAW), minimum UKC, maximum ship
  length / beam, berth category (sea-going / inland), quay and berth type, mooring side and swing time.
- **Tankers:** the official tanker quays replace the AIS guess.
- **Depth:** berth cells take their sounded depth, converted from TAW to LAT at the nearest gauge.
- **Access guarantee:** for every 10 cm draught class, the builder finds the deepest way from the main channel
  to each berth. It counts the fixed level in the docks, mean high water on tidal water, and only locks deep
  enough for that draught. Wherever that way is shallower than the permitted draught + UKC, it is deepened to
  exactly that (depth_source `berth_access`). Locks are never deepened.
  Last build: 676 berths reachable as charted, 28 needed deepening (420 cells).
- **Simulation:** a ship fits a berth when its draught is within the permitted draught, its category and size
  are allowed, and tankers use only tanker quays.

`py src/environment/check_berth_access.py` checks the guarantee independently with the simulation's router.
Last run: all 704 berths with a permitted draught and graph cells are reachable at that draught.

### Terminals and berths

- **`graph.graph["berths"]`**: all 914 charted berth slots, each with:
  - size: length, width and size class (seagoing, inland, small craft);
  - quay edge and graph nodes;
  - depth, and whether it is tidal or behind a lock;
  - zone;
  - AIS calls per class, and whether it is a tanker berth (166; tankers may moor only there, regs §10.5).
- **`graph.graph["terminals"][i]["resource"]`**: a `Terminal` (`src/environment/terminals.py`), with:
  - a quay line built from the berth polygons;
  - first-fit placement along the quay, keeping a 22.5 m gap to neighbouring ships;
  - STS cranes, capped at floor(LOA/45) per ship and at 9 per ship at MPET;
  - handling time;
  - head-out mooring in Deurganckdok for ships over 210 m;
  - the tide window at Noordzee S901–S905 (regs §8.10).
- **Terminal codes:** MPET is quay code 1742 (east side of Deurganckdok) and DP World Antwerp Gateway is
  1700. The schedules show this; the earlier builder had them the other way round.
- **Mooring and unmooring times** come from AIS (`src/data/port_infrastructure.py`,
  `mooring_minutes(loa, kind, area)`).

### Arrays for the step loop

`cache/antwerp_scheldt_graph.arrays.npz` (`src/environment/fast_graph.py`) holds the graph as numpy arrays
(node fields and CSR adjacency):

```python
from fast_graph import FastGraph, PassabilityCache
fg = FastGraph.load(A.DEFAULT_OUTPUT.with_suffix(".arrays.npz"), graph).bind_tide(tide_model)
level = fg.levels(tide_model.levels(times))[k]          # every node, m above LAT
path = fg.route(a, b, draught_m, ukc_m, loa_m, beam_m, level=level)
fine = CG.refine(graph, C, cpath, a, b, draught_m, ukc_m, loa_m, beam_m, fast=fg, level=level)
```

- **Routing** follows the same rules as `find_route` and gives the same paths, but takes 20–110 ms instead of 0.5–3 s.
- **Water levels** at every node for 48 times take 16 ms.
- **Passability masks**: `PassabilityCache` keeps one per step and draught class.

### Tides and wind surge

```
py src/environment/fetch_tide_data.py   # 2 years of 10-min water levels (Rijkswaterstaat, 11 gauges
                                        # Westkapelle -> Antwerpen) + hourly KNMI wind/pressure (Vlissingen)
py src/environment/fit_tide.py          # -> data/tides/tide_model.pkl (~15 min)
py src/environment/antwerp_port.py --no-browser   # rebuild: tide gauges on the nodes, lock sills to LAT
```

`fit_tide.py` fits per gauge a harmonic tide (UTide, ~68 constituents incl. the shallow-water
overtides), the gauge's LAT (lowest of 19 years of predicted tide, so tide heights and chart depths
share a datum), and a surge model (water level minus tide explained by 48 h of wind stress and
air pressure, rest as AR(1) noise); plus an hourly wind Markov chain (Beaufort class x 8 directions)
to drive the surge in the simulation. `src/environment/tide.py` gives levels in m above LAT:

```python
from tide import TideModel, node_level, tidal_window
model = TideModel.load()
levels = model.levels(times, weather)            # per gauge: tide + surge (weather: hourly, or None)
weather = model.sample_weather("2026-11-01", 24 * 14, rng)
ok = tidal_window(G, path, model, departures, speed_kn=12, draught_m=15.5, ukc_m=1.55)
```

Tidal graph nodes interpolate between the two gauges either side of them (`tide` attribute);
basins behind locks keep a fixed level (`basin`, `tide.BASIN_LEVELS_NAP_M`).

### Tidal currents

`src/environment/currents.py` derives the along-river current from the tide by continuity: the flow
through a cross-section is the water needed to raise or lower everything upstream (wet surface x
dh/dt, from the graph's cells and the tide model), divided by the wet cross-section, plus the
tidal storage above Hoboken (Upper Sea Scheldt, Rupel), which fills with a lag behind Antwerp.
Calibration (`data/tides/current_calibration.json`):

- **Zeeschelde** (Bath to Hoboken): on the Flemish current atlas (`fit_currents_atlas.py`;
  Stroomatlas Zeeschelde, Flanders Hydraulics Research 2022, WL rapporten 18_085_1, SCALDIS model).
  `data/tides/zeeschelde_stroomatlas.csv` holds the fairway speed (95th percentile of the vectors)
  of every half-hourly map for spring and neap tides. One scale per atlas section
  (Prosperpolder–Boudewijnsluis, Boudewijnsluis–Antwerpen, Antwerpen–Hoboken), the storage above
  Hoboken (bounded by the area of that water, 5–25 km²) and its lag are fitted. The scales also
  correct the graph's cross-sections, which are too narrow up the river.
- **Western Scheldt**: on AIS (`fit_currents.py`: within each passage, speed over the ground vs the
  modelled current).
- **SOG response**: AIS also shows that in the Zeeschelde ships' speed over ground swings much less
  than the current (pilots take back part of a fair or foul tide); `fit_currents.py` measures the
  share (`sog_response`), and the simulation adds the current times that share to a ship's speed.

```
py src/environment/fit_currents_atlas.py                    # Zeeschelde from the atlas
py src/environment/fit_currents.py --plot currents.png      # then Western Scheldt + SOG response
```

```python
from currents import CurrentModel
field = CurrentModel(G, model).compute(times, weather)          # m/s per 500 m slice, + = flood
field.speed_over_ground(G, u, v, i_time, stw_kn=12)            # kn over the ground on edge u -> v
ok = tidal_window(G, path, model, departures, 12, 15.5, 1.55, currents=CurrentModel(G, model))
```

## Simulation and agents

`py src/sim/engine.py --days 14 --warmup 2 --seed 1` runs the time-stepped simulation (Δt = 5 min).
`py src/sim/engine.py --start "2027-01-04 00:00" --days 14 --containers nhpp --container-rate 1.2` runs with fitted container arrivals (+20 %).

- **Progress:** it logs a status line every `--progress-hours` simulated hours (default 2): ships in the area, finished,
  removed, sailing, blocked, at berth, at anchor, waiting for the VTS, lock queue, busy pilots and tugs, and seconds per
  simulated day.
- **Time limit:** it stops and saves after `--max-minutes` of wall-clock time (default 60); the summary then says
  `stopped_early`. A 7-day run takes about 10 minutes.

It writes `results/<run>/`:
- `events.csv`: every state change and rule event;
- `ships.csv`: one row per ship, with the minutes spent in each state;
- `timeseries.csv`: queues and the use of pilots, tugs, boatmen and quays;
- `positions.csv.gz`: ship positions every 15 min;
- `summary.json`.

`--no-delays` berths containers at their scheduled time; `--no-background` runs containers only.

### Agents (`src/agents/`)

| Module | What it does |
|---|---|
| `ship.py` | One `Ship` class for both levels. Derived flags from regs §2 (pilot, ULCV, marginal, tide-dependent, oversized by zone, IMO2 gas, boatmen, tugs needed). A state machine (sail → pilot station → VTS → anchorage / boarding → sailing → lock → mooring → berth → departure → exit) with timers. Minutes per state are kept for the KPIs. |
| `generator.py` | Containers replayed from the schedule (`--containers replay`, default): TEU gives dimensions, call size and cranes; the AIS schedule delay is optional; ships enter 8 h before berthing at a sea source. Or (`--containers nhpp`) a Poisson process fitted to the schedule: 9.8 calls/day × weekday factor × hour-of-day factor (Brussels time) × a daily gamma factor (shape 23.6) for the bunching of liner calls, each arrival one schedule line drawn at random (TEU, terminal, time at berth); `--container-rate` scales it, `--no-bunching` drops the daily factor; runs can lie outside the schedule's dates. A container's TEU-drawn draught is capped at what its terminal's quay allows. Background traffic is a non-homogeneous Poisson process per class and source, from `entry_probabilities`, with bootstrapped AIS ships and destinations.  Ships entering from or leaving to a canal behind a lock (Schelde-Rijn, Zuid-Beveland, Albert) are redrawn until they fit its largest chamber. |
| `movement.py` | Ships as hulls: a centre line along the route over the ship's length, with its real beam, so ships can be longer and wider than the cells. Two hulls must stay (B1 + B2) / 2 + 20 % of the wider beam apart, less what each can shift sideways inside its own lane ((lane − B) / 2). Two-phase moves are resolved by priority, checking the swept hull. Speed is the JA22 planning speed plus current, capped by the cell's limit. The encounter rules of regs §6 and the 3 nm spacing are applied. Blocked ships detour round the other hulls (head-on: the lower-ranked ship gives way); a deadlock with no detour is let through after an hour. |
| `vts.py` | The simple VTS: first come first served, tide-dependent ships first. A ship is cleared when its route exists, the tide holds along it leaving now and 60 min later, a pilot (two for the largest ships) and a pilot boat are free, and its berth or quay has room. Otherwise it is sent to an anchorage (regs §11). No reservations or optimisation yet. |
| `services.py` | Pools with fleet sizes from the repo: 42 tugs (`tugs.csv`) at the AIS tug bases, plus the tugs AIS saw at Vlissingen, Terneuzen and Zeebrugge; 8 pilot boats (`pilots_mdk.csv`); 42 boatmen crews (`pilots_brabo.csv`, the Brabo boats). The repo has no pilot count, so pilots per zone = 1.25 × the AIS peak demand (`PILOT_DEMAND`) × (1 + return time / time on board):
16 sea, 42 river, 21 dock. |

**Traffic rules in movement** (`movement.py`):
- **Right of way:**
  1. ships in distress;
  2. an oversized ship in a regulated stretch;
  3. in the docks, a dock-oversized ship, then the main waterway over side docks and lock exits (regs §2.5, §10.2);
  4. on the river, the fairway over ships crossing or entering it (regs §5.2);
  5. then the VTS order.
- **Overtaking:** refused where a regulated stretch bans it (Sardijngeul, IMO2, Walsoorden; regs §6). On the river, in the
  docks and canals it is allowed only on the other ship's port side (regs §5.4); detours keep off its starboard side.
  Refusals are logged as `overtake_denied`.
- **Two river pilots** for LOA ≥ 340 m or B ≥ 51 m, and for LOA ≥ 300 m or B ≥ 45 m on a voyage through a lock (regs §8.8).

**ULCVs** (container ships ≥ 350 m or ≥ 51 m wide; regs §8.9, §8.11, JA22):
- **Already applied:** 2 river pilots, 3 / 2 tugs, an exclusive lock chamber, the wind limits, and the encounter and
  3 nm rules.
- **Lock empty from CP:** when the VTS clears a ULCV through a lock, the deepest chamber that fits is reserved from its
  ETA at CP (or 1 h before the lock if its route does not pass CP). No other ship enters it from then on
  (`lock_reserved`).
- **Lock traffic held:** while a ULCV under way passes within 5 km of the river side of Zandvliet, Berendrecht,
  Terneuzen or Hansweert, ships leaving those locks towards the river wait inside (`held_for_ulcv`,
  `released_after_ulcv`).
- **Fallback berth:** a ULCV whose terminal has no suitable free quay goes to the first of Noordzee, Europa, MPET or
  DP World Gateway that has one (`fallback_berth`).

**Weather** (`src/environment/weather.py`, `src/agents/weather_gates.py`):
- **Source:** hourly wind, gusts, pressure and visibility. Each simulated day is a real KNMI Vlissingen day from the
  same season (block bootstrap); `--weather replay` uses the observed dates where the record covers them.
- **Surge:** the wind drives the tide model's surge, so storms change the water level.
- **Gates of regs §9, checked by the VTS before clearing a ship:**
  - visibility < 1,000 m: marginal ships don't start;
  - IMO2 gas tankers need 1,000 m at sea and 2,000 m on the river;
  - ULCV: > 5 Bft for a voyage through a lock; > 6 / > 7 Bft arriving / leaving a tidal terminal, holding until ETA + 3 h;
  - T ≥ 12.5 m may not leave Everingen / Put van Terneuzen at ≥ 7 Bft;
  - cruise ships at the locks: max 7 / 6 Bft by length.
- **Assumed thresholds** (the regulations give none):
  - all sea-going traffic stops at ≥ 9 Bft;
  - no pilot boarding at sea at ≥ 8 Bft, except ships shore-based pilotage can take (LOA ≤ 175 m, T ≤ 8 m);
  - speed at most 8 kn below 1,000 m visibility and 5 kn below 500 m;
  - STS cranes stop in gusts over 20 m/s;
  - one extra tug for ships ≥ 200 m at ≥ 6 Bft.

**Assumed values** to calibrate:
- the tug table by length (except the tanker and ULCV rules, which are from the regulations);
- pilot return times;
- boarding (20 min) and pilot change (10 min);
- inland speed 8 kn;
- dock speed 5 kn where no AIS limit exists;
- lock entry and exit times.

**Simplifications for now:**
- no STS buffer blocking;
- no weather gates;
- no reservation table;
- ships one cell wide;
- moored and lock-waiting ships are off the route cells;
- ports outside Antwerp (Vlissingen, Terneuzen) are a dwell without a berth model.

**Traffic handling:**
- Ships queuing for a lock or moored at a berth are off the route cells.
- **Passing:** whether two ships can pass follows from their beams and lane widths (see `movement.py`). Two barges pass in one 50 m lane; two ULCVs need two lanes between them.
- **Wide ships** are routed only over cells with room for half their beam on each side (`src/environment/clearance.py`, distance to the edge of the water). If no such route exists they take the narrow one, logged as `narrow_route`.
- **Deadlocks:** two ships in a head-on or crossing deadlock with no way round pass after an hour (logged as `squeeze_past`).
- A ship held by an encounter rule for an hour is let through (logged as `encounter_rule_overridden`).

**Infeasible voyages:**
- A ship too deep for the northern sea exit uses another sea exit.
- A deep arrival from the north boards at Wandelaar.
- A voyage impossible even at high water is removed and logged (`infeasible`; counted in the summary).
