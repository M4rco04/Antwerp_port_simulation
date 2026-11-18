"""Fit entry-source probabilities per ship class from the AIS snapshots.

Uses the visits from ais_pipeline.py and works out where every visit entered the scene:

    sea          came in over the edge of the AIS area at sea (west / north / south-west)
                 and sailed on without anchoring
    anchorage    came in from sea and anchored (Westhinder, Everingen, Vlissingen
                 roads, ...) before reaching a port, or was first seen lying there
    port_channel first seen in a port or a canal that feeds the Scheldt (Antwerp docks,
                 Albert Canal, Upper Sea Scheldt, Schelde-Rijn canal, Hansweert,
                 Terneuzen, Ghent canal, Vlissingen, Breskens)
    non_scheldt  first seen in Zeebrugge or the Oosterschelde, then sailed into the Scheldt

Only visits that enter the Scheldt are kept: through traffic in the North Sea
traffic lanes, the coastal route past the mouth and Zeebrugge-only calls are dropped.

The result is written as a plain Python module (default
src/data/entry_probabilities.py) that the simulation imports.

Usage:
    py src/data/fit_entry_probabilities.py
    py src/data/fit_entry_probabilities.py --plot entries.png   # map of the entry points
"""
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from ais_pipeline import (AIS_DIR, CHARTS, CLASS_DESCRIPTIONS, KX, KY, LAT0, LON0, PORT_ZONES, REPO_ROOT,
                          SCHEDULE, SIMULATED_CLASSES, UNRESOLVED, normalise, prepare, write_module)

log = logging.getLogger("entry")

# Day of the week. A class's rate is taken as one level Monday to Friday, one on Saturday and one on Sunday (two or
# three observed days per weekday are too few for seven levels), and kept only where the weekend differs from the
# weekdays beyond the spread from day to day: Welch's t-test on the daily rates, at WEEKDAY_ALPHA divided by the
# number of classes tested. Else the factor is 1 on every day. Days with less than MIN_DAY_H observed hours are
# left out of the test (not of the levels).
WEEK_TZ = "Europe/Brussels"
WEEKDAY_ALPHA = 0.05
MIN_DAY_H = 12.0


def day_exposure(windows):
    """Observed hours per local day (WEEK_TZ)."""
    hours = {}
    for lo, hi in windows:
        for t in pd.date_range(lo.floor("h"), hi, freq="h"):
            a, b = max(lo, t), min(hi, t + pd.Timedelta(hours=1))
            if b > a:
                day = t.tz_convert(WEEK_TZ).normalize()
                hours[day] = hours.get(day, 0.0) + (b - a).total_seconds() / 3600
    return pd.Series(hours, dtype=float).sort_index()


def weekday_factors(entries, windows, classes):
    """class -> 7 multipliers (local Monday .. Sunday) on RATE_PER_HOUR, and class -> the test's p-value.
    A multiplier is the rate on that kind of day over the rate of all the observed hours, so that the rate times
    the factor gives that day's rate (the observed hours are not spread evenly over the week)."""
    exposure = day_exposure(windows)
    dow = pd.Series(exposure.index.dayofweek, index=exposure.index)
    kinds = {"weekday": dow < 5, "saturday": dow == 5, "sunday": dow == 6}
    full = exposure >= MIN_DAY_H
    factors, tests = {}, {}
    from scipy import stats

    for cls in classes:
        e = entries[entries["class"] == cls]
        n = e.t.dt.tz_convert(WEEK_TZ).dt.normalize().value_counts().reindex(exposure.index, fill_value=0)
        overall = n.sum() / exposure.sum() if exposure.sum() else 0.0
        rate = n / exposure
        wk, we = rate[full & kinds["weekday"]], rate[full & ~kinds["weekday"]]
        p = float(stats.ttest_ind(wk, we, equal_var=False).pvalue) if len(wk) >= 2 and len(we) >= 2 and overall else 1.0
        tests[cls] = round(p, 5) if p == p else 1.0
        if p == p and p < WEEKDAY_ALPHA / len(classes) and overall:
            level = {k: n[m].sum() / exposure[m].sum() / overall for k, m in kinds.items()}
            factors[cls] = [round(float(level["weekday"]), 3)] * 5 + [round(float(level["saturday"]), 3),
                                                                     round(float(level["sunday"]), 3)]
        else:
            factors[cls] = [1.0] * 7
    return factors, tests


def until_cut(entries, windows, until):
    """The entries and observed windows up to `until` (the days the model is fitted on; the rest is held out)."""
    if until is None:
        return entries, windows
    return entries[entries.t <= until], [(lo, min(hi, until)) for lo, hi in windows if lo < until]


def hour_exposure(windows):
    hours = np.zeros(24)
    for lo, hi in windows:
        for t in pd.date_range(lo.floor("h"), hi, freq="h"):
            hours[t.hour] += max((min(hi, t + pd.Timedelta(hours=1)) - max(lo, t)).total_seconds() / 3600, 0)
    return hours


def fit(entries, windows, catalogue, classes):
    exposure_h = sum((hi - lo).total_seconds() for lo, hi in windows) / 3600
    per_hour_exposure = hour_exposure(windows)
    sources = [s for s in catalogue if s != UNRESOLVED]
    counts, p_source, p_category, rate, unresolved_share, hourly = {}, {}, {}, {}, {}, {}
    for cls in classes:
        e = entries[entries["class"] == cls]
        c = e.source.value_counts().to_dict()
        counts[cls] = {s: int(c[s]) for s in sources + [UNRESOLVED] if c.get(s)}
        resolved = {s: n for s, n in counts[cls].items() if s != UNRESOLVED}
        p_source[cls] = normalise(resolved)
        cat = {}
        for s, n in resolved.items():
            cat[catalogue[s]["category"]] = cat.get(catalogue[s]["category"], 0) + n
        p_category[cls] = normalise(cat)
        unresolved_share[cls] = round(counts[cls].get(UNRESOLVED, 0) / len(e), 4) if len(e) else 0.0
        # the unresolved entries are shared out over the sources in proportion (missing at random)
        total_rate = len(e) / exposure_h
        rate[cls] = {s: round(total_rate * p, 5) for s, p in p_source[cls].items()}
        # hour-of-day factor (mean 1), smoothed over +-1 h to tame a few days of data
        per_hour = np.bincount(e.t.dt.hour, minlength=24) / np.maximum(per_hour_exposure, 1e-9)
        smooth = (np.roll(per_hour, 1) + per_hour + np.roll(per_hour, -1)) / 3
        hourly[cls] = [round(float(v), 3) for v in (smooth / smooth.mean() if smooth.mean() else np.ones(24))]

    p_class = {s: normalise({cls: counts[cls].get(s, 0) for cls in classes}) for s in sources}
    weekday, weekday_test = weekday_factors(entries, windows, classes)

    # spawn points: where the ships of a source are first seen (for anchorages: the anchorage itself)
    location = {}
    for s, grp in entries[entries.source == entries.first_seen].groupby("source"):
        if s != UNRESOLVED:
            location[s] = {"lat": round(float(grp.lat.median()), 5), "lon": round(float(grp.lon.median()), 5)}
    return {
        "EXPOSURE_HOURS": round(exposure_h, 2),
        "ENTRY_COUNTS": counts,
        "P_SOURCE_GIVEN_CLASS": p_source,
        "P_CATEGORY_GIVEN_CLASS": p_category,
        "P_CLASS_GIVEN_SOURCE": {s: p for s, p in p_class.items() if p},
        "UNRESOLVED_SHARE": unresolved_share,
        "RATE_PER_HOUR": rate,
        "HOURLY_FACTOR": hourly,
        "WEEKDAY_FACTOR": weekday,
        "WEEKDAY_TEST": weekday_test,
        "SOURCE_LOCATION": location,
    }


# ---------------------------------------------------------------------------
# output

DOCSTRING = """Entry-source probabilities per ship class, fitted from the AIS snapshots.

GENERATED by src/data/fit_entry_probabilities.py, do not edit by hand. Re-run it when
more AIS data has been collected.

Data: {n_snapshots} snapshots, {first} to {last},
      {exposure} h observed, {n_entries} entries ({generated}).

Only ships that enter the Scheldt are counted; North Sea through traffic, the coastal
route past the mouth and Zeebrugge-only calls are left out.

SOURCES                 every entry source: category (sea / anchorage / port_channel /
                        non_scheldt) and description
P_SOURCE_GIVEN_CLASS    class -> {{source: P}}, unresolved entries left out
P_CATEGORY_GIVEN_CLASS  class -> {{category: P}}
P_CLASS_GIVEN_SOURCE    source -> {{class: P}}
RATE_PER_HOUR           class -> {{source: mean entries per hour}}; the unresolved
                        entries are shared out over the sources in proportion
HOURLY_FACTOR           class -> 24 multipliers (UTC hour of day, mean 1) for an NHPP
WEEKDAY_FACTOR          class -> 7 multipliers (local day, Monday first) on RATE_PER_HOUR: one level
                        Monday to Friday, one Saturday, one Sunday, where the weekend differs (else 1)
WEEKDAY_TEST            class -> p-value of weekdays against weekends (Welch, daily rates)
ENTRY_COUNTS           class -> {{source: number of entries}}, the raw data behind it all
UNRESOLVED_SHARE        class -> share of entries first seen under way mid-river
SOURCE_LOCATION         source -> median lat/lon of the first fixes there (a spawn point)

Sea arrivals that anchor before reaching a port count as entering from that anchorage.
Counts are small (a few days of data): check ENTRY_COUNTS before trusting a probability.
"""

MODULE_FUNCTIONS = '''

def p_source(ship_class, category=None):
    """P(source | class) over the resolved sources, optionally within one category ("sea", ...)."""
    probs = P_SOURCE_GIVEN_CLASS[ship_class]
    if category is None:
        return dict(probs)
    probs = {s: p for s, p in probs.items() if SOURCES[s]["category"] == category}
    total = sum(probs.values())
    return {s: p / total for s, p in probs.items()} if total else {}


def p_category(ship_class):
    """P(category | class), category in sea / anchorage / port_channel / non_scheldt."""
    return dict(P_CATEGORY_GIVEN_CLASS[ship_class])


def p_class(source):
    """P(class | source): the mix of ship classes entering through one source."""
    return dict(P_CLASS_GIVEN_SOURCE.get(source, {}))


def arrival_rate(ship_class, source=None, hour=None, weekday=None):
    """Mean entries per hour of a class (through one source, at one UTC hour of the day, on one local weekday,
    Monday = 0)."""
    rates = RATE_PER_HOUR[ship_class]
    rate = sum(rates.values()) if source is None else rates.get(source, 0.0)
    rate *= HOURLY_FACTOR[ship_class][hour % 24] if hour is not None else 1.0
    return rate * (WEEKDAY_FACTOR.get(ship_class, [1.0] * 7)[weekday % 7] if weekday is not None else 1.0)


def sample_source(ship_class, rng, category=None):
    """Draw an entry source for a ship of this class; rng is a numpy Generator or random.Random."""
    probs = p_source(ship_class, category)
    names, weights = list(probs), list(probs.values())
    if hasattr(rng, "integers"):
        total = sum(weights)
        return names[rng.choice(len(names), p=[w / total for w in weights])]
    return rng.choices(names, weights=weights)[0]
'''


def plot_entries(entries, passing, zones, charts, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(16, 9))
    gpd.read_file(charts, layer="land_gshhg").clip(box(2.4, 51.1, 4.5, 51.8)).plot(ax=ax, color="#e4e4e4")
    corners = [(LON0 + x / KX, LAT0 + y / KY) for x, y in zones.area.exterior.coords]
    ax.plot(*zip(*corners), "k--", lw=0.8)
    ax.scatter(passing.lon, passing.lat, s=6, marker="x", color="#999999", label=f"passing by, left out ({len(passing)})")
    cmap = plt.get_cmap("tab20")
    for i, (source, grp) in enumerate(entries.groupby("source")):
        ax.scatter(grp.lon, grp.lat, s=8, color=cmap(i % 20), label=f"{source} ({len(grp)})")
    for bounds, _, _ in PORT_ZONES.values():
        ax.add_patch(plt.Rectangle(bounds[:2], bounds[2] - bounds[0], bounds[3] - bounds[1], fill=False, lw=0.5))
    for geom, _ in zones.anchorages.values():
        ax.plot(*zip(*[(LON0 + x / KX, LAT0 + y / KY) for x, y in geom.exterior.coords]), "k-", lw=0.4)
    ax.set_xlim(2.45, 4.5)
    ax.set_ylim(51.15, 51.78)
    ax.set_title("First fix of every visit into the Scheldt, coloured by entry source")
    ax.legend(fontsize=7, ncol=2, loc="upper right")
    fig.savefig(path, dpi=100, bbox_inches="tight")
    log.info("Wrote %s", path)


def patch_weekday(path, factors, tests, until):
    """Write WEEKDAY_FACTOR and WEEKDAY_TEST into an existing generated module (before its functions), with the
    docstring lines for them and arrival_rate taking the weekday; the module's other tables are not touched."""
    import pprint
    import re

    text = path.read_text(encoding="utf-8")
    for name in ("WEEKDAY_FACTOR", "WEEKDAY_TEST"):           # an earlier patch
        text = re.sub(rf"\n{name} = .*?\n\n", "\n", text, flags=re.S)
    note = f"(fitted on the snapshots up to {until:%Y-%m-%d %H:%M}Z)" if until is not None else ""
    tables = (f"# day of the week {note}\n"
              f"WEEKDAY_FACTOR = {pprint.pformat(factors, width=110, sort_dicts=False, compact=True)}\n\n"
              f"WEEKDAY_TEST = {pprint.pformat(tests, width=110, sort_dicts=False, compact=True)}\n\n")
    text = re.sub(r"\n# day of the week[^\n]*\n", "\n", text)
    head, sep, tail = text.partition("\n\ndef p_source(")
    if not sep:
        raise SystemExit(f"{path}: no functions found to put the tables before")
    text = head.rstrip("\n") + "\n\n" + tables + "\ndef p_source(" + tail
    doc = DOCSTRING.split("WEEKDAY_FACTOR", 1)[1].split("ENTRY_COUNTS", 1)[0]
    if "WEEKDAY_FACTOR          class" not in text.split('"""', 2)[1]:
        text = text.replace("\nENTRY_COUNTS ", "\nWEEKDAY_FACTOR" + doc + "ENTRY_COUNTS ", 1)
    old = re.search(r"def arrival_rate\(.*?\n\n\n", text, flags=re.S)
    new = MODULE_FUNCTIONS.split("def arrival_rate(", 1)[1].split("\n\n\n", 1)[0]
    if old:
        text = text[:old.start()] + "def arrival_rate(" + new + "\n\n\n" + text[old.end():]
    path.write_text(text, encoding="utf-8")
    log.info("Wrote WEEKDAY_FACTOR and WEEKDAY_TEST into %s", path)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ais", type=Path, default=AIS_DIR, help="snapshot directory")
    parser.add_argument("--schedule", type=Path, default=SCHEDULE)
    parser.add_argument("--charts", type=Path, default=CHARTS)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "src" / "data" / "entry_probabilities.py")
    parser.add_argument("--plot", type=Path, help="also save a map of the entry points")
    parser.add_argument("--until", help="fit on the snapshots up to this UTC time only (the rest is held out), "
                                        "e.g. '2026-11-12 01:29'")
    parser.add_argument("--weekday-only", action="store_true",
                        help="fit only WEEKDAY_FACTOR / WEEKDAY_TEST and write them into the existing --out module, "
                             "leaving every other table as it was fitted")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    data = prepare(args.ais, args.schedule, args.charts)
    until = pd.Timestamp(args.until, tz="UTC") if args.until else None
    entries, windows = until_cut(data.entries, data.windows, until)
    if args.weekday_only:
        entries = entries[entries.scheldt_bound]
        factors, tests = weekday_factors(entries, windows, list(CLASS_DESCRIPTIONS))
        log.info("weekday factors: %s; p-values: %s", factors, tests)
        patch_weekday(args.out, factors, tests, until)
        return
    data.windows = windows
    log.info("%d entries reach the Scheldt, %d more are still on their way to it, %d pass by (left out)",
             entries.reaches_scheldt.sum(), (entries.scheldt_bound & ~entries.reaches_scheldt).sum(),
             (~entries.scheldt_bound).sum())
    passing, entries = entries[~entries.scheldt_bound], entries[entries.scheldt_bound]
    log.info("Entries per source: %s", entries.source.value_counts().to_dict())

    catalogue = data.zones.catalogue()
    fitted = fit(entries, data.windows, catalogue, list(CLASS_DESCRIPTIONS))
    times = data.times
    docstring = DOCSTRING.format(
        n_snapshots=len(times), first=f"{times.iloc[0]:%Y-%m-%d %H:%M}Z", last=f"{times.iloc[-1]:%Y-%m-%d %H:%M}Z",
        exposure=fitted["EXPOSURE_HOURS"], n_entries=len(entries),
        generated=f"generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z",
    )
    tables = {"CLASSES": CLASS_DESCRIPTIONS, "SIMULATED_CLASSES": SIMULATED_CLASSES, "SOURCES": catalogue, **fitted}
    write_module(args.out, docstring, tables, MODULE_FUNCTIONS)
    if args.plot:
        plot_entries(entries, passing, data.zones, args.charts, args.plot)


if __name__ == "__main__":
    main()
