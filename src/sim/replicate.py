"""Replications: the same configuration run with several seeds, with confidence intervals and a warm-up check.

    py src/sim/replicate.py --days 14 --reps 5 --label baseline
    py src/sim/replicate.py --days 14 --reps 5 --seed 100 --workers 3 --containers nhpp

One run is one draw: a result is the mean over independent replications with its confidence interval. Each
replication i runs with seed + i and is saved in results/replications/<id>_<label>/rep_<seed>/ (ships.csv,
timeseries.csv, summary.json; no positions or viewer). The folder also gets:

    replications.csv   one row per replication, one column per result
    results.csv        per result: mean, standard deviation, half-width and bounds of the 95 % confidence
                       interval (Student's t, n - 1 degrees of freedom), n
    warmup.csv         ships in the area per step: every replication, their mean and its moving average
    warmup.png         the same as a plot (Welch's procedure), with the warm-up used and the one suggested

Warm-up. The run starts empty. Welch's procedure: average the ships in the area over the replications at each
step, smooth with a moving average of one day (one tide and day cycle each side would hide less; a day removes
the daily pattern), and read off where the curve stops rising. The suggestion here is the first time the smoothed
curve reaches the band it keeps over the last half of the run (a later excursion, a storm or a busy week, is not
warm-up; asking that it stay inside for good made one late dip read as never settling) (its mean there +- twice its
standard deviation there, at least 5 %: the weekly pattern alone moves it by 3 %). Ships that entered before --warmup are left out of the statistics; if
the suggestion is later than --warmup, run again with a longer one.

Two configurations are compared on the same seeds: the arrivals, the ships' attributes and the weather come from
their own random streams (engine.STREAMS), so replication i has the same ships arriving in the same weather in
both, and the difference per seed (a paired t interval) is far tighter than the difference of two means.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "replications"
STEP_MIN = 5.0
PER_CLASS = ("n", "hours_in_area_mean", "anchored_h_mean", "wait_clearance_h_mean", "lock_queue_h_mean",
             "in_lock_h_mean", "at_berth_h_mean", "sailing_h_mean")


def flatten(summary):
    """The numbers of a run's summary as one flat row."""
    row = {k: summary[k] for k in ("ships_generated", "ships_finished_after_warmup", "still_in_area",
                                   "removed_infeasible", "anchored_mean") if k in summary}
    for cls, d in summary.get("per_class", {}).items():
        for k in PER_CLASS:
            if k in d:
                row[f"{cls}.{k}"] = d[k]
    for group in ("utilisation_mean", "release_valves", "containers", "locks"):
        for k, v in (summary.get(group) or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                row[f"{group}.{k}"] = v
    return row


def one(job):
    """One replication (a worker process): run, save the small outputs, return its row and its series."""
    cfg, seed, out = job
    sys.path.insert(0, str(ROOT / "src" / "sim"))
    import engine

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    t0 = time.time()
    sim = engine.Simulation(start=cfg["start"], days=cfg["days"], seed=seed, delays=cfg["delays"],
                            warmup_days=cfg["warmup"], background=cfg["background"], weather_mode=cfg["weather"],
                            container_mode=cfg["containers"], container_rate=cfg["container_rate"],
                            bunching=cfg["bunching"], routing=cfg["routing"], checks=cfg["checks"])
    sim.run(progress_hours=1e9)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ships = sim.ship_table()
    ships.to_csv(out / "ships.csv", index=False)
    series = pd.DataFrame(sim.series)
    series.to_csv(out / "timeseries.csv", index=False)
    summary = sim.summary(ships)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return {"seed": seed, "wall_s": round(time.time() - t0), **flatten(summary)}, series["ships"].to_numpy()


def interval(values, level=0.95):
    """Mean, standard deviation and the half-width of the confidence interval of the mean (Student's t)."""
    from scipy import stats

    x = np.asarray([v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))], dtype=float)
    n = len(x)
    if n == 0:
        return {"mean": None, "sd": None, "half_width": None, "low": None, "high": None, "n": 0}
    mean = float(x.mean())
    if n == 1:
        return {"mean": mean, "sd": None, "half_width": None, "low": None, "high": None, "n": 1}
    sd = float(x.std(ddof=1))
    h = float(stats.t.ppf(0.5 + level / 2, n - 1) * sd / math.sqrt(n))
    return {"mean": mean, "sd": sd, "half_width": h, "low": mean - h, "high": mean + h, "n": n}


def welch(series, window_steps):
    """Welch's procedure on the ships in the area. series: (replications, steps). Returns the mean per step,
    its moving average (window_steps each side, shorter at the ends) and the suggested warm-up in steps (None
    when the curve never settles)."""
    mean = np.asarray(series, dtype=float).mean(axis=0)
    n = len(mean)
    c = np.r_[0.0, np.cumsum(mean)]
    lo = np.maximum(np.arange(n) - window_steps, 0)
    hi = np.minimum(np.arange(n) + window_steps + 1, n)
    smooth = (c[hi] - c[lo]) / (hi - lo)
    tail = smooth[n // 2:]
    level, band = float(tail.mean()), max(2.0 * float(tail.std()), 0.05 * float(tail.mean()))
    inside = np.flatnonzero(np.abs(smooth - level) <= band)
    first = int(inside[0]) if len(inside) else None
    return mean, smooth, (first if first is not None and first < n // 2 else None)


def next_folder(label):
    OUT.mkdir(parents=True, exist_ok=True)
    ids = [int(p.name[:4]) for p in OUT.iterdir() if p.is_dir() and p.name[:4].isdigit()]
    name = f"{max(ids, default=0) + 1:04d}" + ("_" + "".join(ch if ch.isalnum() else "-" for ch in label) if label else "")
    return OUT / name


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--label", default="")
    p.add_argument("--reps", type=int, default=5, help="replications")
    p.add_argument("--seed", type=int, default=1, help="seed of the first replication; the others follow it")
    p.add_argument("--workers", type=int, default=2, help="replications run at once (each holds its own graph)")
    p.add_argument("--start", default="2026-10-21 00:00")
    p.add_argument("--days", type=float, default=14.0, help="simulated days, warm-up included")
    p.add_argument("--warmup", type=float, default=2.0, help="days whose ships are left out of the statistics")
    p.add_argument("--no-delays", action="store_true")
    p.add_argument("--no-background", action="store_true")
    p.add_argument("--weather", choices=("bootstrap", "replay"), default="bootstrap")
    p.add_argument("--containers", choices=("replay", "weeks", "nhpp"), default="weeks")
    p.add_argument("--container-rate", type=float, default=1.0)
    p.add_argument("--no-bunching", action="store_true")
    p.add_argument("--routing", choices=("lanes", "shortest"), default="lanes")
    p.add_argument("--checks", action="store_true", help="check the model's invariants every step (slower)")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger("replicate")
    cfg = {"label": a.label, "reps": a.reps, "seed": a.seed, "start": a.start, "days": a.days, "warmup": a.warmup,
           "delays": not a.no_delays, "background": not a.no_background, "weather": a.weather,
           "containers": a.containers, "container_rate": a.container_rate, "bunching": not a.no_bunching,
           "routing": a.routing, "checks": a.checks}
    out = next_folder(a.label)
    out.mkdir(parents=True)
    (out / "config.json").write_text(json.dumps(cfg, indent=2))
    seeds = [a.seed + i for i in range(a.reps)]
    log.info("%d replications of %.1f days (seeds %d-%d), %d at once -> %s", a.reps, a.days, seeds[0], seeds[-1], a.workers, out)
    t0 = time.time()
    rows, series = [], []
    with ProcessPoolExecutor(max_workers=max(1, a.workers)) as pool:
        for row, s in pool.map(one, [(cfg, seed, str(out / f"rep_{seed}")) for seed in seeds]):
            rows.append(row)
            series.append(s)
            log.info("  seed %d done in %d s", row["seed"], row["wall_s"])
    reps = pd.DataFrame(rows)
    reps.to_csv(out / "replications.csv", index=False)
    results = pd.DataFrame({k: interval(reps[k]) for k in reps.columns if k not in ("seed", "wall_s")}).T
    results.index.name = "result"
    results.to_csv(out / "results.csv")

    n = min(len(s) for s in series)
    series = np.vstack([s[:n] for s in series])
    mean, smooth, warm = welch(series, int(12 * 60 / STEP_MIN))
    days = np.arange(n) * STEP_MIN / 1440
    w = pd.DataFrame({"day": days.round(4), **{f"seed_{s}": series[i] for i, s in enumerate(seeds)},
                      "mean": mean.round(2), "moving_average": smooth.round(2)})
    w.to_csv(out / "warmup.csv", index=False)
    suggested = None if warm is None else math.ceil(warm * STEP_MIN / 1440 * 2) / 2
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(9, 4.5))
        for i in range(len(seeds)):
            ax.plot(days, series[i], color="0.8", lw=0.6)
        ax.plot(days, mean, color="0.45", lw=0.8, label="mean of the replications")
        ax.plot(days, smooth, color="C0", lw=2, label="moving average (1 day)")
        ax.axvline(a.warmup, color="C3", ls="--", label=f"warm-up used ({a.warmup:g} d)")
        if suggested is not None:
            ax.axvline(suggested, color="C2", ls=":", label=f"suggested ({suggested:g} d)")
        ax.set_xlabel("day")
        ax.set_ylabel("ships in the area")
        ax.legend(frameon=False)
        fig.tight_layout()
        fig.savefig(out / "warmup.png", dpi=130)
    except ImportError:
        log.info("matplotlib not installed: no warmup.png (warmup.csv has the numbers)")

    log.info("\n%d replications in %.0f min. 95 %% confidence intervals:", len(reps), (time.time() - t0) / 60)
    show = ["anchored_mean", "removed_infeasible"] + [k for k in results.index if k.endswith("hours_in_area_mean")
                                                      or k.startswith("release_valves") or k.startswith("containers.")]
    for k in show:
        if k in results.index and results.loc[k, "mean"] is not None:
            r = results.loc[k]
            hw = "" if r["half_width"] is None or pd.isna(r["half_width"]) else f" +- {r['half_width']:.2f}"
            log.info("  %-42s %9.2f%s", k, r["mean"], hw)
    if suggested is None:
        log.warning("warm-up: the ships in the area never settle in the first half of the run: run longer")
    elif suggested > a.warmup:
        log.warning("warm-up: the port fills until about day %g, but --warmup is %g: run again with --warmup %g",
                    suggested, a.warmup, suggested)
    else:
        log.info("warm-up: the ships in the area settle by day %g (--warmup %g is enough)", suggested, a.warmup)
    log.info("results in %s", out)


if __name__ == "__main__":
    main()
