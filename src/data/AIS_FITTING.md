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
- **Durations.** The lognormal fits allow for stays still in progress when the data ends (and for stops under 0.5 h never being recorded). With few complete stays, the long tail is an extrapolation.
- **Container delays.** Ships berth roughly 1–2 days later than the schedule CSV says, which reflects congestion or stale planned times. Schedule times are read as Brussels local time, and delays are only matched within ±96 h.
- **Hand-tuned zones.** The zone boxes and thresholds are constants at the top of `ais_pipeline.py`. After changing them, check the result with `--plot`.
- **Self-reported AIS fields.** Draught is the largest value a ship reported, not its design maximum. Ship type and destination are also self-reported and sometimes stale.
