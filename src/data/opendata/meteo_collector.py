"""Meteo collector - Port of Antwerp-Bruges Meteo API.

Run (from the project root):  python src/data/opendata/meteo_collector.py
Output: ./data/opendata/meteo/meteo_<YYYYMMDDTHHMMSSZ>.csv   (timestamp = collection time, UTC)

Rate limit (docs): 100 calls per day per company_code. Defaults: one call every 20 minutes
(72/day) and a persistent hard cap of 90/day, which leaves headroom for other calls.
Deduplication: a station's reading is saved only when its poa_ingest_time_utc is new.

Settings (.env): METEO_INTERVAL_SECONDS (default 1200), METEO_DAILY_CAP (default 90, 0 = off)
"""

from __future__ import annotations

import json

try:
    import opendata_common as oc
except ImportError:  # started as a package: python -m src.data.opendata.meteo_collector
    from . import opendata_common as oc

NAME = "meteo"
API = "METEO"
DEFAULT_INTERVAL = 1200
DEFAULT_DAILY_CAP = 90

BASE_COLUMNS = [
    "collected_at_utc",
    "station",
    "station_description",
    "station_longitude_wgs84",
    "station_latitude_wgs84",
]
MEASURE_COLUMNS = [
    "poa_ingest_time_utc",
    "ws_600",
    "ws_ship_600",
    "ws_max_600",
    "ws_min_600",
    "ws_600_beaufort",
    "ws_ship_600_beaufort",
    "ws_max_600_beaufort",
    "ws_min_600_beaufort",
    "wr_10",
    "wr_600",
    "tt_600",
    "tt_max_600",
    "tt_min_600",
    "tt_10",
]


def build_row(reading: dict, collected_at: str) -> dict:
    location = (
        reading.get("location") if isinstance(reading.get("location"), dict) else {}
    )
    row = {
        "collected_at_utc": collected_at,
        "station": location.get("name"),
        "station_description": location.get("description"),
        "station_longitude_wgs84": location.get("longitude_wgs84"),
        "station_latitude_wgs84": location.get("latitude_wgs84"),
    }
    for key, value in reading.items():
        if key == "location":
            continue
        row[key] = (
            json.dumps(value, ensure_ascii=False)
            if isinstance(value, (dict, list))
            else value
        )
    return row


def collect(rt: "oc.Runtime") -> None:
    data = rt.client.get_json("/readings")
    readings = [r for r in oc.as_list(data) if isinstance(r, dict)]
    if not readings:
        rt.log.warning("response contained no readings")
        return

    last_seen = rt.state.data.setdefault("last_seen", {})
    collected_at = oc.iso_z(oc.utc_now())
    new_items, rows = [], []
    for reading in readings:
        location = (
            reading.get("location") if isinstance(reading.get("location"), dict) else {}
        )
        station = location.get("name") or "unknown"
        identity = reading.get("poa_ingest_time_utc") or oc.canonical_hash(reading)
        if last_seen.get(station) == identity:
            continue  # same reading as last time
        new_items.append((station, identity))
        rows.append(build_row(reading, collected_at))

    if not rows:
        rt.log.info("no new readings (%d stations unchanged)", len(readings))
        return

    extras = sorted(
        {key for row in rows for key in row} - set(BASE_COLUMNS) - set(MEASURE_COLUMNS)
    )
    path = oc.write_csv_snapshot(
        rt.out_dir, "meteo", BASE_COLUMNS + MEASURE_COLUMNS + extras, rows
    )

    # Update dedup state only after the file was written successfully.
    for station, identity in new_items:
        last_seen[station] = identity
    rt.state.save()
    rt.log.info(
        "saved %d new readings -> %s (calls today: %d)",
        len(rows),
        path.name,
        rt.budget.calls_today,
    )


def main() -> None:
    rt = oc.start(NAME, API, DEFAULT_INTERVAL, DEFAULT_DAILY_CAP)
    rt.run(lambda: collect(rt))


if __name__ == "__main__":
    main()
