"""Fit the background-traffic distributions (PLAN.md §1 level 2, §2.4) from the AIS snapshots.

For the Scheldt visits from ais_pipeline.py:

    ATTRIBUTES        whole observed ships per class (LOA, beam, arrival draught, dangerous
                      goods category), to bootstrap so the dimensions stay correlated
    destinations      where a ship entering through a source goes: the berth zone of its
                      longest stop, or the exit it leaves by when it never stops (through traffic)
    exits             where a ship leaves the area after its last berth stop
    BERTH_DWELL_H     lognormal time at berth per class (and per berth zone where there is data)
    ANCHORAGE_WAIT_H  lognormal time at anchor per class, and which anchorage is used

Stops still going on when the data ends are right-censored and fitted as such, so the
long berth stays of sea-going ships are not cut short.

The result is written as a plain Python module (default src/data/background_traffic.py).

Usage:
    py src/data/fit_background_traffic.py
"""
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ais_pipeline import (AIS_DIR, BERTHS, CHARTS, LOCK_STOP_MAX_H, LOCK_ZONES, PORT_ZONES, REPO_ROOT, SCHEDULE,
                          SEA_GATES, SIMULATED_CLASSES, UNRESOLVED, berth_calls, dangerous_goods, destination_zones,
                          find_stops, fit_lognormal, normalise, prepare, visit_exits, write_module)

log = logging.getLogger("background")

# fit a per-zone dwell time only with this many complete stays
MIN_COMPLETE_PER_ZONE = 5


def exit_name(sink):
    return f"exit_{sink}"


def attributes(entries, df, ships):
    """Whole ships as they arrived: (LOA m, beam m, draught m or None, DG category or None)."""
    draught = df[df.draught > 0].groupby("visit").draught.first()
    out = {}
    for cls in SIMULATED_CLASSES:
        rows = []
        for e in entries[entries["class"] == cls].itertuples():
            ship = ships.loc[e.mmsi]
            if pd.isna(ship.length) or pd.isna(ship.width):
                continue
            t = draught.get(e.visit)
            rows.append((int(ship.length), int(ship.width), None if pd.isna(t) else round(float(t), 1),
                         dangerous_goods(ship.ship_type)))
        out[cls] = rows
    return out


def main_stops(calls):
    """The berth call of each visit: its longest call that it did not start the visit at."""
    calls = calls[~calls.at_visit_start]
    return calls.loc[calls.groupby("visit").hours.idxmax()].set_index("visit")


def lock_stops(stops):
    """Hours lying still in the lock zones, for stops shorter than LOCK_STOP_MAX_H."""
    lock = stops[(stops.kind == "berth") & stops.zone.isin(LOCK_ZONES) & (stops.hours < LOCK_STOP_MAX_H)
                 & stops.start_observed & stops.end_observed]
    return {zone: {"n": len(g), "median_h": round(float(g.hours.median()), 2),
                   "p90_h": round(float(g.hours.quantile(0.9)), 2)} for zone, g in lock.groupby("zone")}


def destinations(entries, calls, exits):
    dest = pd.Series(index=entries.visit, dtype=object)
    for v in entries.visit:
        if v in calls.index:
            dest[v] = calls.zone[v]
        elif v in exits.index and exits[v] != UNRESOLVED:
            dest[v] = exit_name(exits[v])
    return dest


def conditional(frame, by, value):
    """{by value: {value: P}} from a frame."""
    return {k: normalise(g[value].value_counts().to_dict()) for k, g in frame.groupby(by)}


def fit(data, stops, exits):
    visits = data.visits
    scheldt = visits.index[visits.scheldt_bound]
    entries = data.entries[data.entries.scheldt_bound & data.entries["class"].isin(SIMULATED_CLASSES)]
    stops = stops[stops.visit.isin(scheldt)].copy()
    stops["class"] = stops.visit.map(visits["class"])
    all_calls = berth_calls(stops)
    calls = main_stops(all_calls)

    # origin-destination
    od = entries.assign(destination=entries.visit.map(destinations(entries, calls, exits)))
    known = od[od.destination.notna()]
    p_dest = {cls: normalise(g.destination.value_counts().to_dict()) for cls, g in known.groupby("class")}
    p_dest_source = {cls: conditional(g, "source", "destination") for cls, g in known.groupby("class")}
    dest_counts = {cls: {k: int(n) for k, n in g.destination.value_counts().items()}
                   for cls, g in known.groupby("class")}
    unknown_share = {cls: round(float(g.destination.isna().mean()), 4) for cls, g in od.groupby("class")}

    # exits after the last berth stop, for every Scheldt visit whose exit was seen
    last_berth = all_calls.sort_values("end").groupby("visit").zone.last()
    left = pd.DataFrame({"zone": last_berth, "exit": exits}).dropna()
    left = left[left.exit != UNRESOLVED]
    left["class"] = left.index.map(visits["class"])
    left = left[left["class"].isin(SIMULATED_CLASSES)]
    left["exit"] = left.exit.map(exit_name)
    p_exit = {cls: normalise(g.exit.value_counts().to_dict()) for cls, g in left.groupby("class")}
    p_exit_zone = {cls: conditional(g, "zone", "exit") for cls, g in left.groupby("class")}

    # time at berth: the berth calls whose start was seen
    dwell = calls[calls.start_observed & calls["class"].isin(SIMULATED_CLASSES)]
    berth_dwell = {cls: fit_lognormal(g.hours, g.end_observed, g.truncated_at) for cls, g in dwell.groupby("class")}
    berth_dwell["all"] = fit_lognormal(dwell.hours, dwell.end_observed, dwell.truncated_at)
    by_zone = {}
    for (cls, zone), g in dwell.groupby(["class", "zone"]):
        if g.end_observed.sum() >= MIN_COMPLETE_PER_ZONE:
            by_zone.setdefault(cls, {})[zone] = fit_lognormal(g.hours, g.end_observed, g.truncated_at)

    # anchorages
    anchored = stops[(stops.kind == "anchorage") & stops["class"].isin(SIMULATED_CLASSES)]
    waits = anchored[anchored.start_observed]
    anchorage_wait = {cls: fit_lognormal(g.hours, g.end_observed) for cls, g in waits.groupby("class")}
    anchorage_wait["all"] = fit_lognormal(waits.hours, waits.end_observed)
    p_anchorage = {cls: normalise(g.zone.value_counts().to_dict()) for cls, g in anchored.groupby("class")}

    location = {zone: {"lat": round(float(g.lat.median()), 5), "lon": round(float(g.lon.median()), 5)}
                for zone, g in calls.groupby("zone")}
    described = {**destination_zones(),
                 **{exit_name(s): f"leaves via {s} without stopping: {d}" for s, d in SEA_GATES.items()},
                 **{exit_name(z): f"leaves via {z} without stopping: {d}" for z, (_, _, d) in PORT_ZONES.items()}}
    used = set().union(*[set(p) for p in p_dest.values()], *[set(p) for p in p_exit.values()])
    tables = {
        "SIMULATED_CLASSES": SIMULATED_CLASSES,
        "DESTINATIONS": {k: v for k, v in described.items() if k in used},
        "ATTRIBUTES": attributes(entries, data.df, data.ships),
        "P_DESTINATION_GIVEN_CLASS": p_dest,
        "P_DESTINATION_GIVEN_CLASS_SOURCE": p_dest_source,
        "DESTINATION_COUNTS": dest_counts,
        "DESTINATION_UNKNOWN_SHARE": unknown_share,
        "P_EXIT_GIVEN_CLASS": p_exit,
        "P_EXIT_GIVEN_CLASS_BERTH": p_exit_zone,
        "BERTH_DWELL_H": berth_dwell,
        "BERTH_DWELL_H_BY_ZONE": by_zone,
        "ANCHORAGE_WAIT_H": anchorage_wait,
        "P_ANCHORAGE_GIVEN_CLASS": p_anchorage,
        "LOCK_ZONE_STOP_H": lock_stops(stops),
        "ZONE_LOCATION": location,
    }
    tables["DG_SHARE"] = {cls: round(sum(r[3] is not None for r in rows) / len(rows), 4) if rows else 0.0
                          for cls, rows in tables["ATTRIBUTES"].items()}
    log.info("Destinations known for %d of %d entries; %d berth calls with a seen start; %d anchor stops",
             len(known), len(od), len(dwell), len(anchored))
    return tables


DOCSTRING = """Background-traffic distributions per ship class, fitted from the AIS snapshots.

GENERATED by src/data/fit_background_traffic.py, do not edit by hand. Re-run it when
more AIS data has been collected. Data: {n_snapshots} snapshots, {first} to {last} ({generated}).
Only ships that enter the Scheldt are used. Entry sources and arrival rates are in
entry_probabilities.py; the source names here are the same.

DESTINATIONS                      every destination: a berth zone, or exit_<sink> for ships that
                                  pass through without stopping
ATTRIBUTES                        class -> [(LOA m, beam m, draught m or None, DG category or None)],
                                  whole arriving ships to bootstrap (PLAN.md §1)
DG_SHARE                          class -> share of arrivals with an IMO hazard category (AIS type x1-x4)
P_DESTINATION_GIVEN_CLASS         class -> {{destination: P}}
P_DESTINATION_GIVEN_CLASS_SOURCE  class -> source -> {{destination: P}}
DESTINATION_COUNTS                class -> {{destination: number of visits}}
DESTINATION_UNKNOWN_SHARE         class -> share of entries whose destination was not seen (left out)
P_EXIT_GIVEN_CLASS                class -> {{exit_<sink>: P}} after the last berth stop
P_EXIT_GIVEN_CLASS_BERTH          class -> berth zone -> {{exit_<sink>: P}}
BERTH_DWELL_H                     class (or "all") -> lognormal time at berth in hours:
                                  mu, sigma (of ln hours), median_h, mean_h, n_complete, n_censored
BERTH_DWELL_H_BY_ZONE             class -> berth zone -> the same, where there are enough stays
ANCHORAGE_WAIT_H                  class (or "all") -> lognormal time at anchor in hours
P_ANCHORAGE_GIVEN_CLASS           class -> {{anchorage: P}} over the anchor stops
LOCK_ZONE_STOP_H                  lock zone -> n, median_h, p90_h of stops shorter than {lock_max} h there
                                  (lock passage + wait, only the ones of 0.5 h or more)
ZONE_LOCATION                     berth zone -> median lat/lon of the berth stops there

A visit's destination is the zone of its longest berth call. In the lock zones ({lock_zones})
a stop counts as a call only from {lock_max} h; shorter ones are lock passages.
Lognormal fits handle stops still going on when the data ended (censored) and stops
shorter than 0.5 h are never recorded (truncated). With few complete stays the long tail
is an extrapolation: check n_complete. A fit is None when it had fewer than 3 complete stays.
"""

MODULE_FUNCTIONS = '''

def _choice(rng, probs):
    names, weights = list(probs), list(probs.values())
    if hasattr(rng, "integers"):
        total = sum(weights)
        return names[rng.choice(len(names), p=[w / total for w in weights])]
    return rng.choices(names, weights=weights)[0]


def _lognormal(rng, fit):
    if hasattr(rng, "integers"):
        return float(rng.lognormal(fit["mu"], fit["sigma"]))
    return rng.lognormvariate(fit["mu"], fit["sigma"])


def sample_attributes(ship_class, rng):
    """One observed ship of this class: {"loa", "beam", "draught", "dg"}."""
    rows = ATTRIBUTES[ship_class]
    loa, beam, draught, dg = rows[rng.integers(len(rows)) if hasattr(rng, "integers") else rng.randrange(len(rows))]
    return {"loa": loa, "beam": beam, "draught": draught, "dg": dg}


def p_destination(ship_class, source=None):
    """P(destination | class), or P(destination | class, entry source) when that has data."""
    if source is not None and source in P_DESTINATION_GIVEN_CLASS_SOURCE.get(ship_class, {}):
        return dict(P_DESTINATION_GIVEN_CLASS_SOURCE[ship_class][source])
    return dict(P_DESTINATION_GIVEN_CLASS[ship_class])


def sample_destination(ship_class, rng, source=None):
    return _choice(rng, p_destination(ship_class, source))


def sample_exit(ship_class, rng, berth_zone=None):
    """Where a ship leaves after its berth stay (exit_<sink>)."""
    probs = P_EXIT_GIVEN_CLASS_BERTH.get(ship_class, {}).get(berth_zone) or P_EXIT_GIVEN_CLASS[ship_class]
    return _choice(rng, probs)


def berth_dwell_fit(ship_class, zone=None):
    fit = BERTH_DWELL_H_BY_ZONE.get(ship_class, {}).get(zone) or BERTH_DWELL_H.get(ship_class)
    return fit or BERTH_DWELL_H["all"]


def sample_berth_dwell(ship_class, rng, zone=None):
    """Hours at berth (lognormal; per zone where fitted, else per class, else all classes)."""
    return _lognormal(rng, berth_dwell_fit(ship_class, zone))


def sample_anchorage_wait(ship_class, rng):
    """Hours at anchor (lognormal; per class where fitted, else all classes)."""
    return _lognormal(rng, ANCHORAGE_WAIT_H.get(ship_class) or ANCHORAGE_WAIT_H["all"])
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ais", type=Path, default=AIS_DIR, help="snapshot directory")
    parser.add_argument("--schedule", type=Path, default=SCHEDULE)
    parser.add_argument("--charts", type=Path, default=CHARTS)
    parser.add_argument("--berths", type=Path, default=BERTHS)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "src" / "data" / "background_traffic.py")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    data = prepare(args.ais, args.schedule, args.charts, args.berths)
    stops = find_stops(data.df)
    exits = visit_exits(data.df, data.visits, data.zones)
    tables = fit(data, stops, exits)
    times = data.times
    docstring = DOCSTRING.format(
        n_snapshots=len(times), first=f"{times.iloc[0]:%Y-%m-%d %H:%M}Z", last=f"{times.iloc[-1]:%Y-%m-%d %H:%M}Z",
        generated=f"generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z",
        lock_zones=", ".join(LOCK_ZONES), lock_max=LOCK_STOP_MAX_H,
    )
    write_module(args.out, docstring, tables, MODULE_FUNCTIONS)


if __name__ == "__main__":
    main()
