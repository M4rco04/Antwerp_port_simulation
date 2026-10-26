"""Collect live AIS ship data for the Scheldt approach from aisstream.io.

aisstream.io is a websocket stream, not a request/response API, so the
collector keeps one subscription open, tracks the latest state of every ship
inside AREA, and every --interval seconds (default 5 min) writes a snapshot
to data/ais/ and commits + pushes it.

The API key is read from the AISSTREAM_API_KEY environment variable or from
a .env file in the repo root (AISSTREAM_API_KEY=...). .env is gitignored.

Usage:
    py src/data/ais_collector.py                              # run forever
    py src/data/ais_collector.py --no-push                    # snapshots only, no git
    py src/data/ais_collector.py --once --listen 60 --no-push # quick test
"""
import argparse
import asyncio
import json
import logging
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

REPO_ROOT = Path(__file__).resolve().parents[2]
STREAM_URL = "wss://stream.aisstream.io/v0/stream"

log = logging.getLogger("ais")


def dm(degrees, minutes):
    return round(degrees + minutes / 60, 6)


# (lat, lon) corners, in order: 51 23.33N 002 31.03E, 51 43.08N 002 36.68E,
# 51 28.02N 004 17.98E, 51 10.81N 004 26.03E
AREA = [
    (dm(51, 23.33), dm(2, 31.03)),
    (dm(51, 43.08), dm(2, 36.68)),
    (dm(51, 28.02), dm(4, 17.98)),
    (dm(51, 10.81), dm(4, 26.03)),
]
# aisstream only filters by rectangle, the polygon itself is applied client side
BBOX = [
    [min(lat for lat, _ in AREA), min(lon for _, lon in AREA)],
    [max(lat for lat, _ in AREA), max(lon for _, lon in AREA)],
]

POSITION_TYPES = {"PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport"}
STATIC_TYPES = {"ShipStaticData", "StaticDataReport"}

# forget ships we haven't heard from in this long (keeps memory bounded)
FORGET_AFTER = 6 * 3600


def in_area(lat, lon, polygon=AREA):
    """Ray casting point-in-polygon test (ray pointing north)."""
    inside = False
    for (lat1, lon1), (lat2, lon2) in zip(polygon, polygon[1:] + polygon[:1]):
        if (lon1 > lon) != (lon2 > lon):
            crossing = lat1 + (lon - lon1) * (lat2 - lat1) / (lon2 - lon1)
            if lat < crossing:
                inside = not inside
    return inside


def clean(text):
    # AIS pads strings with spaces and '@'
    text = (text or "").replace("@", " ").strip()
    return text or None


def unavailable(value, sentinel):
    return None if value is None or value >= sentinel else value


class ShipTracker:
    def __init__(self):
        self.ships = {}

    def handle(self, msg):
        mtype = msg.get("MessageType")
        body = msg.get("Message", {}).get(mtype)
        meta = msg.get("MetaData", {})
        mmsi = meta.get("MMSI") or (body or {}).get("UserID")
        if body is None or not mmsi:
            return

        now = time.time()
        ship = self.ships.setdefault(mmsi, {"mmsi": mmsi})
        ship["_touched"] = now
        if clean(meta.get("ShipName")):
            ship["name"] = clean(meta.get("ShipName"))

        if mtype in POSITION_TYPES:
            ship.update(
                lat=body.get("Latitude"),
                lon=body.get("Longitude"),
                sog=unavailable(body.get("Sog"), 102.3),
                cog=unavailable(body.get("Cog"), 360),
                heading=unavailable(body.get("TrueHeading"), 360),
                ais_class="A" if mtype == "PositionReport" else "B",
                position_time_utc=meta.get("time_utc"),
                _seen=now,
            )
            if mtype == "PositionReport":
                ship["nav_status"] = body.get("NavigationalStatus")
        elif mtype == "ShipStaticData":
            dim = body.get("Dimension") or {}
            ship.update(
                name=clean(body.get("Name")) or ship.get("name"),
                call_sign=clean(body.get("CallSign")),
                imo=body.get("ImoNumber") or None,
                ship_type=body.get("Type"),
                destination=clean(body.get("Destination")),
                eta=body.get("Eta"),
                draught=body.get("MaximumStaticDraught"),
                length=(dim.get("A", 0) + dim.get("B", 0)) or None,
                width=(dim.get("C", 0) + dim.get("D", 0)) or None,
            )
        elif mtype == "StaticDataReport":
            report_a, report_b = body.get("ReportA") or {}, body.get("ReportB") or {}
            if report_a.get("Valid") and clean(report_a.get("Name")):
                ship["name"] = clean(report_a.get("Name"))
            if report_b.get("Valid"):
                dim = report_b.get("Dimension") or {}
                ship.update(
                    call_sign=clean(report_b.get("CallSign")),
                    ship_type=report_b.get("ShipType"),
                    length=(dim.get("A", 0) + dim.get("B", 0)) or None,
                    width=(dim.get("C", 0) + dim.get("D", 0)) or None,
                )

    def snapshot(self, stale_after):
        """Ships with a fresh position inside AREA; internal '_' fields stripped."""
        now = time.time()
        self.ships = {m: s for m, s in self.ships.items() if s["_touched"] >= now - FORGET_AFTER}
        ships = [
            {k: v for k, v in s.items() if not k.startswith("_")}
            for s in self.ships.values()
            if s.get("_seen", 0) >= now - stale_after and in_area(s["lat"], s["lon"])
        ]
        return sorted(ships, key=lambda s: s["mmsi"])


def load_api_key():
    key = os.environ.get("AISSTREAM_API_KEY")
    env_file = REPO_ROOT / ".env"
    if not key and env_file.exists():
        raw = env_file.read_bytes()
        # PowerShell 5.1 `echo ... > .env` writes UTF-16
        text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
        for line in text.splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "AISSTREAM_API_KEY":
                key = value.strip().strip("'\"")
    if not key:
        raise SystemExit("Set AISSTREAM_API_KEY (environment variable or .env in the repo root).")
    return key


async def stream(api_key, tracker):
    subscription = {
        "APIKey": api_key,
        "BoundingBoxes": [BBOX],
        "FilterMessageTypes": sorted(POSITION_TYPES | STATIC_TYPES),
    }
    backoff = 1
    while True:
        received = 0
        try:
            async with connect(STREAM_URL, ping_interval=20, ping_timeout=20) as ws:
                await ws.send(json.dumps(subscription))
                log.info("Subscribed to aisstream.io, bbox %s", BBOX)
                async for raw in ws:
                    msg = json.loads(raw)
                    if "error" in msg:
                        raise RuntimeError(f"aisstream.io rejected the subscription: {msg['error']}")
                    tracker.handle(msg)
                    received += 1
                    backoff = 1
        except (OSError, WebSocketException, asyncio.TimeoutError) as e:
            log.warning("Stream disconnected (%s), reconnecting in %ss", e, backoff)
        if not received:
            # aisstream drops the connection without a message when the key is invalid
            log.warning("Connection closed before any data arrived - check AISSTREAM_API_KEY")
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)


def git(*args):
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=120)


def commit_and_push(path, message):
    rel = str(path.relative_to(REPO_ROOT))
    git("add", "--", rel)
    if git("diff", "--cached", "--quiet", "--", rel).returncode == 0:
        log.info("Nothing new to commit")
        return
    # commit only the data dir, so whatever else is staged in the repo is left alone
    result = git("commit", "-m", message, "--", rel)
    if result.returncode:
        log.error("git commit failed: %s", result.stderr.strip() or result.stdout.strip())
        return
    if git("push").returncode == 0:
        log.info("Pushed: %s", message)
        return
    log.warning("Push rejected, rebasing onto remote and retrying")
    result = git("pull", "--rebase", "--autostash")
    if result.returncode:
        git("rebase", "--abort")
        log.error("git pull --rebase failed, will retry next cycle: %s", result.stderr.strip())
        return
    result = git("push")
    if result.returncode:
        log.error("git push failed, will retry next cycle: %s", result.stderr.strip())
    else:
        log.info("Pushed: %s", message)


def save_snapshot(ships, out_dir, push):
    taken_at = datetime.now(timezone.utc).replace(microsecond=0)
    if not ships:
        log.warning("No ships in area at %s, skipping snapshot", taken_at.isoformat())
        return
    payload = json.dumps(
        {"taken_at_utc": taken_at.isoformat(), "area": AREA, "ship_count": len(ships), "ships": ships},
        separators=(",", ":"),
    )
    day_dir = out_dir / taken_at.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / taken_at.strftime("%H%M%SZ.json")
    path.write_text(payload, encoding="utf-8")
    (out_dir / "latest.json").write_text(payload, encoding="utf-8")
    log.info("Saved %d ships to %s", len(ships), path)
    if push:
        commit_and_push(out_dir, f"AIS snapshot {taken_at:%Y-%m-%d %H:%M}Z ({len(ships)} ships)")


async def snapshot_loop(tracker, args):
    next_run = time.monotonic() + args.interval
    while True:
        await asyncio.sleep(max(0, next_run - time.monotonic()))
        next_run += args.interval
        ships = tracker.snapshot(args.stale_after)
        await asyncio.to_thread(save_snapshot, ships, args.out, not args.no_push)


async def run(args):
    tracker = ShipTracker()
    stream_task = asyncio.create_task(stream(load_api_key(), tracker))
    if args.once:
        done, _ = await asyncio.wait({stream_task}, timeout=args.listen)
        if done:
            stream_task.result()
        stream_task.cancel()
        save_snapshot(tracker.snapshot(args.stale_after), args.out, not args.no_push)
        return
    tasks = {stream_task, asyncio.create_task(snapshot_loop(tracker, args))}
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    for task in pending:
        task.cancel()
    for task in done:
        task.result()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--interval", type=int, default=300, help="seconds between snapshots (default 300)")
    parser.add_argument("--stale-after", type=int, default=600,
                        help="drop ships whose last position is older than this many seconds (default 600)")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "ais", help="snapshot directory")
    parser.add_argument("--no-push", action="store_true", help="write snapshots but don't commit/push")
    parser.add_argument("--once", action="store_true", help="listen once for --listen seconds, save, exit")
    parser.add_argument("--listen", type=int, default=60, help="listen time for --once (default 60)")
    args = parser.parse_args()
    args.out = args.out.resolve()
    if not args.no_push and not args.out.is_relative_to(REPO_ROOT):
        parser.error("--out must be inside the repo when pushing")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
