"""Bridges and Locks collector - Port of Antwerp-Bruges Bridges and Locks API.

Run (from the project root):  python src/data/opendata/bridges_locks_collector.py
Output: ./data/opendata/bridges/bridges_state_<UTC stamp>.json
        ./data/opendata/locks/locks_state_<UTC stamp>.json

The API returns the full current state of all bridges / locks. A snapshot is written only
when that state differs from the previously saved one, so every file is a real change.
No rate limit is documented (403 = too many requests), so the default is one poll per
5 minutes (2 calls per poll). On 403/429 the collector pauses with growing back-off.

Settings (.env): BRIDGESANDLOCKS_INTERVAL_SECONDS (default 300), BRIDGESANDLOCKS_DAILY_CAP (default 0 = off)
"""

from __future__ import annotations

try:
    import opendata_common as oc
except (
    ImportError
):  # started as a package: python -m src.data.opendata.bridges_locks_collector
    from . import opendata_common as oc

NAME = "bridges_locks"
API = "BRIDGESANDLOCKS"
DEFAULT_INTERVAL = 300
DEFAULT_DAILY_CAP = 0

# (state key, endpoint path, file prefix, output directory under ./data/opendata/)
ENDPOINTS = [
    ("bridges", "/bridges/state", "bridges_state", "bridges"),
    ("locks", "/locks/state", "locks_state", "locks"),
]


def collect(rt: "oc.Runtime") -> None:
    hashes = rt.state.data.setdefault("hashes", {})
    errors = []

    for index, (key, path, prefix, dirname) in enumerate(ENDPOINTS):
        if index:
            rt.sleep(1.0)  # be polite between the two calls
        try:
            data = rt.client.get_json(path)
        except oc.CollectorError as exc:
            errors.append(exc)
            if isinstance(exc, (oc.RateLimited, oc.BudgetExhausted)):
                break  # do not hammer the API; back-off is handled by the run loop
            rt.log.warning("%s: %s", key, exc)
            continue

        items = oc.as_list(data)
        digest = oc.canonical_hash(data)
        if hashes.get(key) == digest:
            rt.log.info("%s unchanged (%d items)", key, len(items))
            continue

        payload = {
            "collected_at_utc": oc.iso_z(oc.utc_now()),
            "source": f"{rt.client.base}{path}",
            "count": len(items),
            "data": data,
        }
        file_path = oc.write_json_snapshot(oc.data_root() / dirname, prefix, payload)
        hashes[key] = digest  # only after the file exists
        rt.state.save()
        rt.log.info(
            "%s changed -> saved %s (%d items)", key, file_path.name, len(items)
        )

    if errors:
        raise errors[0]


def main() -> None:
    rt = oc.start(NAME, API, DEFAULT_INTERVAL, DEFAULT_DAILY_CAP)
    root = oc.data_root()
    rt.out_label = f"{root / 'bridges'} and {root / 'locks'}"
    rt.run(lambda: collect(rt))


if __name__ == "__main__":
    main()
