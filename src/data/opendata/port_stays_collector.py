"""Port Stays collector - Port of Antwerp-Bruges Port Stays API.

Run (from the project root):  python src/data/opendata/port_stays_collector.py
Output: ./data/opendata/port_stays/port_stays_<UTC stamp>.json

GET /stays requires `date` (UTC), which may be at most 6 hours before the call. Each poll
uses date = (last successful poll - 5 min overlap), never older than 5.5 h, so nothing is
missed between polls. Every stay is hashed; only new or changed stays are written, so files
never repeat the same data. Default: one call every 10 minutes (144/day).

Settings (.env): PORTSTAYS_INTERVAL_SECONDS (default 600), PORTSTAYS_DAILY_CAP (default 0 = off)
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

try:
    import opendata_common as oc
except (
    ImportError
):  # started as a package: python -m src.data.opendata.port_stays_collector
    from . import opendata_common as oc

NAME = "port_stays"
API = "PORTSTAYS"
DEFAULT_INTERVAL = 600
DEFAULT_DAILY_CAP = 0

MAX_LOOKBACK = timedelta(hours=5, minutes=30)  # API limit is 6 h; keep a safety margin
OVERLAP = timedelta(minutes=5)
SHORT_LOOKBACK = timedelta(hours=1)  # used once after an HTTP 400
FORGET_AFTER = 14 * 24 * 3600  # drop dedup entries for stays not seen for 14 days


def compute_date(state: dict, now: datetime) -> datetime:
    if state.get("short_lookback_next"):
        return now - SHORT_LOOKBACK
    earliest = now - MAX_LOOKBACK
    last = state.get("last_success_epoch")
    if isinstance(last, (int, float)):
        candidate = datetime.fromtimestamp(last, tz=timezone.utc) - OVERLAP
        if candidate > now:  # clock moved backwards
            candidate = now - OVERLAP
        return max(candidate, earliest)
    return earliest


def stay_key(stay: dict) -> str:
    return str(stay.get("stay_number") or oc.canonical_hash(stay)[:16])


def collect(rt: "oc.Runtime") -> None:
    state = rt.state.data
    request_time = oc.utc_now()
    date_param = oc.iso_z(compute_date(state, request_time))

    try:
        data = rt.client.get_json("/stays", params={"date": date_param})
    except oc.BadRequest:
        state["short_lookback_next"] = (
            True  # retry next cycle with a safer, shorter window
        )
        raise

    stays = [s for s in oc.as_list(data) if isinstance(s, dict)]
    known = state.setdefault("stays", {})
    now_epoch = time.time()

    changed = []
    hashes = {}
    for stay in stays:
        key = stay_key(stay)
        digest = oc.canonical_hash(stay)
        hashes[key] = digest
        if known.get(key, {}).get("h") != digest:
            changed.append(stay)

    if changed:
        payload = {
            "collected_at_utc": oc.iso_z(request_time),
            "date_param": date_param,
            "count_in_response": len(stays),
            "count_new_or_changed": len(changed),
            "data": changed,
        }
        path = oc.write_json_snapshot(rt.out_dir, "port_stays", payload)
        rt.log.info(
            "date=%s: %d stays in response, %d new/changed -> saved %s",
            date_param,
            len(stays),
            len(changed),
            path.name,
        )
    else:
        rt.log.info(
            "date=%s: %d stays in response, nothing new", date_param, len(stays)
        )

    # Update state only after a successful write.
    for key, digest in hashes.items():
        known[key] = {"h": digest, "seen": now_epoch}
    for key in [
        k for k, v in known.items() if now_epoch - v.get("seen", 0) > FORGET_AFTER
    ]:
        del known[key]
    state["last_success_epoch"] = request_time.timestamp()
    state.pop("short_lookback_next", None)
    rt.state.save()


def main() -> None:
    rt = oc.start(NAME, API, DEFAULT_INTERVAL, DEFAULT_DAILY_CAP)
    rt.run(lambda: collect(rt))


if __name__ == "__main__":
    main()
