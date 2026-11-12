"""Ship generation (PLAN.md §3).

Level 1, container ships, mode "replay" (default): replay of the schedule CSV. Each line gives the vessel, TEU, the
scheduled berth arrival / departure (Europe/Brussels time) and the terminal code. TEU gives the
dimensions (container_calls.dimensions_for_teu, with the fitted residual noise) and the cranes; the
scheduled stay (departure - arrival) gives the call size (engine._start_handling). With delays=True the berth arrival is shifted by a delay drawn from the AIS
(container_calls.SCHEDULE_DELAY_H). The ship enters the area ENTRY_LEAD_H before that, at a sea
source drawn from entry_probabilities.

Level 1, mode "nhpp": a non-homogeneous Poisson process fitted to the schedule (fit_container_nhpp):
berth arrivals at rate base x weekday factor x hour-of-day factor (Brussels time), and, because liner
calls bunch (the schedule's calls per day vary twice as much as Poisson), each day's rate times a
gamma factor of mean 1 (a Cox process) fitted to that extra variance. Each arrival is one schedule
line drawn at random (TEU, terminal code, scheduled time at berth together), entering ENTRY_LEAD_H
before its berth time. rate_factor scales the rate (scenarios). Runs need not lie inside the
schedule's dates.

Level 1, mode "weeks": a schedule made for the run from whole weeks of the real one (_week). Week k of the
run is a real week drawn at random, its calls moved to that week with their weekday, hour, ship, terminal and
stay. Liner services are weekly, so a real week is a set of calls that fits the quays; calls drawn one by one
(mode "nhpp") overlap at a terminal as a planned schedule never does. With delays the berth time is
shifted as in replay mode. The berth plan is then made again on paper: a call that finds the quay full for any
part of its stay (the lengths of the ships at the terminal against its quay) is moved to when a ship there has
left. That covers two weeks joining with a ship still at the quay, and a late ship meeting the next one. Runs of any length and any start date.

Level 2, background traffic: a non-homogeneous Poisson process per class and entry source,
rate = entry_probabilities.RATE_PER_HOUR x HOURLY_FACTOR(hour of day). Attributes are whole AIS
ships that went to that destination (background_traffic.sample_attributes), the destination depends on
class and source.

Two random streams: rng draws when ships arrive (counts, times, the daily factor, schedule delays), and
rng_attributes what they are (schedule line, dimensions, source, destination, AIS ship). Two runs with the same
seed then have the same arrivals whatever else differs between them (common random numbers).
"""

from __future__ import annotations

import csv
import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ship import Ship, cranes_for

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "data"))
import background_traffic as BT          # noqa: E402
import container_calls as CC             # noqa: E402
import entry_probabilities as EP         # noqa: E402

SCHEDULES = ROOT / "data" / "schedules"     # every schedule file in it, together (they follow on each other)
SCHEDULE = SCHEDULES
WEEK_MIN = 7 * 24 * 60.0
WEEK_AHEAD_MIN = 5 * 24 * 60.0             # a week's calls are made this long before it starts (early ships enter before it)
QUAY_GAP_M = 22.5                          # between two ships at a quay (terminals.MOORING_GAP_M), for the paper check
SCHEDULE_TZ = "Europe/Brussels"
SCHEDULE_YEAR = 2026
ENTRY_LEAD_H = 8.0                  # enter the area this long before the berth time
# schedule terminal code -> Terminal (graph.graph["terminals"]); other codes berth in a dock zone
TERMINAL_OF_CODE = {"1700": "DP World Antwerp Gateway", "K1742": "MPET", "K1718": "MPET",
                    "K913": "PSA Noordzee Terminal", "K869": "PSA Europa Terminal"}
# the TEU fit's scatter can exceed any real ship: the largest container ships are 400 x 61.5 m
MAX_LOA_M, MAX_BEAM_M = 400.0, 61.5
BACKGROUND_CLASSES = ("bulk_general", "tanker", "inland_cargo", "inland_tanker", "passenger")
# Inland arrivals are scaled to Rijkswaterstaat's lock counts: commercial passages a day at Kreekrak 189 and
# Hansweert 113 (NMCA 2017, 69,058 and 41,112 a year) and Terneuzen 126 (IVS90 2018, Deltares 2021), 428 in all,
# 11 of them sea-going ships in the model. The AIS rates give 311 inland passages a day there (fits of 12 Nov
# 2026, three 21-day runs: 447 with the factor 1.44 of the fits before, 194, 116 and 137 at the three locks), so
# the factor is (428 - 11) / 311. The AIS hears an inland craft in about a third of its snapshots and misses
# trips out and back; the gap is alike at the three locks. The inland stays are divided by the same factor
# (engine), so that the craft lying in port stay at the AIS number. Set again after every re-fit of the rates
# (the run's summary gives the passages a day per lock).
INLAND_TRIP_SCALE = round((428 - 11) / 311, 2)
INLAND_CLASSES = ("inland_cargo", "inland_tanker")
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
    """The schedule: one CSV, or every CSV of a folder together, in order of arrival."""
    path = Path(path)
    rows = []
    for file in (sorted(path.glob("*.csv")) if path.is_dir() else [path]):
        with open(file, encoding="utf-8-sig") as f:
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
    df = df[df.arrival.notna() & df.teu.notna()]
    return df.sort_values("arrival", kind="stable").reset_index(drop=True)


class Generator:
    def __init__(self, start, rng, delays=True, schedule=SCHEDULE, background=True, containers=True,
                 container_mode="replay", rate_factor=1.0, bunching=True, rng_attributes=None, quay_m=None):
        self.start = pd.Timestamp(start)
        self.rng = rng
        self.rng_att = rng if rng_attributes is None else rng_attributes
        self.delays = delays
        self.background = background
        self.counter = itertools.count(1)
        self.pending = []
        self.nhpp = None
        self.weeks = None
        if containers:
            df = read_schedule(schedule)
            known = df.terminal[df.terminal != ""]
            self.codes = known.value_counts(normalize=True)
            # scheduled stays (h) by ship size, for the lines without a departure time
            stay = (df.departure - df.arrival).dt.total_seconds() / 3600
            self.stays = {b: stay[(df.teu.map(cranes_for) == b) & stay.notna()].to_numpy() for b in set(df.teu.map(cranes_for))}
            self.stays_all = stay[stay.notna()].to_numpy()
            if container_mode == "replay":
                self._schedule(df, quay_m or {})
            elif container_mode == "nhpp":
                self.calls = df.reset_index(drop=True)
                self.nhpp = fit_container_nhpp(df)
                self.nhpp["rate_factor"] = rate_factor
                if not bunching:
                    self.nhpp["gamma_shape"] = None
                self.day_factor = {}
            elif container_mode == "weeks":
                self._prepare_weeks(df, quay_m or {})
            else:
                raise ValueError(f"container_mode {container_mode!r}: 'replay', 'weeks' or 'nhpp'")
        self.median_draught = {c: float(np.nanmedian([r[2] for r in BT.ATTRIBUTES[c] if r[2]]))
                               for c in BACKGROUND_CLASSES}

    def minutes(self, ts):
        return (ts - self.start).total_seconds() / 60.0

    # ------------------------------------------------------------------ containers
    def _schedule(self, df, quay_m):
        """Replay: every schedule line is one ship. The berth plan is made again on paper with the delays, as
        in weeks mode (_plan_berth), where the terminal's quay is known."""
        self.replay = {"plan": {}, "moved": 0, "moved_h": 0.0}
        for r in df.itertuples():
            berth_t = r.arrival + pd.Timedelta(hours=CC.sample_arrival_delay(self.rng) if self.delays else 0.0)
            quay = TERMINAL_OF_CODE.get(r.terminal)
            if quay in quay_m and pd.notna(r.departure):
                wanted = berth_t
                berth_t = self._plan_berth(self.replay["plan"].setdefault(quay, []), berth_t, r.departure - r.arrival,
                                           CC.dimensions_for_teu(r.teu)["loa"] + QUAY_GAP_M, quay_m[quay])
                if berth_t > wanted:
                    self.replay["moved"] += 1
                    self.replay["moved_h"] += (berth_t - wanted).total_seconds() / 3600
            ship = self._container(r, r.arrival, r.departure, berth_t)
            if ship.spawn_t < 0:             # due before the run starts: the warm-up replaces it
                continue
            self.pending.append(ship)
        self.pending.sort(key=lambda s: s.spawn_t)

    # ------------------------------------------------------------------ a schedule from whole weeks
    def _prepare_weeks(self, df, quay_m):
        """The whole weeks of the schedule (from the day of its first call; a last part-week is left out), and
        per terminal the quay the paper check allows: its quay (quay_m, from the engine) or, if that is more,
        the most the real schedule itself has there at once by the same count."""
        tz = SCHEDULE_TZ
        # in local clock time (no time zone): a call keeps its weekday and hour across a change of the clocks
        local = df.arrival.dt.tz_convert(tz).dt.tz_localize(None)
        first = local.min().normalize()
        n = int((local.max() - first) / pd.Timedelta(days=7))
        if n < 1:
            raise ValueError("the schedule covers less than one week")
        week = ((local - first) / pd.Timedelta(days=7)).astype(int)
        df = df[week < n].assign(week=week[week < n], offset=local - first - pd.to_timedelta(week * 7, unit="D"))
        stay = df.departure - df.arrival
        df = df.assign(stay=stay, metres=[CC.dimensions_for_teu(t)["loa"] + QUAY_GAP_M for t in df.teu],
                       quay=df.terminal.map(TERMINAL_OF_CODE))
        start_day = self.start.tz_convert(tz).tz_localize(None).normalize()
        back = (start_day.dayofweek - first.dayofweek) % 7
        peak = {}
        for name, g in df[df.quay.notna() & df.stay.notna()].groupby("quay"):
            events = sorted([(a, m) for a, m in zip(g.arrival, g.metres)] + [(a + s, -m) for a, s, m in zip(g.arrival, g.stay, g.metres)])
            used = top = 0.0
            for _, m in events:
                used += m
                top = max(top, used)
            peak[name] = top
        self.weeks = {"calls": df, "n": n, "week0": start_day - pd.Timedelta(days=back),
                      "quay": {k: quay_m.get(k) or v for k, v in peak.items()}, "plan": {}, "made": 0,
                      "drawn": [], "moved": 0, "moved_h": 0.0}
        self._weeks_until(0.0)

    def _weeks_until(self, t0):
        """Make the calls of every run week that starts within WEEK_AHEAD_MIN of t0."""
        w = self.weeks
        while self.minutes(self._utc_of(w["week0"] + pd.Timedelta(days=7 * w["made"]))) <= t0 + WEEK_AHEAD_MIN:
            self._week(w["made"])
            w["made"] += 1
        self.pending.sort(key=lambda s: s.spawn_t)

    def _week(self, k):
        w = self.weeks
        source = int(self.rng.integers(w["n"]))
        w["drawn"].append(source)
        begin = w["week0"] + pd.Timedelta(days=7 * k)
        old = begin - pd.Timedelta(days=14)
        for r in w["calls"][w["calls"].week == source].itertuples():
            arrival = self._utc_of(begin + r.offset)
            departure = arrival + r.stay if pd.notna(r.stay) else pd.NaT
            berth_t = arrival + pd.Timedelta(hours=CC.sample_arrival_delay(self.rng) if self.delays else 0.0)
            if pd.notna(r.quay) and pd.notna(r.stay):
                plan = w["plan"].setdefault(r.quay, [])
                plan[:] = [p for p in plan if p[1] > self._utc_of(old)]
                wanted = berth_t
                berth_t = self._plan_berth(plan, berth_t, r.stay, r.metres, w["quay"][r.quay])
                if berth_t > wanted:
                    w["moved"] += 1
                    w["moved_h"] += (berth_t - wanted).total_seconds() / 3600
            ship = self._container(r, arrival, departure, berth_t)
            if ship.spawn_t >= 0:                           # due before the run starts: the warm-up replaces it
                self.pending.append(ship)

    @staticmethod
    def _plan_berth(plan, berth_t, stay, metres, quay_m):
        """The berth plan on paper, made again with the ships as late as they are: a call that finds the quay
        full for any part of its stay (the lengths of the ships there, with their gaps, against the quay) is
        moved to when a ship there has left. plan: the terminal's [(from, until, metres)], added to. Returns the
        berth time."""
        while True:
            over = [p for p in plan if p[0] < berth_t + stay and p[1] > berth_t]
            at = [berth_t] + [p[0] for p in over if p[0] > berth_t]
            if all(sum(p[2] for p in over if p[0] <= t < p[1]) + metres <= quay_m for t in at):
                break
            berth_t = min(p[1] for p in over)
        plan.append((berth_t, berth_t + stay, metres))
        return berth_t

    @staticmethod
    def _utc_of(local):
        """A local clock time of the schedule's time zone as UTC."""
        return local.tz_localize(SCHEDULE_TZ, ambiguous=True, nonexistent="shift_forward").tz_convert("UTC")

    def _container(self, r, arrival, departure, berth_t):
        """A container ship for schedule line r berthing at berth_t, with its scheduled arrival / departure."""
        code = r.terminal or self.rng_att.choice(self.codes.index, p=self.codes.to_numpy())    # missing code: drawn
        spawn = self.minutes(berth_t) - ENTRY_LEAD_H * 60
        dims = CC.dimensions_for_teu(r.teu, self.rng_att)
        if pd.notna(departure):
            stay_h = (departure - arrival).total_seconds() / 3600
        else:                                # no departure in the schedule: the stay of a call of its size
            pool = self.stays.get(cranes_for(r.teu))
            pool = pool if pool is not None and len(pool) else self.stays_all
            stay_h = float(pool[int(self.rng_att.integers(len(pool)))])
        zone = None
        if code not in TERMINAL_OF_CODE:
            zones = CC.TERMINAL_LOCATION.get(code, {}).get("zones") or {"antwerp_right_bank_docks": 1.0}
            zone = max(zones, key=zones.get)
        ship = Ship(id=f"C{next(self.counter):04d}", cls="container", loa=round(min(dims["loa"], MAX_LOA_M), 1),
                    beam=round(min(dims["beam"], MAX_BEAM_M), 1), draught=round(min(dims["draught"], 16.0), 2), level=1,
                    source=EP.sample_source("container", self.rng_att, category="sea"),
                    destination=zone or "antwerp_terminal", spawn_t=spawn, teu=float(r.teu), name=r.vessel,
                    terminal=TERMINAL_OF_CODE.get(code), berth_zone=zone,
                    schedule={"code": code, "arrival": arrival, "departure": departure,
                              "arrival_min": self.minutes(arrival),
                              "departure_min": self.minutes(departure) if pd.notna(departure) else None,
                              # when it is to berth: the schedule and its delay (the engine times its entry by it)
                              "berth_min": self.minutes(berth_t)},
                    stay_h=stay_h, cranes_wanted=cranes_for(r.teu))
        if zone:
            ship.dwell_h = stay_h
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
            r = self.calls.iloc[int(self.rng_att.integers(len(self.calls)))]
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
                if cls in INLAND_CLASSES:
                    lam *= INLAND_TRIP_SCALE
                for _ in range(self.rng.poisson(lam)):
                    dest = BT.sample_destination(cls, self.rng_att, source)
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
            a = BT.sample_attributes(cls, self.rng_att, dest)
            loa = float(a["loa"])
            beam = float(a["beam"] or loa / 7)
            if all(loa <= L and beam <= B for L, B in limits):
                return a
        return a

    def arrivals(self, t0, dt):
        """Ships entering in [t0, t0 + dt) minutes."""
        out = []
        if self.weeks is not None:
            self._weeks_until(t0)
        while self.pending and self.pending[0].spawn_t < t0 + dt:
            out.append(self.pending.pop(0))
        if self.nhpp is not None:
            out += self._containers_nhpp(t0, dt)
        if self.background:
            out += self._background(t0, dt)
        return out
