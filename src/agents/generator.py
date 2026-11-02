"""Ship generation (PLAN.md §3).

Level 1, container ships: replay of the schedule CSV. Each line gives the vessel, TEU, the
scheduled berth arrival / departure (Europe/Brussels time) and the terminal code. TEU gives the
dimensions (container_calls.dimensions_for_teu, with the fitted residual noise), the call size
and the cranes. With delays=True the berth arrival is shifted by a delay drawn from the AIS
(container_calls.SCHEDULE_DELAY_H). The ship enters the area ENTRY_LEAD_H before that, at a sea
source drawn from entry_probabilities.

Level 2, background traffic: a non-homogeneous Poisson process per class and entry source,
rate = entry_probabilities.RATE_PER_HOUR x HOURLY_FACTOR(hour of day). Attributes are whole AIS
ships (background_traffic.sample_attributes), the destination depends on class and source.
"""

from __future__ import annotations

import csv
import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ship import Ship, container_moves, cranes_for

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "data"))
import background_traffic as BT          # noqa: E402
import container_calls as CC             # noqa: E402
import entry_probabilities as EP         # noqa: E402

SCHEDULE = ROOT / "data" / "schedules" / "2026_Oct20-Nov22.csv"
SCHEDULE_TZ = "Europe/Brussels"
SCHEDULE_YEAR = 2026
ENTRY_LEAD_H = 8.0                  # enter the area this long before the berth time
# schedule terminal code -> Terminal (graph.graph["terminals"]); other codes berth in a dock zone
TERMINAL_OF_CODE = {"1700": "DP World Antwerp Gateway", "K1742": "MPET", "K1718": "MPET",
                    "K913": "PSA Noordzee Terminal", "K869": "PSA Europa Terminal"}
BACKGROUND_CLASSES = ("bulk_general", "tanker", "inland_cargo", "inland_tanker", "passenger")
# canals reached only through a lock: the largest chamber's length and width (environment LOCKS):
# a ship entering from or leaving to them must fit (Kreekrak, Hansweert, Royers)
CANAL_LIMITS = {"schelde_rijn_canal": (320.0, 24.0), "zuid_beveland_canal": (280.0, 24.0), "albert_canal": (180.0, 22.0)}


def read_schedule(path=SCHEDULE):
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.reader(f, delimiter=";"):
            if not r or r[0] == "Vessel" or len(r) < 4:
                continue
            r = (r + [""] * 6)[:6]
            rows.append(dict(zip(("vessel", "teu", "voyage", "arrival", "departure", "terminal"), r)))
    df = pd.DataFrame(rows)
    df["teu"] = pd.to_numeric(df.teu, errors="coerce")

    def parse(col):
        local = pd.to_datetime(df[col] + f" {SCHEDULE_YEAR}", format="%b %d, %I %p %Y", errors="coerce")
        return local.dt.tz_localize(SCHEDULE_TZ, ambiguous=np.ones(len(local), dtype=bool),
                                    nonexistent="shift_forward").dt.tz_convert("UTC")

    df["arrival"], df["departure"] = parse("arrival"), parse("departure")
    return df[df.arrival.notna() & df.teu.notna()].reset_index(drop=True)


class Generator:
    def __init__(self, start, rng, delays=True, schedule=SCHEDULE, background=True, containers=True):
        self.start = pd.Timestamp(start)
        self.rng = rng
        self.delays = delays
        self.background = background
        self.counter = itertools.count(1)
        self.pending = []
        if containers:
            self._schedule(read_schedule(schedule))
        self.median_draught = {c: float(np.nanmedian([r[2] for r in BT.ATTRIBUTES[c] if r[2]]))
                               for c in BACKGROUND_CLASSES}

    def minutes(self, ts):
        return (ts - self.start).total_seconds() / 60.0

    # ------------------------------------------------------------------ containers
    def _schedule(self, df):
        known = df.terminal[df.terminal != ""]
        codes = known.value_counts(normalize=True)
        for r in df.itertuples():
            code = r.terminal or self.rng.choice(codes.index, p=codes.to_numpy())    # missing code: drawn
            berth_t = r.arrival + pd.Timedelta(hours=CC.sample_arrival_delay(self.rng) if self.delays else 0.0)
            spawn = self.minutes(berth_t) - ENTRY_LEAD_H * 60
            dims = CC.dimensions_for_teu(r.teu, self.rng)
            zone = None
            if code not in TERMINAL_OF_CODE:
                zones = CC.TERMINAL_LOCATION.get(code, {}).get("zones") or {"antwerp_right_bank_docks": 1.0}
                zone = max(zones, key=zones.get)
            ship = Ship(id=f"C{next(self.counter):04d}", cls="container", loa=round(dims["loa"], 1),
                        beam=round(dims["beam"], 1), draught=round(min(dims["draught"], 16.0), 2), level=1,
                        source=EP.sample_source("container", self.rng, category="sea"),
                        destination=zone or "antwerp_terminal", spawn_t=spawn, teu=float(r.teu), name=r.vessel,
                        terminal=TERMINAL_OF_CODE.get(code), berth_zone=zone,
                        schedule={"code": code, "arrival": r.arrival, "departure": r.departure,
                                  "arrival_min": self.minutes(r.arrival),
                                  "departure_min": self.minutes(r.departure) if pd.notna(r.departure) else None},
                        moves=container_moves(r.teu, self.rng), cranes_wanted=cranes_for(r.teu))
            if spawn < 0:                    # due before the run starts: the warm-up replaces it
                continue
            if zone:
                ship.dwell_h = (r.departure - r.arrival).total_seconds() / 3600 if pd.notna(r.departure) else 24.0
            self.pending.append(ship)
        self.pending.sort(key=lambda s: s.spawn_t)

    # ------------------------------------------------------------------ background
    def _background(self, t0, dt):
        hour = int(((self.start + pd.Timedelta(minutes=t0)).hour))
        out = []
        for cls in BACKGROUND_CLASSES:
            for source, rate in EP.RATE_PER_HOUR[cls].items():
                lam = rate * EP.HOURLY_FACTOR[cls][hour] * dt / 60.0
                for _ in range(self.rng.poisson(lam)):
                    dest = BT.sample_destination(cls, self.rng, source)
                    a = self._fitting_attributes(cls, source, dest)
                    loa = float(a["loa"])
                    ship = Ship(id=f"B{next(self.counter):05d}", cls=cls, loa=loa,
                                beam=float(a["beam"] or round(loa / 7, 1)),
                                draught=float(a["draught"] or self.median_draught[cls]), level=2, source=source,
                                destination=dest, spawn_t=t0 + self.rng.uniform(0, dt), dg=a["dg"])
                    out.append(ship)
        return out

    def _fitting_attributes(self, cls, source, dest):
        """An AIS ship of the class that fits the locks on its way in and out: a ship entering from or
        leaving to a canal behind a lock must pass that lock (CANAL_LIMITS). Redrawn up to 100 times."""
        ends = [source, dest[5:] if dest.startswith("exit_") else dest]
        limits = [CANAL_LIMITS[e] for e in ends if e in CANAL_LIMITS]
        for _ in range(100):
            a = BT.sample_attributes(cls, self.rng)
            loa = float(a["loa"])
            beam = float(a["beam"] or loa / 7)
            if all(loa <= L and beam <= B for L, B in limits):
                return a
        return a

    def arrivals(self, t0, dt):
        """Ships entering in [t0, t0 + dt) minutes."""
        out = []
        while self.pending and self.pending[0].spawn_t < t0 + dt:
            out.append(self.pending.pop(0))
        if self.background:
            out += self._background(t0, dt)
        return out
