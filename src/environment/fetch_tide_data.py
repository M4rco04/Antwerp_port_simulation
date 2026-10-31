"""Download the water levels and weather the tide and surge models are fitted on.

    data/tides/<gauge>.csv.gz     10-min water level (cm above NAP, UTC) from the Rijkswaterstaat
                                  water web services (DDL), for the gauges in GAUGES
    data/weather/knmi_310.csv.gz  hourly wind direction / speed, gusts, pressure and visibility at
                                  KNMI station 310 Vlissingen

Downloads are done month by month and retried; files already complete are skipped, so an
interrupted run can simply be started again.

Usage:
    py src/environment/fetch_tide_data.py                       # the last 2 years
    py src/environment/fetch_tide_data.py --start 2024-01-01 --end 2026-10-01
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TIDE_DIR = PROJECT_ROOT / "data" / "tides"
WEATHER_DIR = PROJECT_ROOT / "data" / "weather"
RWS_URL = "https://ddapi20-waterwebservices.rijkswaterstaat.nl/ONLINEWAARNEMINGENSERVICES/OphalenWaarnemingen"
KNMI_URL = "https://www.daggegevens.knmi.nl/klimatologie/uurgegevens"
KNMI_STATION = 310          # Vlissingen
RETRIES = 3

# Rijkswaterstaat location code -> (name, lon, lat), from the sea up to Antwerp
GAUGES = {
    "westkapelle": ("Westkapelle", 3.440031, 51.521448),
    "cadzand.2": ("Cadzand", 3.376275, 51.379298),
    "vlissingen": ("Vlissingen", 3.6, 51.442),
    "terneuzen": ("Terneuzen", 3.819812, 51.336212),
    "hansweert": ("Hansweert", 3.99744, 51.44567),
    "walsoorden": ("Walsoorden", 4.026206, 51.398427),
    "schaarvandenoord": ("Schaar van de Noord", 4.164992, 51.377868),
    "rilland.bath": ("Bath", 4.21014, 51.39878),
    "fortliefkenshoek": ("Fort Liefkenshoek", 4.285749, 51.296459),
    "kallosluis.schelde": ("Kallosluis (Scheldt)", 4.29859, 51.267822),
    "antwerpen.loodsgebouw": ("Antwerpen Loodsgebouw", 4.399894, 51.227537),
}

log = logging.getLogger("fetch")


def _post_json(url, body, timeout=180):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def _retry(fn, what):
    for attempt in range(1, RETRIES + 1):
        try:
            return fn()
        except Exception as e:  # the services time out or drop connections now and then
            if attempt == RETRIES:
                raise
            log.warning("%s failed (%s), retrying", what, str(e)[:100])
            time.sleep(10 * attempt)


def months(start, end):
    t = start
    while t < end:
        nxt = (t.replace(day=1) + timedelta(days=32)).replace(day=1)
        yield t, min(nxt, end)
        t = nxt


def fetch_gauge(code, start, end):
    """10-min levels (cm above NAP) of one gauge, as a Series indexed by UTC time."""
    parts = []
    for t0, t1 in months(start, end):
        body = {"Locatie": {"Code": code},
                "AquoPlusWaarnemingMetadata": {"AquoMetadata": {
                    "Compartiment": {"Code": "OW"}, "Grootheid": {"Code": "WATHTE"},
                    "Hoedanigheid": {"Code": "NAP"}, "ProcesType": "meting"}},
                "Periode": {"Begindatumtijd": t0.strftime("%Y-%m-%dT%H:%M:%S.000+00:00"),
                            "Einddatumtijd": t1.strftime("%Y-%m-%dT%H:%M:%S.000+00:00")}}
        try:
            reply = _retry(lambda: _post_json(RWS_URL, body), f"{code} {t0:%Y-%m}")
        except Exception as e:   # an empty reply usually means no data that month: a gap is fine
            log.warning("%s %s skipped (%s)", code, f"{t0:%Y-%m}", str(e)[:80])
            continue
        if not reply.get("Succesvol"):
            log.warning("%s %s: no data (%s)", code, f"{t0:%Y-%m}", reply.get("Foutmelding", "")[:80])
            continue
        for series in reply["WaarnemingenLijst"]:
            values = [(m["Tijdstip"], m["Meetwaarde"].get("Waarde_Numeriek")) for m in series["MetingenLijst"]]
            parts.append(pd.DataFrame(values, columns=["time", "level_cm"]))
        log.info("%s %s: %d values", code, f"{t0:%Y-%m}", sum(len(p) for p in parts[-len(reply["WaarnemingenLijst"]):]))
    df = pd.concat(parts)
    df["time"] = pd.to_datetime(df.time, utc=True)
    s = df.set_index("time").level_cm.astype(float).sort_index()
    s = s[~s.index.duplicated()]
    return s[(s > -1000) & (s < 1000)]          # 999999999 marks a missing value


def fetch_knmi(start, end):
    """Hourly weather at KNMI_STATION: DD (deg), FH, FF, FX (0.1 m/s), P (0.1 hPa), VV (class)."""
    parts = []
    for t0, t1 in months(start, end):
        form = urllib.parse.urlencode({"start": f"{t0:%Y%m%d}01", "end": f"{(t1 - timedelta(days=1)):%Y%m%d}24",
                                       "vars": "DD:FH:FF:FX:P:VV", "stns": KNMI_STATION}).encode()
        text = _retry(lambda: urllib.request.urlopen(urllib.request.Request(KNMI_URL, form), timeout=180).read().decode(),
                      f"KNMI {t0:%Y-%m}")
        rows = [line for line in text.splitlines() if line and not line.startswith("#")]
        parts.append(pd.read_csv(io.StringIO("\n".join(rows)), header=None, skipinitialspace=True,
                                 names=["STN", "date", "HH", "DD", "FH", "FF", "FX", "P", "VV"]))
    df = pd.concat(parts)
    # HH = 1..24: the hour ending at HH UTC
    df["time"] = pd.to_datetime(df.date.astype(str), format="%Y%m%d", utc=True) + pd.to_timedelta(df.HH, unit="h")
    df = df.drop(columns=["STN", "date", "HH"]).set_index("time").sort_index()
    return df[~df.index.duplicated()]      # KNMI repeats a day at each month boundary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    now = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    parser.add_argument("--start", default=(now - timedelta(days=730)).strftime("%Y-%m-01"))
    parser.add_argument("--end", default=now.strftime("%Y-%m-%d"))
    parser.add_argument("--force", action="store_true", help="download again even if the file exists")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    TIDE_DIR.mkdir(parents=True, exist_ok=True)
    WEATHER_DIR.mkdir(parents=True, exist_ok=True)

    weather_file = WEATHER_DIR / f"knmi_{KNMI_STATION}.csv.gz"
    if args.force or not weather_file.is_file():
        fetch_knmi(start, end).to_csv(weather_file)
        log.info("Saved %s", weather_file)
    for code in GAUGES:
        out = TIDE_DIR / f"{code}.csv.gz"
        if out.is_file() and not args.force:
            log.info("%s already downloaded", code)
            continue
        fetch_gauge(code, start, end).to_csv(out)
        log.info("Saved %s", out)


if __name__ == "__main__":
    main()
