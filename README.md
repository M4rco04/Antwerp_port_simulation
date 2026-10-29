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