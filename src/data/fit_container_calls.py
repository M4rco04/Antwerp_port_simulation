"""Fit the container-ship distributions (PLAN.md §1 level 1, §3, §8) from AIS + the schedule CSV.

    TEU_DIMENSIONS     TEU -> LOA, beam, draught: power laws (log-log regressions) fitted on the
                       ships of the schedule seen in AIS, with correlated lognormal residuals
    SCHEDULE_DELAY_H   actual berth arrival / departure (start / end of the AIS berth stop in
                       Antwerp) minus the scheduled Arrival / Departure
    ENTRY_TO_BERTH_H   hours from entering the area (sea edge or anchorage) to berthing,
                       to know when to release a ship that should berth at its scheduled time
    TERMINAL_LOCATION  where the ships of each schedule terminal code actually berth

The schedule times are read as Europe/Brussels local time.

The result is written as a plain Python module (default src/data/container_calls.py).

Usage:
    py src/data/fit_container_calls.py
"""
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ais_pipeline import (AIS_DIR, BERTHS, CHARTS, REPO_ROOT, SCHEDULE, berth_calls, find_stops, normalise,
                          normalise_name, prepare, write_module)

log = logging.getLogger("container")

SCHEDULE_TZ = "Europe/Brussels"
SCHEDULE_YEAR = 2026
# a port call belongs to a schedule line if it starts this close to the scheduled arrival
# (wide: ships run a day or two late, and a ship calls Antwerp at most about weekly)
MATCH_WINDOW_H = 96
# berth stops in Antwerp this close together are one port call (shifting berth)
SHIFT_MAX_H = 3
DIMENSIONS = {"loa": "length", "beam": "width", "draught": "draught"}


def parse_schedule_time(values):
    local = pd.to_datetime(values + f" {SCHEDULE_YEAR}", format="%b %d, %I %p %Y", errors="coerce")
    # the 02:00-03:00 hour on the night summer time ends happens twice; take the first
    return local.dt.tz_localize(SCHEDULE_TZ, ambiguous=np.ones(len(local), dtype=bool)).dt.tz_convert("UTC")


def schedule_ships(schedule, ships):
    """AIS container ships of the schedule, with their (median) TEU."""
    teu = schedule.assign(key=schedule.Vessel.map(normalise_name)).groupby("key").TEU.median()
    container = ships[ships["class"] == "container"].copy()
    container["teu"] = container.name.map(normalise_name).map(teu)
    return container[container.teu.notna()]


def fit_dimensions(container):
    """log(dimension) = a + b log(TEU) per dimension, plus the covariance of the residuals."""
    rows = container[["teu"] + list(DIMENSIONS.values())].dropna()
    rows = rows[(rows > 0).all(axis=1)]
    log_teu = np.log(rows.teu.to_numpy())
    model, residuals = {}, []
    for dim, column in DIMENSIONS.items():
        y = np.log(rows[column].to_numpy(dtype=float))
        b, a = np.polyfit(log_teu, y, 1)
        resid = y - (a + b * log_teu)
        residuals.append(resid)
        model[dim] = {"a": round(float(a), 5), "b": round(float(b), 5),
                      "r2": round(float(1 - resid.var() / y.var()), 3)}
    cov = np.cov(np.vstack(residuals))
    table = sorted((int(r.teu), int(r.length), int(r.width), round(float(r.draught), 1)) for r in rows.itertuples())
    return {
        "model": model,
        "residual_cov": [[round(float(v), 6) for v in row] for row in cov],
        "residual_cholesky": [[round(float(v), 6) for v in row] for row in np.linalg.cholesky(cov)],
        "n": len(rows), "teu_range": [int(rows.teu.min()), int(rows.teu.max())],
        "observed": table,
    }


def summary(hours):
    h = pd.Series(hours, dtype=float).dropna()
    if h.empty:
        return {"n": 0}
    return {"n": len(h), "mean_h": round(float(h.mean()), 2), "median_h": round(float(h.median()), 2),
            "sd_h": round(float(h.std()), 2) if len(h) > 1 else 0.0,
            "p10_h": round(float(h.quantile(0.1)), 2), "p90_h": round(float(h.quantile(0.9)), 2),
            "values": [round(float(v), 1) for v in sorted(h)]}


def port_calls(calls):
    """Antwerp berth calls of a visit, with berth shifts merged into one call that keeps the zone
    of its longest part, the start of the first and the end of the last."""
    antwerp = calls[calls.zone.str.startswith("antwerp_")].sort_values(["visit", "start"])
    gap_h = (antwerp.start - antwerp.end.shift()).dt.total_seconds().div(3600)
    new = (antwerp.visit != antwerp.visit.shift()) | (gap_h > SHIFT_MAX_H)
    rows = []
    for _, g in antwerp.groupby(new.cumsum()):
        first, last, main = g.iloc[0], g.iloc[-1], g.loc[g.hours.idxmax()]
        rows.append({"visit": first.visit, "mmsi": first.mmsi, "zone": main.zone, "lat": main.lat, "lon": main.lon,
                     "start": first.start, "end": last.end, "start_observed": first.start_observed,
                     "end_observed": last.end_observed, "at_visit_start": first.at_visit_start})
    return pd.DataFrame(rows)


def match_schedule(schedule, container, calls, times):
    """Each schedule line in the AIS period paired with the nearest Antwerp port call of that ship."""
    lines = schedule.assign(key=schedule.Vessel.map(normalise_name),
                            arrival=parse_schedule_time(schedule.Arrival),
                            departure=parse_schedule_time(schedule.Departure))
    lo, hi = times.iloc[0] - pd.Timedelta(hours=MATCH_WINDOW_H), times.iloc[-1] + pd.Timedelta(hours=MATCH_WINDOW_H)
    lines = lines[lines.arrival.between(lo, hi)]
    mmsis = container.groupby(container.name.map(normalise_name)).apply(lambda g: list(g.index))
    rows = []
    for line in lines.itertuples():
        cand = calls[calls.mmsi.isin(mmsis.get(line.key, []))]
        if cand.empty:
            continue
        off = (cand.start - line.arrival).dt.total_seconds().div(3600)
        if off.abs().min() > MATCH_WINDOW_H:
            continue
        call = cand.loc[off.abs().idxmin()]
        rows.append({"vessel": line.Vessel, "terminal": line.Terminal, "zone": call.zone,
                     "lat": call.lat, "lon": call.lon,
                     "arrival_delay_h": off.loc[call.name] if call.start_observed else np.nan,
                     "departure_delay_h": ((call.end - line.departure).total_seconds() / 3600
                                           if call.end_observed and pd.notna(line.departure) else np.nan)})
    matched = pd.DataFrame(rows)
    log.info("%d schedule lines in the AIS period, %d matched to a berth call", len(lines), len(matched))
    return matched


def entry_to_berth(entries, calls, catalogue):
    """Hours from entry to the first Antwerp berth call, per entry category (sea / anchorage)."""
    seen = calls[calls.start_observed & ~calls.at_visit_start]
    first = seen.sort_values("start").groupby("visit").start.first()
    e = entries[entries.scheldt_bound & (entries["class"] == "container") & entries.visit.isin(first.index)]
    hours = (e.visit.map(first) - e.t).dt.total_seconds().div(3600)
    category = e.source.map(lambda s: catalogue[s]["category"])
    return {cat: summary(hours[category == cat]) for cat in sorted(category.unique())}


def fit(data, stops):
    container = schedule_ships(data.schedule, data.ships)
    calls = port_calls(berth_calls(stops))
    matched = match_schedule(data.schedule, container, calls, data.times)
    terminals = {}
    for terminal, g in matched.dropna(subset=["terminal"]).groupby("terminal"):
        terminals[terminal] = {"lat": round(float(g.lat.median()), 5), "lon": round(float(g.lon.median()), 5),
                               "zones": normalise(g.zone.value_counts().to_dict()), "n": len(g)}
    return {
        "TEU_DIMENSIONS": fit_dimensions(container),
        "SCHEDULE_DELAY_H": {"arrival": summary(matched.arrival_delay_h),
                             "departure": summary(matched.departure_delay_h)},
        "ENTRY_TO_BERTH_H": entry_to_berth(data.entries, calls, data.zones.catalogue()),
        "TERMINAL_LOCATION": terminals,
    }


DOCSTRING = """Container-ship distributions, fitted from the AIS snapshots and the schedule CSV.

GENERATED by src/data/fit_container_calls.py, do not edit by hand. Re-run it when more AIS
data has been collected. Data: {n_snapshots} snapshots, {first} to {last} ({generated}).

TEU_DIMENSIONS     dimension = exp(a) * TEU**b for loa, beam, draught (m), fitted in logs on the
                   scheduled ships seen in AIS; residual_cov / residual_cholesky are the
                   covariance of the log residuals (loa, beam, draught), observed the raw rows
                   (TEU, LOA, beam, max reported draught)
SCHEDULE_DELAY_H   arrival / departure -> n, mean_h, median_h, sd_h, p10_h, p90_h, values:
                   actual berth arrival / departure minus the schedule (positive = late),
                   berth shifts within Antwerp counted as one call. Schedule times read as
                   {tz} local time; only delays within +-{window} h can be matched.
ENTRY_TO_BERTH_H   entry category (sea / anchorage) -> the same summary: hours from entering
                   the area to berthing in Antwerp (includes any anchorage wait)
TERMINAL_LOCATION  schedule terminal code -> median lat/lon of its berth calls, berth zones, n

Draught is the largest draught a ship reported in AIS (ships report their current draught,
not the design maximum). Small samples: check n before relying on the tails.
"""

MODULE_FUNCTIONS = '''

def _normals(rng, n):
    if hasattr(rng, "standard_normal"):
        return [float(v) for v in rng.standard_normal(n)]
    return [rng.gauss(0.0, 1.0) for _ in range(n)]


def dimensions_for_teu(teu, rng=None):
    """{"loa", "beam", "draught"} in m for a ship of this TEU: the fitted median, or a random
    ship around it (correlated residuals) when rng (numpy Generator / random.Random) is given."""
    import math

    model = TEU_DIMENSIONS["model"]
    dims = ("loa", "beam", "draught")
    log_dims = [model[d]["a"] + model[d]["b"] * math.log(teu) for d in dims]
    if rng is not None:
        z = _normals(rng, 3)
        chol = TEU_DIMENSIONS["residual_cholesky"]
        log_dims = [v + sum(chol[i][j] * z[j] for j in range(3)) for i, v in enumerate(log_dims)]
    return {d: math.exp(v) for d, v in zip(dims, log_dims)}


def _bootstrap(rng, values):
    return values[rng.integers(len(values)) if hasattr(rng, "integers") else rng.randrange(len(values))]


def sample_arrival_delay(rng):
    """Hours a ship berths after (positive) or before its scheduled arrival."""
    return _bootstrap(rng, SCHEDULE_DELAY_H["arrival"]["values"])


def sample_departure_delay(rng):
    """Hours a ship leaves its berth after (positive) or before its scheduled departure."""
    return _bootstrap(rng, SCHEDULE_DELAY_H["departure"]["values"])


def sample_entry_to_berth(rng, category="sea"):
    """Hours from entering the area (category "sea" or "anchorage") to berthing in Antwerp."""
    summary = ENTRY_TO_BERTH_H.get(category) or ENTRY_TO_BERTH_H["sea"]
    return _bootstrap(rng, summary["values"])
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ais", type=Path, default=AIS_DIR, help="snapshot directory")
    parser.add_argument("--schedule", type=Path, default=SCHEDULE)
    parser.add_argument("--charts", type=Path, default=CHARTS)
    parser.add_argument("--berths", type=Path, default=BERTHS)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "src" / "data" / "container_calls.py")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    data = prepare(args.ais, args.schedule, args.charts, args.berths)
    tables = fit(data, find_stops(data.df))
    times = data.times
    docstring = DOCSTRING.format(
        n_snapshots=len(times), first=f"{times.iloc[0]:%Y-%m-%d %H:%M}Z", last=f"{times.iloc[-1]:%Y-%m-%d %H:%M}Z",
        generated=f"generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z", tz=SCHEDULE_TZ,
        window=MATCH_WINDOW_H,
    )
    write_module(args.out, docstring, tables, MODULE_FUNCTIONS)


if __name__ == "__main__":
    main()
