"""Ship generation (PLAN.md §3).

Level 1, container ships, mode "replay" (default): replay of the schedule CSV. Each line gives the vessel, TEU, the
scheduled berth arrival / departure (Europe/Brussels time) and the terminal code. TEU gives the
dimensions (container_calls.dimensions_for_teu, with the fitted residual noise), the call size
and the cranes. With delays=True the berth arrival is shifted by a delay drawn from the AIS
(container_calls.SCHEDULE_DELAY_H). The ship enters the area ENTRY_LEAD_H before that, at a sea
source drawn from entry_probabilities.

Level 1, mode "nhpp": a non-homogeneous Poisson process fitted to the schedule (fit_container_nhpp):
berth arrivals at rate base x weekday factor x hour-of-day factor (Brussels time), and, because liner
calls bunch (the schedule's calls per day vary twice as much as Poisson), each day's rate times a
gamma factor of mean 1 (a Cox process) fitted to that extra variance. Each arrival is one schedule
line drawn at random (TEU, terminal code, scheduled time at berth together), entering ENTRY_LEAD_H
before its berth time. rate_factor scales the rate (scenarios). Runs need not lie inside the
schedule's dates.

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
# the TEU fit's scatter can exceed any real ship: the largest container ships are 400 x 61.5 m
MAX_LOA_M, MAX_BEAM_M = 400.0, 61.5
BACKGROUND_CLASSES = ("bulk_general", "tanker", "inland_cargo", "inland_tanker", "passenger")
# canals reached only through a lock: the largest chamber's length and width (environment LOCKS):
# a ship entering from or leaving to them must fit (Kreekrak, Hansweert, Royers)
CANAL_LIMITS = {"schelde_rijn_canal": (320.0, 24.0), "zuid_beveland_canal": (280.0, 24.0), "albert_canal": (180.0, 22.0)}


HOUR_SMOOTHING = 3                  # hour-of-day factor: circular moving average over this many hours


def fit_container_nhpp(df, tz=SCHEDULE_TZ):
    """Fitted rate of container berth arrivals from the schedule: base per hour, weekday factor (7),
    hour factor (24), both mean 1, and the gamma shape of the daily factor (None: plain Poisson)."""
    local = df.arrival.dt.tz_convert(tz)
    first, last = local.min().ceil("D"), local.max().floor("D")       # whole days only
    inside = (local >= first) & (local < last)
    days = pd.date_range(first, last, freq="D", inclusive="left")
    n = int(inside.sum())
    base = n / (len(days) * 24.0)
    # weekday: calls per occurrence of that weekday in the period, over the mean
    occ = pd.Series(days.dayofweek).value_counts().reindex(range(7), fill_value=0)
    per = local[inside].dt.dayofweek.value_counts().reindex(range(7), fill_value=0) / occ.clip(lower=1)
    weekday = (per / per.mean()).to_numpy()
    counts = local[inside].dt.hour.value_counts().reindex(range(24), fill_value=0).to_numpy(float)
    k = HOUR_SMOOTHING
    padded = np.r_[counts[-(k // 2):], counts, counts[:k // 2]]
    smooth = np.convolve(padded, np.ones(k) / k, mode="valid")
    hour = smooth / smooth.mean()
    # bunching: daily counts vs what the weekday pattern alone gives (Var = m + m^2 / shape)
    daily = local[inside].dt.floor("D").value_counts().reindex(days, fill_value=0).to_numpy(float)
    m = base * 24.0 * weekday[days.dayofweek]
    extra = float(((daily - m) ** 2).sum() - m.sum())
    shape = float((m ** 2).sum() / extra) if extra > 0 else None
    return {"base_per_h": base, "weekday": weekday, "hour": hour, "gamma_shape": shape, "calls": n,
            "days": len(days), "daily_mean": float(daily.mean()), "daily_var": float(daily.var())}


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
    def __init__(self, start, rng, delays=True, schedule=SCHEDULE, background=True, containers=True,
                 container_mode="replay", rate_factor=1.0, bunching=True):
        self.start = pd.Timestamp(start)
        self.rng = rng
        self.delays = delays
        self.background = background
        self.counter = itertools.count(1)
        self.pending = []
        self.nhpp = None
        if containers:
            df = read_schedule(schedule)
            known = df.terminal[df.terminal != ""]
            self.codes = known.value_counts(normalize=True)
            if container_mode == "replay":
                self._schedule(df)
            elif container_mode == "nhpp":
                self.calls = df.reset_index(drop=True)
                self.nhpp = fit_container_nhpp(df)
                self.nhpp["rate_factor"] = rate_factor
                if not bunching:
                    self.nhpp["gamma_shape"] = None
                self.day_factor = {}
            else:
                raise ValueError(f"container_mode {container_mode!r}: 'replay' or 'nhpp'")
        self.median_draught = {c: float(np.nanmedian([r[2] for r in BT.ATTRIBUTES[c] if r[2]]))
                               for c in BACKGROUND_CLASSES}

    def minutes(self, ts):
        return (ts - self.start).total_seconds() / 60.0

    # ------------------------------------------------------------------ containers
    def _schedule(self, df):
        for r in df.itertuples():
            berth_t = r.arrival + pd.Timedelta(hours=CC.sample_arrival_delay(self.rng) if self.delays else 0.0)
            ship = self._container(r, r.arrival, r.departure, berth_t)
            if ship.spawn_t < 0:             # due before the run starts: the warm-up replaces it
                continue
            self.pending.append(ship)
        self.pending.sort(key=lambda s: s.spawn_t)

    def _container(self, r, arrival, departure, berth_t):
        """A container ship for schedule line r berthing at berth_t, with its scheduled arrival / departure."""
        code = r.terminal or self.rng.choice(self.codes.index, p=self.codes.to_numpy())    # missing code: drawn
        spawn = self.minutes(berth_t) - ENTRY_LEAD_H * 60
        dims = CC.dimensions_for_teu(r.teu, self.rng)
        zone = None
        if code not in TERMINAL_OF_CODE:
            zones = CC.TERMINAL_LOCATION.get(code, {}).get("zones") or {"antwerp_right_bank_docks": 1.0}
            zone = max(zones, key=zones.get)
        ship = Ship(id=f"C{next(self.counter):04d}", cls="container", loa=round(min(dims["loa"], MAX_LOA_M), 1),
                    beam=round(min(dims["beam"], MAX_BEAM_M), 1), draught=round(min(dims["draught"], 16.0), 2), level=1,
                    source=EP.sample_source("container", self.rng, category="sea"),
                    destination=zone or "antwerp_terminal", spawn_t=spawn, teu=float(r.teu), name=r.vessel,
                    terminal=TERMINAL_OF_CODE.get(code), berth_zone=zone,
                    schedule={"code": code, "arrival": arrival, "departure": departure,
                              "arrival_min": self.minutes(arrival),
                              "departure_min": self.minutes(departure) if pd.notna(departure) else None},
                    moves=container_moves(r.teu, self.rng), cranes_wanted=cranes_for(r.teu))
        if zone:
            ship.dwell_h = (r.departure - r.arrival).total_seconds() / 3600 if pd.notna(r.departure) else 24.0
        return ship

    def _containers_nhpp(self, t0, dt):
        """Container ships entering in [t0, t0 + dt): berth arrivals ENTRY_LEAD_H later at the fitted rate."""
        f = self.nhpp
        berth = self._utc(self.start + pd.Timedelta(minutes=t0 + ENTRY_LEAD_H * 60))
        local = berth.tz_convert(SCHEDULE_TZ)
        day = local.normalize()
        if day not in self.day_factor:
            k = f["gamma_shape"]
            self.day_factor[day] = self.rng.gamma(k, 1.0 / k) if k else 1.0
        lam = (f["base_per_h"] * f["weekday"][local.dayofweek] * f["hour"][local.hour] * self.day_factor[day]
               * f["rate_factor"] * dt / 60.0)
        out = []
        for _ in range(self.rng.poisson(lam)):
            r = self.calls.iloc[int(self.rng.integers(len(self.calls)))]
            u = float(self.rng.uniform(0, dt))
            berth_t = berth + pd.Timedelta(minutes=u)
            stay = r.departure - r.arrival if pd.notna(r.departure) else None
            ship = self._container(r, berth_t, berth_t + stay if stay is not None else pd.NaT, berth_t)
            ship.spawn_t = t0 + u
            out.append(ship)
        return out

    @staticmethod
    def _utc(ts):
        return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")

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
        if self.nhpp is not None:
            out += self._containers_nhpp(t0, dt)
        if self.background:
            out += self._background(t0, dt)
        return out
