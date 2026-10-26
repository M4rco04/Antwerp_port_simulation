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
