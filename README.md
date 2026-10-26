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