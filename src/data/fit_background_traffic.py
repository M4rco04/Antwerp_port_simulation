"""Fit the background-traffic distributions (PLAN.md §1 level 2, §2.4) from the AIS snapshots.

For the Scheldt visits from ais_pipeline.py:

    ATTRIBUTES        whole observed ships per class (LOA, beam, arrival draught, dangerous
                      goods category), to bootstrap so the dimensions stay correlated; per
                      destination too, so a ship's size goes with where it is going
    NEXT_CALL         inland craft call at several places on one visit: where they go after a call
    DRAUGHT_CHANGE    departure / arrival draught seen on one visit: ships load and unload
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

import numpy as np
import pandas as pd

from ais_pipeline import (AIS_DIR, BERTHS, CHARTS, LOCK_STOP_MAX_H, LOCK_ZONES, PORT_ZONES, REPO_ROOT, SCHEDULE,
                          SEA_GATES, SIMULATED_CLASSES, UNRESOLVED, berth_calls, dangerous_goods, destination_zones,
                          find_stops, fit_lognormal, normalise, prepare, visit_exits, write_module)

log = logging.getLogger("background")

# fit a per-zone dwell time only with this many complete stays
MIN_COMPLETE_PER_ZONE = 8
# bootstrap a ship from the visits to one destination only with this many of them, else from the class
MIN_SHIPS_PER_DESTINATION = 5
INLAND_CLASSES = ("inland_cargo", "inland_tanker")
# largest believable draught of an inland craft (class VIb barge convoys load to about 4.5 m); AIS shows
# 85 x 10 m barges "at" 25 m. Above it the draught counts as not reported
INLAND_MAX_DRAUGHT_M = 5.0
# an inland call lasts at least this long; shorter stops are waits for a bridge or a lock
INLAND_CALL_MIN_H = 1.0
INLAND_SILENT_H = 6.0               # an inland craft not heard for this long has left (find_stops)
LEAVE = "leave"
DRAUGHT_BANDS = (7.0, 10.0, 13.0)   # arrival draught bands of DRAUGHT_CHANGE, m


def exit_name(sink):
    return f"exit_{sink}"


def attributes(entries, df, ships, destination):
    """Whole ships as they arrived: (LOA m, beam m, draught m or None, DG category or None), per class
    and per class and destination (only destinations with MIN_SHIPS_PER_DESTINATION ships)."""
    draught = df[df.draught > 0].groupby("visit").draught.first()
    out, by_destination = {}, {}
    for cls in SIMULATED_CLASSES:
        rows, per = [], {}
        for e in entries[entries["class"] == cls].itertuples():
            ship = ships.loc[e.mmsi]
            if pd.isna(ship.length) or pd.isna(ship.width):
                continue
            t = draught.get(e.visit)
            if cls in INLAND_CLASSES and t is not None and t > INLAND_MAX_DRAUGHT_M:
                t = None
            row = (int(ship.length), int(ship.width), None if t is None or pd.isna(t) else round(float(t), 1),
                   dangerous_goods(ship.ship_type))
            rows.append(row)
            d = destination.get(e.visit)
            if d is not None and not pd.isna(d):
                per.setdefault(d, []).append(row)
        out[cls] = rows
        by_destination[cls] = {d: r for d, r in per.items() if len(r) >= MIN_SHIPS_PER_DESTINATION}
    return out, by_destination


def draught_changes(df, all_calls, visits):
    """Departure / arrival draught of the visits with a berth call whose draught was seen both before and
    after it, per class and arrival draught band (DRAUGHT_BANDS): whole values to bootstrap (1.0: AIS draught
    unchanged). The band matters: a ship that comes in deep has cargo to unload."""
    out = {}
    calls = all_calls.sort_values("start").groupby("visit").agg(first=("start", "first"), last=("end", "last"))
    fixes = df[(df.draught > 0) & df.visit.isin(calls.index)]
    for visit, g in fixes.groupby("visit"):
        before, after = g[g.t <= calls["first"][visit]], g[g.t >= calls["last"][visit]]
        if before.empty or after.empty:
            continue
        cls = visits["class"].get(visit)
        band = int(np.searchsorted(DRAUGHT_BANDS, before.draught.iloc[0], side="right"))
        out.setdefault(cls, {}).setdefault(band, []).append(round(float(after.draught.iloc[-1] / before.draught.iloc[0]), 3))
    return {c: {b: sorted(v) for b, v in per.items()} for c, per in out.items() if c in SIMULATED_CLASSES}


def inland_calls(all_calls):
    """The calls of inland craft in order per visit: stops of INLAND_CALL_MIN_H or more, with successive
    stops in one zone merged into a single call (shifting along the quay)."""
    c = all_calls[all_calls["class"].isin(INLAND_CLASSES) & (all_calls.hours >= INLAND_CALL_MIN_H)]
    c = c[~c.at_visit_start].sort_values(["visit", "start"])
    new = (c.visit != c.visit.shift()) | (c.zone != c.zone.shift())
    rows = []
    for _, g in c.groupby(new.cumsum()):
        first, last = g.iloc[0], g.iloc[-1]
        rows.append({"visit": first.visit, "mmsi": first.mmsi, "class": first["class"], "zone": first.zone,
                     "lat": first.lat, "lon": first.lon, "start": first.start, "end": last.end,
                     "hours": (last.end - first.start).total_seconds() / 3600, "start_observed": first.start_observed,
                     "end_observed": last.end_observed, "truncated_at": first.truncated_at})
    return pd.DataFrame(rows)


def scale_inland_stays(berth_dwell, by_zone, inland, data):
    """Scale the inland stays so that they give the stock the AIS shows (Little's law: mean stay = craft
    lying in port / calls per hour). With many stays still going on when the data ends the lognormal's tail
    is an extrapolation, and it gave three times the craft in port. Only ever shortens."""
    df, n_snapshots = data.df, data.times.size
    hours = n_snapshots * 5 / 60
    rng = np.random.default_rng(0)
    out = {}
    for cls in INLAND_CLASSES:
        calls = inland[(inland["class"] == cls) & inland.start_observed]
        rate = len(calls) / hours
        fixes = df[(df.mmsi.map(data.ships["class"]) == cls) & df.stationary & (df.port_zone != "")]
        target = len(fixes) / n_snapshots / rate
        means = []
        for zone, n in calls.zone.value_counts().items():
            f = by_zone.get(cls, {}).get(zone) or berth_dwell[cls]
            means.append(n * np.minimum(rng.lognormal(f["mu"], f["sigma"], 20000), f["longest_seen_h"]).mean())
        model = sum(means) / len(calls)
        factor = min(target / model, 1.0)
        for f in [berth_dwell[cls], *by_zone.get(cls, {}).values()]:
            f["mu"] = round(f["mu"] + float(np.log(factor)), 4)
            f["median_h"] = round(float(np.exp(f["mu"])), 2)
            f["mean_h"] = round(float(np.exp(f["mu"] + f["sigma"] ** 2 / 2)), 2)
        out[cls] = {"mean_stay_from_stock_h": round(float(target), 1), "mean_stay_of_fit_h": round(float(model), 1),
                    "factor": round(float(factor), 3)}
    log.info("inland stays scaled to the AIS stock: %s", out)
    return out


def next_call(calls, visits):
    """class -> zone -> {next zone or LEAVE: P}. The last call counts as leaving only if the visit's end
    was seen; a ship still lying there when the data ends says nothing about what it does next."""
    counts = {}
    for visit, g in calls.groupby("visit", sort=False):
        zones, cls = list(g.zone), g["class"].iloc[0]
        for a, b in zip(zones, zones[1:]):
            counts.setdefault(cls, {}).setdefault(a, {}).setdefault(b, 0)
            counts[cls][a][b] += 1
        if visits.end_observed.get(visit) and g.end_observed.iloc[-1]:
            counts.setdefault(cls, {}).setdefault(zones[-1], {}).setdefault(LEAVE, 0)
            counts[cls][zones[-1]][LEAVE] += 1
    return {c: {z: normalise(n) for z, n in per.items()} for c, per in counts.items()}


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
    """The berth zone of a visit's call, or the exit of one with no call. A sea-going ship in from sea and out
    to sea with no call seen has not simply passed through: such visits last a median of 34 h and reach
    Vlissingen, so its call was not heard. Its destination counts as unknown (left out), not as the sea."""
    dest = pd.Series(index=entries.visit, dtype=object)
    sea = entries.set_index("visit").source.map(lambda s: s in SEA_GATES or str(s).startswith("anchorage"))
    sea_going = entries.set_index("visit")["class"].isin(("bulk_general", "tanker", "container"))
    source = entries.set_index("visit").source
    for v in entries.visit:
        if v in calls.index:
            dest[v] = calls.zone[v]
        elif v in exits.index and exits[v] != UNRESOLVED and not (sea[v] and sea_going[v] and exits[v] in SEA_GATES) \
                and exits[v] != source[v]:     # out the way it came in, with no call: it went somewhere unseen
            dest[v] = exit_name(exits[v])
    return dest


def conditional(frame, by, value):
    """{by value: {value: P}} from a frame."""
    return {k: normalise(g[value].value_counts().to_dict()) for k, g in frame.groupby(by)}


def fit(data, stops, exits, inland_stops):
    visits = data.visits
    scheldt = visits.index[visits.scheldt_bound]
    entries = data.entries[data.entries.scheldt_bound & data.entries["class"].isin(SIMULATED_CLASSES)]
    stops = stops[stops.visit.isin(scheldt)].copy()
    stops["class"] = stops.visit.map(visits["class"])
    all_calls = berth_calls(stops)
    calls = main_stops(all_calls)
    # inland craft: the first call is the destination and each call has its own stay (one long "main" call
    # gave a third of the traffic on the river, with the berth stock right); the sea-going classes keep the
    # main call
    inland_stops = inland_stops[inland_stops.visit.isin(scheldt)].copy()
    inland_stops["class"] = inland_stops.visit.map(visits["class"])
    inland = inland_calls(berth_calls(inland_stops))
    first = inland.groupby("visit").head(1).set_index("visit")
    calls = pd.concat([calls[~calls["class"].isin(INLAND_CLASSES)], first])

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
    dwell = pd.concat([calls[~calls["class"].isin(INLAND_CLASSES)], inland])
    dwell = dwell[dwell.start_observed & dwell["class"].isin(SIMULATED_CLASSES)]
    berth_dwell = {cls: fit_lognormal(g.hours, g.end_observed, g.truncated_at) for cls, g in dwell.groupby("class")}
    berth_dwell["all"] = fit_lognormal(dwell.hours, dwell.end_observed, dwell.truncated_at)
    by_zone = {}
    for (cls, zone), g in dwell.groupby(["class", "zone"]):
        if g.end_observed.sum() >= MIN_COMPLETE_PER_ZONE:
            f = fit_lognormal(g.hours, g.end_observed, g.truncated_at)
            if f and not f["at_bound"]:        # at a bound the tail is not known: the class fit instead
                by_zone.setdefault(cls, {})[zone] = f

    stay_scale = scale_inland_stays(berth_dwell, by_zone, inland, data)

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
    p_next = next_call(inland, visits)
    used = set().union(*[set(p) for p in p_dest.values()], *[set(p) for p in p_exit.values()],
                       *[set(n) | {z} for per in p_next.values() for z, n in per.items()])
    attrs, attrs_dest = attributes(entries, data.df, data.ships, od.set_index("visit").destination)
    tables = {
        "SIMULATED_CLASSES": SIMULATED_CLASSES,
        "DESTINATIONS": {k: v for k, v in described.items() if k in used},
        "ATTRIBUTES": attrs,
        "ATTRIBUTES_BY_DESTINATION": attrs_dest,
        "DRAUGHT_CHANGE": draught_changes(data.df, all_calls, visits),
        "NEXT_CALL": p_next,
        "P_DESTINATION_GIVEN_CLASS": p_dest,
        "P_DESTINATION_GIVEN_CLASS_SOURCE": p_dest_source,
        "DESTINATION_COUNTS": dest_counts,
        "DESTINATION_UNKNOWN_SHARE": unknown_share,
        "P_EXIT_GIVEN_CLASS": p_exit,
        "P_EXIT_GIVEN_CLASS_BERTH": p_exit_zone,
        "BERTH_DWELL_H": berth_dwell,
        "BERTH_DWELL_H_BY_ZONE": by_zone,
        "INLAND_STAY_SCALE": stay_scale,
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
ATTRIBUTES_BY_DESTINATION         class -> destination -> the same, from the visits to that destination
DRAUGHT_CHANGE                    class -> arrival draught band (below 7, 10, 13 m, above) -> [departure draught /
                                  arrival draught] per visit, to bootstrap
NEXT_CALL                         inland class -> zone -> {{next zone or "leave": P}} after a call there
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
INLAND_STAY_SCALE                 inland class -> the factor their stays were scaled by to give the AIS stock
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
    """A lognormal draw, no longer than the longest stay seen: beyond the data the fit is a guess."""
    value = float(rng.lognormal(fit["mu"], fit["sigma"])) if hasattr(rng, "integers") else rng.lognormvariate(fit["mu"], fit["sigma"])
    return min(value, fit.get("longest_seen_h", value))


def sample_attributes(ship_class, rng, destination=None):
    """One observed ship of this class (that went to this destination, where enough did):
    {"loa", "beam", "draught", "dg"}."""
    rows = ATTRIBUTES_BY_DESTINATION.get(ship_class, {}).get(destination) or ATTRIBUTES[ship_class]
    loa, beam, draught, dg = rows[rng.integers(len(rows)) if hasattr(rng, "integers") else rng.randrange(len(rows))]
    return {"loa": loa, "beam": beam, "draught": draught, "dg": dg}


def p_destination(ship_class, source=None):
    """P(destination | class), or P(destination | class, entry source) when that has data."""
    if source is not None and source in P_DESTINATION_GIVEN_CLASS_SOURCE.get(ship_class, {}):
        return dict(P_DESTINATION_GIVEN_CLASS_SOURCE[ship_class][source])
    return dict(P_DESTINATION_GIVEN_CLASS[ship_class])


def sample_destination(ship_class, rng, source=None):
    return _choice(rng, p_destination(ship_class, source))


def sample_draught_change(ship_class, rng, arrival_draught=None):
    """Departure draught / arrival draught of one observed visit that came in about as deep (the nearest band
    with 5 visits or more; 1.0 where there are none)."""
    per = DRAUGHT_CHANGE.get(ship_class)
    if not per:
        return 1.0
    band = sum(arrival_draught >= b for b in (7.0, 10.0, 13.0)) if arrival_draught is not None else 1
    bands = sorted((b for b, v in per.items() if len(v) >= 5), key=lambda b: abs(b - band))
    if not bands:
        return 1.0
    values = per[bands[0]]
    return values[rng.integers(len(values)) if hasattr(rng, "integers") else rng.randrange(len(values))]


def sample_next_call(ship_class, rng, zone):
    """Where an inland craft goes after a call in this zone: a zone, or None when it leaves."""
    probs = NEXT_CALL.get(ship_class, {}).get(zone)
    if not probs:
        return None
    next_zone = _choice(rng, probs)
    return None if next_zone == "leave" else next_zone


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
    tables = fit(data, stops, exits, find_stops(data.df, max_gap_h=INLAND_SILENT_H))
    times = data.times
    docstring = DOCSTRING.format(
        n_snapshots=len(times), first=f"{times.iloc[0]:%Y-%m-%d %H:%M}Z", last=f"{times.iloc[-1]:%Y-%m-%d %H:%M}Z",
        generated=f"generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z",
        lock_zones=", ".join(LOCK_ZONES), lock_max=LOCK_STOP_MAX_H,
    )
    write_module(args.out, docstring, tables, MODULE_FUNCTIONS)


if __name__ == "__main__":
    main()
