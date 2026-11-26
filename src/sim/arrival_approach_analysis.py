"""Compare modelled approach estimates to simulated station arrivals.

Run arrival_game with record_approach_estimates=true, then pass its events.csv
to this script. The results calibrate against this simulation, not AIS.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd


def analyse(events, warmup_min=0):
    if not math.isfinite(warmup_min) or warmup_min < 0:
        raise ValueError("warmup_min must be finite and nonnegative")
    required = {"ship", "event", "t", "approach_min", "station", "source"}
    if not required <= set(events.columns):
        raise ValueError(f"events.csv lacks required columns: {', '.join(sorted(required - set(events.columns)))}")
    estimates = events[events.event == "approach_estimate"]
    if estimates.empty:
        raise ValueError("no approach_estimate events: run arrival_game with record_approach_estimates=true")
    rows = []
    incomplete = 0
    for _, estimate in estimates.iterrows():
        ship_events = events[events.ship == estimate.ship]
        legs = ship_events[ship_events.event == "to_station"].sort_values("t")
        if legs.empty:
            incomplete += 1
            continue
        started = float(legs.iloc[0].t)
        if started < warmup_min:
            continue
        arrivals = ship_events[(ship_events.event == "wait_clearance") & (ship_events.t >= started)].sort_values("t")
        if arrivals.empty:
            incomplete += 1
            continue
        actual = float(arrivals.iloc[0].t) - started
        predicted = float(estimate.approach_min)
        if not math.isfinite(predicted) or predicted < 0 or actual < 0:
            raise ValueError(f"{estimate.ship}: invalid approach times")
        rows.append({"ship": estimate.ship, "source": estimate.source, "station": estimate.station,
                     "start_min": started, "estimated_min": predicted, "actual_min": actual,
                     "error_min": actual - predicted})
    if not rows:
        raise ValueError(f"no completed approaches after warmup; {incomplete} incomplete")
    frame = pd.DataFrame(rows)

    def summary(group):
        errors = group.error_min
        return {"n": len(group), "estimated_median_min": float(group.estimated_min.median()),
                "actual_median_min": float(group.actual_min.median()),
                "error_median_min": float(errors.median()), "error_p90_min": float(errors.quantile(0.9)),
                "candidate_buffer_p90_min": max(0.0, float(errors.quantile(0.9)))}

    groups = []
    for (source, station), group in frame.groupby(["source", "station"], dropna=False):
        groups.append({"source": source, "station": station, **summary(group)})
    return frame, {"overall": summary(frame), "by_source_station": groups,
                   "incomplete": incomplete, "warmup_min": warmup_min,
                   "note": "Times and buffer candidates are simulated, not calibrated against AIS. "
                           "Use independent runs and adequate sample sizes before setting a buffer."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path)
    parser.add_argument("--warmup-days", type=float, default=0)
    parser.add_argument("--output", type=Path, required=True, help="output CSV with individual observations")
    parser.add_argument("--summary", type=Path, required=True, help="output JSON with quantiles")
    args = parser.parse_args()
    frame, summary = analyse(pd.read_csv(args.events), args.warmup_days * 1440)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output, index=False)
    args.summary.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
