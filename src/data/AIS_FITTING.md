# AIS distribution fitting

Scripts that turn the AIS snapshots in `data/ais/` into probability distributions for the
simulation (PLAN.md §1–3). Each `fit_*.py` script writes a generated Python module that the
simulation imports. **Don't edit the generated modules by hand.** Re-run the scripts instead.

## Rerunning

Run from the repo root, after more AIS data has been collected:

```
pip install -r requirements.txt
py src/data/fit_entry_probabilities.py --plot entries.png   # -> src/data/entry_probabilities.py
py src/data/fit_background_traffic.py                        # -> src/data/background_traffic.py
py src/data/fit_container_calls.py                           # -> src/data/container_calls.py
```

- The scripts are independent and each takes about a minute.
- `--plot` saves a map of the entry points, which is useful for checking the zone boxes.
- Every script accepts `--ais`, `--schedule`, `--charts`, `--berths` and `--out` to point at other inputs or outputs.

Inputs: `data/ais/`, `data/schedules/2026_Oct20-Nov22.csv`, `data/charts/scheldt_navigation.gpkg`
(anchorages, land), `slots_cords/paczka_final.json` (Antwerp berths).

## How it works (`ais_pipeline.py`, shared)

1. **Snapshots → positions.** Snapshots written seconds apart by two collectors are counted once. Gaps longer than 12 min count as collector downtime.
2. **Visits.** A ship's positions are split into visits; a new visit starts when the ship comes back somewhere else after more than 6 h. Gaps caused by collector downtime never start a new visit.
3. **Censoring.** Ships first seen within 20 min of a collector (re)start were already in the area, so they don't count as arrivals. Arrival rates only use observed time, about 52 h so far.
4. **Classes.**
   - `container`: name found in the schedule, a container line's name, or cargo ≥ 250 m.
   - `bulk_general`, `tanker`: sea-going ships (valid IMO number).
   - `inland_cargo`, `inland_tanker`: no valid IMO number and LOA ≥ 50 m.
   - `passenger`.
   - `service` and `unknown`: dropped from the simulation.
5. **Scheldt only.** A visit counts only if the ship gets east of the Vlissingen–Breskens line, enters a Scheldt port or canal, or is still waiting with a Scheldt port as its destination. North Sea through traffic and Zeebrugge-only calls are dropped.
6. **Zones.**
   - Sea gates: the west, north and south-west edges of the AIS area.
   - Anchorages: from the chart file, each widened by 1.5 km.
   - Port and canal boxes: Antwerp, Albert Canal, Upper Sea Scheldt, Schelde-Rijn canal, Hansweert, Terneuzen, Ghent canal, Vlissingen, Breskens, Zeebrugge, Oosterschelde.
   - Antwerp is split further by quay number: right-bank docks, tidal river quays, left-bank docks, Deurganckdok.
7. **Stops.** A stop is lying still (< 1 kn) for at least 30 min within 1 km. It is classed as a berth stop, an anchorage stop or "other". In the lock zones, a stop shorter than 3 h counts as a lock passage, not a berth call.

## Outputs

| Module | Contents | Main helpers |
|---|---|---|
| `entry_probabilities.py` | P(entry source \| class): sea gates, anchorages, ports and canals. P(class \| source), arrival rate per class and source, hour-of-day factors, spawn points | `p_source`, `p_category`, `arrival_rate`, `sample_source` |
| `background_traffic.py` | Whole ships to resample (LOA, beam, draught, dangerous-goods category); destination per class and entry source; exit after the berth stay; lognormal time at berth and at anchor; anchorage choice; lock passage times | `sample_attributes`, `sample_destination`, `sample_exit`, `sample_berth_dwell`, `sample_anchorage_wait` |
| `container_calls.py` | TEU → LOA, beam, draught power laws with correlated scatter; berth arrival and departure delay against the schedule; time from entering the area to berthing; where each terminal code berths | `dimensions_for_teu`, `sample_arrival_delay`, `sample_departure_delay`, `sample_entry_to_berth` |

All `sample_*` functions take an `rng` that can be a `numpy.random.Generator` or a `random.Random`.

```python
import numpy as np, entry_probabilities as E, background_traffic as B, container_calls as C
rng = np.random.default_rng(0)
src = E.sample_source("tanker", rng)               # e.g. "sea_north"
dest = B.sample_destination("tanker", rng, src)    # e.g. "antwerp_right_bank_docks"
hours = B.sample_berth_dwell("tanker", rng, dest)
dims = C.dimensions_for_teu(14000, rng)
```

## Caveats

- **Little data (about 52 h usable).** Check `ENTRY_COUNTS`, `DESTINATION_COUNTS` and each fit's `n_complete` / `n_censored` before relying on a value. There are no weekly patterns yet.
- **Durations.** The lognormal fits allow for stays still in progress when the data ends (and for stops under 0.5 h never being recorded). With few complete stays, the long tail is an extrapolation: draws stop at the longest stay seen, sigma is limited to 1.6, a zone fit at a bound falls back to the class fit, and inland stays are scaled to give the AIS stock (`INLAND_STAY_SCALE`).
- **Container delays.** Ships berth roughly 1–2 days later than the schedule CSV says, which reflects congestion or stale planned times. Schedule times are read as Brussels local time, and delays are only matched within ±96 h.
- **Hand-tuned zones.** The zone boxes and thresholds are constants at the top of `ais_pipeline.py`. After changing them, check the result with `--plot`.
- **Self-reported AIS fields.** Draught is the largest value a ship reported, not its design maximum. Ship type and destination are also self-reported and sometimes stale.

## Port infrastructure (`fit_port_infrastructure.py` → `port_infrastructure.py`)

- `BERTH_USE`: berth stops of at least 0.5 h within 150 m of a charted berth, counted by ship class per
  berth. A berth is a tanker berth if it had ≥ 2 tanker or tank-barge calls and they were ≥ 50 % of its calls.
- `TUG_BASES` / `PILOT_BASES`: clusters (600 m) of the stops of tugs and pilot boats, with ≥ 50 vessel-hours
  from ≥ 2 vessels:
  - tugs: the 42 of `data/equipment/tugs.csv` plus every other ship with AIS type 52;
  - pilot boats: Brabo, LRD and "PILOT" in the name.
- `MOORING_MIN`: arrival and departure manoeuvre of sea-going ships, t = base + k·LOA with lognormal noise,
  fitted separately for tidal quays and docks:
  - arrival: from the last fix ≥ 1 km from the berth to lying still;
  - departure: from leaving to the first fix ≥ 1 km away.

- `DOCK_SPEED_KN`: speed over ground of sea-going ships under way (≥ 1 kn), per dock basin and in the outer
  harbours and docks within 600 m of a lock: median and 95th percentile. It snaps fixes to the navigation
  graph, so build the graph first.

Rerun: `py src/data/fit_port_infrastructure.py`, then rebuild the graph (`py src/environment/antwerp_port.py --no-browser`).

## Data used by the current fits

Refitted 2026-11-06 on 3,014 snapshots (2026-10-26 to 2026-11-06): 1,977,944 positions of 4,354 ships, with 244
observed hours of entries (123 h in the fits before).

A few things to know when reading the fits:
- **Inland visits are split where a craft left the area.** An inland craft under way on one side of a silence of
  6 h or more, with both ends in a zone at the edge of the area, has been out and come back: a new visit, however
  little it moved (`INLAND_LEFT_AREA_H`, `AREA_EDGE_ZONES`). This raised inland arrivals from 129 to 189 per day.
  A craft silent at a dock is not split, so some return trips may still be missed.
- **Checking inland flows against the AIS: three traps.**
  - Divide passages by calendar days (11.58), not observed days (10.47): a passage during an outage still shows as
    a change of side afterwards.
  - Do not count at a section beside a lock mouth (Terneuzen km 24, Hansweert km 40, Zandvliet and Berendrecht km 66,
    Boudewijn and Van Cauwelaert km 74): craft manoeuvring there cross the line without going anywhere.
  - Counts of ships seen inside a chamber are low: AIS hears an inland craft in about a third of its snapshots. The
    AIS trips imply about 65 passages a day at Terneuzen, where the chamber count gives 30.
- **Inland flows as they stand.** Trips between calls match the AIS (Antwerp - Schelde-Rijn 92 against 88 per day). Off
  the lock mouths, river passages are 0.84 of the AIS at km 45-60, 1.0 at km 78-83 and 0.70 at km 30-35. The last is
  the one real gap: about 30 of its 50 a day (counted at km 25) are craft that go out and back with no call seen in
  between.
- **A sea-going ship in from sea and out to sea with no call seen** has an unknown destination, not "the sea": such visits last a median of 34 h and most reach Vlissingen, so the call was not heard. Taking them at face value made 17% of bulk carriers and tankers board a pilot and leave within the hour.
- **A ship that leaves the way it came in with no call seen** likewise has an unknown destination.
- **A craft only ever seen inside one canal or edge zone** is not Scheldt traffic and is left out of the rates.
- **Anchor stays are fitted on the sea anchorages and scaled to their stock** (`ANCHOR_STAY_SCALE`), for bulk
  carriers and tankers, the classes that arrive at anchor in the model. Little's law: the mean stay is the number
  at anchor at Westhinder, Oostdyck and Schouwenbank divided by the anchor stops there per hour (14 h and 19 h).
  The draws stop at the longest stay seen, so the scale is solved for, not taken as a ratio. The fitted tails (means of
  33 h and 58 h) held twice the AIS number at anchor. Berth stays of sea-going ships are not scaled.

Rerun all fits after the collector has added data (the infrastructure fit needs the graph), then rebuild the graph:

    py src/data/fit_entry_probabilities.py; py src/data/fit_background_traffic.py; py src/data/fit_container_calls.py
    py src/data/fit_port_infrastructure.py; cd src/environment; py fit_currents.py; cd ../..
    py src/environment/antwerp_port.py --no-browser

The graph build reads the AIS too (the traffic layers that decide the sea mesh and lanes). Build it from the same
snapshots as the fits (`--ais <dir>`), or the berth catalogue, lanes and fits come from different data.

