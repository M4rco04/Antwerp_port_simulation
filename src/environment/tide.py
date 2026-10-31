"""Water levels for the simulation (PLAN.md §5.3): astronomical tide + wind surge, per gauge and
per graph node, and tidal windows for a planned route.

All levels are metres above LAT (chart datum), so a graph edge is passable when
    edge["depth_m"] + level >= draught + UKC

    model = TideModel.load()
    model.levels(times)                       DataFrame time x gauge: tide only
    model.levels(times, weather)              ... + the surge from hourly weather (wind, pressure)
    model.sample_weather(start, hours, rng)   hourly weather from the fitted Markov chain
    model.surge_noise(times, rng)             AR(1) surge error, for stochastic runs
    node_level(graph, node, row)              level at a node from one row of model.levels()
    tidal_window(graph, path, model, ...)     departure times at which a route has enough water

Tidal nodes take their level from the two gauges either side of them along the estuary (node
attribute "tide" = (gauge_a, gauge_b, weight_b)); nodes in a basin behind locks (attribute
"basin") keep that basin's fixed level from BASIN_LEVELS_NAP_M.
"""

from __future__ import annotations

import math
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_FILE = PROJECT_ROOT / "data" / "tides" / "tide_model.pkl"

# Belgian TAW zero lies about 2.33 m below Dutch NAP zero: z_NAP = z_TAW - TAW_BELOW_NAP_M
TAW_BELOW_NAP_M = 2.33
# Water levels kept in the basins behind locks (m above NAP). Approximate: replace with the
# managed levels (Antwerp docks ~TAW +4.3 m; Ghent-Terneuzen canal ~NAP +2.13 m).
BASIN_LEVELS_NAP_M = {
    "antwerp": 4.30 - TAW_BELOW_NAP_M,
    "ghent_terneuzen_canal": 2.13,
    "zuid_beveland_canal": 0.0,
    "schelde_rijn_canal": 0.0,
    "vlissingen": 0.0,
}
KNOT = 1852.0 / 3600.0


def basin_key(basin):
    return "antwerp" if basin.startswith("antwerp") else basin


class TideModel:
    def __init__(self, data):
        self.data = data
        self.gauges = list(data["gauges"])

    @classmethod
    def load(cls, path=MODEL_FILE):
        with open(path, "rb") as f:
            return cls(pickle.load(f))

    # -- datums -----------------------------------------------------------------------------

    def lat_nap_m(self, gauge):
        """LAT of a gauge in m above NAP (negative: LAT is below NAP)."""
        return self.data["gauges"][gauge]["lat_nap_cm"] / 100.0

    def taw_to_lat_depth(self, depth_below_taw_m, gauge):
        """A depth below TAW (e.g. a lock sill) as a depth below the gauge's LAT."""
        return depth_below_taw_m + self.lat_nap_m(gauge) + TAW_BELOW_NAP_M

    def basin_level_m(self, basin, gauge):
        """The fixed level of a basin behind locks, in m above the nearest gauge's LAT."""
        return BASIN_LEVELS_NAP_M.get(basin_key(basin), 0.0) - self.lat_nap_m(gauge)

    # -- tide and surge ----------------------------------------------------------------------

    def tide(self, gauge, times):
        """Astronomical tide at a gauge, m above LAT."""
        import utide

        g = self.data["gauges"][gauge]
        h = utide.reconstruct(pd.DatetimeIndex(times), g["coef"], verbose=False).h
        return h / 100.0 - self.lat_nap_m(gauge)

    def surge(self, gauge, weather):
        """Surge (m) at a gauge for hourly weather (columns speed m/s, direction deg from,
        pressure hPa, indexed by UTC time); needs 24 h of weather before the first hour."""
        model = self.data["surge"][gauge]
        rad = np.radians(weather.direction)
        tx, ty = -weather.speed ** 2 * np.sin(rad), -weather.speed ** 2 * np.cos(rad)
        cols = {}
        for lag in self.data["surge_lags_h"]:
            cols[f"tx_{lag}"], cols[f"ty_{lag}"] = tx.shift(lag), ty.shift(lag)
        for lag in self.data["pressure_lags_h"]:
            cols[f"p_{lag}"] = (1013.0 - weather.pressure).shift(lag)
        X = pd.DataFrame(cols)[model["columns"]]
        return pd.Series((model["beta"][0] + X.to_numpy() @ model["beta"][1:]) / 100.0, index=weather.index)

    def levels(self, times, weather=None, noise=None):
        """Water level (m above LAT) at every gauge: tide, plus the surge when hourly weather is
        given (interpolated to the times), plus optional noise (DataFrame like the result)."""
        times = pd.DatetimeIndex(times)
        out = pd.DataFrame({g: self.tide(g, times) for g in self.gauges}, index=times)
        if weather is not None:
            for g in self.gauges:
                s = self.surge(g, weather).dropna()
                out[g] += np.interp(times.asi8, s.index.asi8, s.to_numpy())
        if noise is not None:
            out += noise.reindex(times).fillna(0.0)
        return out

    def surge_noise(self, times, rng):
        """AR(1) surge error (m) per gauge on hourly steps, interpolated to the times."""
        times = pd.DatetimeIndex(times)
        hours = pd.date_range(times[0].floor("h"), times[-1].ceil("h"), freq="1h")
        out = {}
        for g in self.gauges:
            m = self.data["surge"][g]
            e = np.zeros(len(hours))
            e[0] = rng.normal(0.0, m["error_std_cm"])
            for i in range(1, len(hours)):
                e[i] = m["phi"] * e[i - 1] + rng.normal(0.0, m["sigma_cm"])
            out[g] = np.interp(times.asi8, hours.asi8, e / 100.0)
        return pd.DataFrame(out, index=times)

    # -- weather -----------------------------------------------------------------------------

    def sample_weather(self, start, hours, rng, state=None):
        """Hourly weather from the Markov chain: speed (m/s), direction (deg from), pressure (hPa),
        VV (KNMI visibility code) and the chain state; starts in a random state if none given."""
        chain = self.data["weather_chain"]
        P = chain["transition"]
        n = len(P)
        if state is None:
            state = rng.choice(n, p=chain["state_frequency"])
        rows, states = [], []
        for _ in range(hours):
            samples = chain["samples"][state]
            while samples is None:                       # never observed: jump to a seen state
                state = rng.choice(n, p=chain["state_frequency"])
                samples = chain["samples"][state]
            rows.append(samples[rng.integers(len(samples))])
            states.append(state)
            state = rng.choice(n, p=P[state])
        index = pd.date_range(pd.Timestamp(start).floor("h"), periods=hours, freq="1h")
        df = pd.DataFrame(rows, columns=["speed", "direction", "pressure", "VV"], index=index)
        df["state"] = states
        return df


# ---------------------------------------------------------------------------
# graph


def node_level(graph, node, row, model=None):
    """Water level (m above LAT) at a graph node for one time: row = one row of model.levels()."""
    data = graph.nodes[node]
    tide = data.get("tide")
    if tide is not None:
        a, b, w = tide
        return (1.0 - w) * row[a] + w * row[b]
    if model is not None and data.get("basin"):
        return model.basin_level_m(data["basin"], data.get("tide_gauge") or "antwerpen.loodsgebouw")
    return 0.0


def node_levels(graph, levels, model):
    """Water level at every node for every time in levels: array (n_times, n_nodes), node order
    as graph.nodes."""
    cols = {g: i for i, g in enumerate(levels.columns)}
    L = levels.to_numpy()
    out = np.zeros((len(levels), graph.number_of_nodes()))
    for j, (n, d) in enumerate(graph.nodes(data=True)):
        if d.get("tide") is not None:
            a, b, w = d["tide"]
            out[:, j] = (1.0 - w) * L[:, cols[a]] + w * L[:, cols[b]]
        elif d.get("basin"):
            out[:, j] = model.basin_level_m(d["basin"], d.get("tide_gauge") or "antwerpen.loodsgebouw")
    return out


def tidal_window(graph, path, model, departures, speed_kn, draught_m, ukc_m=0.0, weather=None):
    """For each departure time, whether the ship (sailing the path at speed_kn) finds enough water
    on every edge when it gets there. Returns a Series of bool indexed by departure time."""
    departures = pd.DatetimeIndex(departures)
    xy = np.array([(graph.nodes[n]["x"], graph.nodes[n]["y"]) for n in path])
    arrive_s = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]) / (speed_kn * KNOT)
    span = pd.date_range(departures[0], departures[-1] + pd.Timedelta(seconds=float(arrive_s[-1])) + pd.Timedelta("10min"),
                         freq="5min")
    levels = model.levels(span, weather)
    L = levels.to_numpy()
    col = {g: i for i, g in enumerate(levels.columns)}
    # each path node's level = (1 - w) * gauge a + w * gauge b + constant (basins behind locks)
    ia, ib, w, const = [], [], [], []
    for n in path:
        d = graph.nodes[n]
        if d.get("tide") is not None:
            a, b, wb = d["tide"]
            ia.append(col[a]); ib.append(col[b]); w.append(wb); const.append(0.0)
        else:
            ia.append(0); ib.append(0); w.append(np.nan)
            const.append(model.basin_level_m(d["basin"], d.get("tide_gauge") or "antwerpen.loodsgebouw") if d.get("basin") else 0.0)
    ia, ib, w, const = map(np.array, (ia, ib, w, const))
    tidal = ~np.isnan(w)
    w = np.nan_to_num(w)
    depth = np.array([graph.edges[u, v]["depth_m"] for u, v in zip(path, path[1:])])
    step = (span[1] - span[0]).total_seconds()
    rows = np.clip(((departures - span[0]).total_seconds().to_numpy()[:, None] + arrive_s[None, :]) / step, 0,
                   len(span) - 1).round().astype(int)                  # (departures, path nodes)
    level = np.where(tidal, (1.0 - w) * L[rows, ia] + w * L[rows, ib], const)
    ok = np.all(depth[None, :] + np.minimum(level[:, :-1], level[:, 1:]) >= draught_m + ukc_m, axis=1)
    return pd.Series(ok, index=departures)
