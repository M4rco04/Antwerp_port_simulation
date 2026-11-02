"""Weather for the simulation: hourly wind, gusts, direction, pressure and visibility (PLAN.md §5.3).

The KNMI hourly observations at Vlissingen (station 310, data/weather/knmi_310.csv.gz, fetched by
fetch_tide_data.py) are resampled in whole days (block bootstrap): each simulated day is a real day
drawn from the same season (within SEASON_DAYS of the date, any year), so fog that lasts the night,
storms that last a day, the daily cycle and the link between wind, gusts, pressure and visibility
are all kept. mode="replay" uses the observed hours of the simulated dates instead (only where the
record has them).

    w = Weather.generate(start, hours, rng)
    w.at(t)            -> the hour's row: wind_ms (10-min mean), gust_ms, direction, pressure,
                          visibility_m, bft
    w.max_bft(t0, t1)  -> the highest Beaufort force between two times
    w.surge_input      -> hourly speed / direction / pressure as TideModel.surge wants it

KNMI fields: FF 10-minute mean wind (0.1 m/s), FH hourly mean wind, FX highest gust, DD direction
(990 variable), P pressure (0.1 hPa), VV visibility code (0-49: x 100 m, 56-79: (VV - 50) km,
80-89: 30 km + (VV - 80) x 5 km).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
KNMI = ROOT / "data" / "weather" / "knmi_310.csv.gz"
SEASON_DAYS = 45
BFT_UPPER_MS = (0.3, 1.6, 3.4, 5.5, 8.0, 10.8, 13.9, 17.2, 20.8, 24.5, 28.5, 32.7)


def beaufort(ms):
    return np.searchsorted(BFT_UPPER_MS, np.asarray(ms), side="right")


def visibility_m(vv):
    vv = np.asarray(vv, dtype=float)
    out = np.where(vv < 50, np.maximum(vv, 0.5) * 100.0, np.nan)
    out = np.where(vv == 50, 5000.0, out)
    out = np.where((vv >= 56) & (vv <= 79), (vv - 50) * 1000.0, out)
    out = np.where(vv >= 80, 30000.0 + (vv - 80) * 5000.0, out)
    return out


def load_observations(path=KNMI):
    w = pd.read_csv(path, index_col=0, parse_dates=True)
    w = w[~w.index.duplicated()].sort_index()
    calm = (w.DD == 0) | (w.DD == 990)
    out = pd.DataFrame(index=w.index)
    out["wind_ms"] = (w.FF / 10.0).fillna(w.FH / 10.0)
    out["hourly_ms"] = w.FH / 10.0
    out["gust_ms"] = (w.FX / 10.0).fillna(out.wind_ms * 1.5)
    out["direction"] = w.DD.where(~calm).ffill().fillna(0.0)
    out["pressure"] = (w.P / 10.0).ffill()
    out["visibility_m"] = pd.Series(visibility_m(w.VV.ffill()), index=w.index).ffill()
    return out.dropna(subset=["wind_ms"])


class Weather:
    def __init__(self, hourly):
        self.hourly = hourly
        self.hourly["bft"] = beaufort(hourly.wind_ms)

    @classmethod
    def generate(cls, start, hours, rng, mode="bootstrap", lead_hours=48):
        """Hourly weather from lead_hours before start (the surge needs the wind before) to start + hours."""
        obs = load_observations()
        t0 = pd.Timestamp(start).floor("h") - pd.Timedelta(hours=lead_hours)
        index = pd.date_range(t0, periods=hours + lead_hours + 1, freq="1h")
        if mode == "replay":
            got = obs.reindex(index)
            if got.wind_ms.isna().mean() > 0.05:
                raise ValueError("the KNMI record does not cover the simulated period: use mode='bootstrap'")
            return cls(got.ffill())
        days = obs.groupby(obs.index.normalize())
        complete = {d: g for d, g in days if len(g) >= 24}
        doy = np.array([d.dayofyear for d in complete])
        keys = list(complete)
        parts = []
        for day in pd.date_range(index[0].normalize(), index[-1].normalize(), freq="1D"):
            gap = np.abs((doy - day.dayofyear + 182) % 365 - 182)
            pool = [k for k, g in zip(keys, gap) if g <= SEASON_DAYS]
            block = complete[pool[int(rng.integers(len(pool)))]].iloc[:24].copy()
            block.index = pd.date_range(day, periods=len(block), freq="1h", tz=index.tz)
            parts.append(block)
        return cls(pd.concat(parts).reindex(index).ffill().bfill())

    def at(self, t):
        i = min(max(self.hourly.index.searchsorted(pd.Timestamp(t), side="right") - 1, 0), len(self.hourly) - 1)
        return self.hourly.iloc[i]

    def max_bft(self, t0, t1):
        w = self.hourly.loc[pd.Timestamp(t0).floor("h"):pd.Timestamp(t1)]
        return int(w.bft.max()) if len(w) else int(self.at(t0).bft)

    @property
    def surge_input(self):
        """Hourly speed (m/s), direction and pressure, as TideModel.surge reads them."""
        return pd.DataFrame({"speed": self.hourly.hourly_ms.fillna(self.hourly.wind_ms),
                             "direction": self.hourly.direction, "pressure": self.hourly.pressure}, index=self.hourly.index)
