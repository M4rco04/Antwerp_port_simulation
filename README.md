# Antwerp Port Simulation


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
dh/dt, from the graph's cells and the tide model), divided by the wet cross-section. It is
calibrated on AIS (`fit_currents.py`: within each passage, speed over the ground vs the modelled
current) to `data/tides/current_calibration.json`.

```
py src/environment/fit_currents.py --plot currents.png      # needs the graph and tide_model.pkl
```

```python
from currents import CurrentModel
field = CurrentModel(G, model).compute(times, weather)          # m/s per 500 m slice, + = flood
field.speed_over_ground(G, u, v, i_time, stw_kn=12)            # kn over the ground on edge u -> v
ok = tidal_window(G, path, model, departures, 12, 15.5, 1.55, currents=CurrentModel(G, model))
```
