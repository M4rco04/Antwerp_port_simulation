"""The simulation pipeline: configuration -> numbered run folder -> simulation -> viewer.

Every run gets the next free id and its own folder, results/runs/<id>/ (0001, 0002, ...):

    config.json      the settings it was run with
    status.json      queued / running / building viewer / done / stopped / failed, with progress and timings
                     (stopped: stopped from the setup page; saved and given a viewer like a finished run)
    run.log          the simulation's log (status lines, warnings)
    ...              the simulation output (ships.csv, events.csv, positions.csv.gz, routes.json, ...)
    viewer.html      the interactive viewer (src/viz/build_viewer.py), built at the end of every run

results/runs/index.html lists all runs with links to their viewers. Runs are started from the setup
page (py src/ui/app.py) or from the command line:

    py src/sim/pipeline.py --days 7 --label "baseline"
    py src/sim/engine.py --days 7                       # the same: the engine runs through the pipeline
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import re
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "results" / "runs"
sys.path.insert(0, str(ROOT / "src" / "sim"))
sys.path.insert(0, str(ROOT / "src" / "viz"))

DEFAULTS = {
    "label": "",
    "start": "2026-10-21 00:00",       # simulated start (UTC)
    "days": 7.0,                       # simulated days, warm-up included
    "warmup": 2.0,                     # days whose ships are left out of the statistics
    "seed": 1,
    "weather": "bootstrap",            # bootstrap: real days of the same season; replay: the observed dates
    "containers": "replay",            # replay the schedule, or nhpp: a Poisson process fitted to it
    "container_rate": 1.0,             # nhpp: multiplies the container arrival rate
    "bunching": True,                  # nhpp: daily gamma factor (liner calls bunch)
    "delays": True,                    # replay: draw the AIS delay against the schedule
    "background": True,                # non-container traffic
    "routing": "lanes",                # lanes: hold the starboard side of the buoyed fairway; shortest: shortest path
    "max_minutes": 60.0,               # stop (and save) after this much wall-clock time
    "progress_hours": 2.0,             # simulated hours between status lines
}
STOP_FILE = "stop.request"           # written by the setup page: finish the step, save, build the viewer
DAY_LINE = re.compile(r"day\s+([\d.]+)\s*\|")


def clean_config(cfg: dict) -> dict:
    """Defaults filled in, values of the right type, nonsense refused (ValueError)."""
    out = dict(DEFAULTS)
    out.update({k: v for k, v in (cfg or {}).items() if k in DEFAULTS and v is not None and v != ""})
    for k in ("days", "warmup", "container_rate", "max_minutes", "progress_hours"):
        out[k] = float(out[k])
    out["seed"] = int(out["seed"])
    for k in ("bunching", "delays", "background"):
        out[k] = out[k] if isinstance(out[k], bool) else str(out[k]).lower() in ("1", "true", "yes", "on")
    out["label"] = str(out["label"])[:80]
    import pandas as pd
    out["start"] = str(pd.Timestamp(out["start"]).strftime("%Y-%m-%d %H:%M"))
    if out["weather"] not in ("bootstrap", "replay"):
        raise ValueError("weather must be bootstrap or replay")
    if out["routing"] not in ("lanes", "shortest"):
        raise ValueError("routing must be lanes or shortest")
    if out["containers"] not in ("replay", "nhpp"):
        raise ValueError("containers must be replay or nhpp")
    if not 0 < out["days"] <= 60:
        raise ValueError("days must be between 0 and 60")
    if not 0 <= out["warmup"] < out["days"]:
        raise ValueError("the warm-up must be shorter than the run")
    if not 0 < out["container_rate"] <= 5:
        raise ValueError("container rate must be between 0 and 5")
    if out["max_minutes"] <= 0:
        raise ValueError("max minutes must be positive")
    return out


# ---------------------------------------------------------------------------------------------
# run folders

def run_ids():
    return sorted(int(p.name) for p in RUNS.glob("[0-9][0-9][0-9][0-9]") if p.is_dir())


def new_run(cfg: dict) -> Path:
    """Create the next run folder with its config and a queued status; returns its path."""
    RUNS.mkdir(parents=True, exist_ok=True)
    n = (run_ids() or [0])[-1] + 1
    while True:
        path = RUNS / f"{n:04d}"
        try:
            path.mkdir()
            break
        except FileExistsError:
            n += 1
    (path / "config.json").write_text(json.dumps(cfg, indent=2))
    write_status(path, state="queued", created=now_iso(), progress=0.0)
    write_index()
    return path


def now_iso():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def read_status(path: Path) -> dict:
    try:
        return json.loads((path / "status.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_status(path: Path, **fields):
    st = read_status(path)
    st.update(fields, id=path.name)
    tmp = path / "status.json.tmp"
    tmp.write_text(json.dumps(st, indent=2, default=str))
    tmp.replace(path / "status.json")


class ProgressHandler(logging.Handler):
    """Turns the engine's status lines ("day 3.00 | ...") into status.json progress."""

    def __init__(self, path, days):
        super().__init__(logging.INFO)
        self.path, self.days, self.last = path, days, 0.0

    def emit(self, record):
        msg = record.getMessage()
        m = DAY_LINE.search(msg)
        if m:
            day = float(m.group(1))
            if time.time() - self.last > 2 or day >= self.days:
                self.last = time.time()
                write_status(self.path, progress=round(min(day / self.days, 1.0), 4), last_line=msg.strip())


# ---------------------------------------------------------------------------------------------
# running

def execute(path: Path) -> dict:
    """Run the simulation of a run folder, save its output and build its viewer."""
    cfg = clean_config(json.loads((path / "config.json").read_text()))
    root = logging.getLogger()
    fh = logging.FileHandler(path / "run.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    ph = ProgressHandler(path, cfg["days"])
    root.addHandler(fh)
    root.addHandler(ph)
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
    t0 = time.time()
    try:
        write_status(path, state="loading", started=now_iso(), progress=0.0, error=None)
        import engine
        sim = engine.Simulation(cfg["start"], cfg["days"], cfg["seed"], cfg["delays"], cfg["warmup"], cfg["background"],
                                weather_mode=cfg["weather"], container_mode=cfg["containers"],
                                container_rate=cfg["container_rate"], bunching=cfg["bunching"], routing=cfg["routing"])
        write_status(path, state="running")
        stop = path / STOP_FILE
        sim.run(cfg["progress_hours"], cfg["max_minutes"], should_stop=stop.exists)
        manual = sim.stop_reason == "stopped manually"
        write_status(path, state="saving", progress=round(min(sim.t / 1440 / cfg["days"], 1.0), 4) if manual else 1.0)
        summary = sim.save(path)
        write_status(path, state="building viewer")
        import build_viewer
        viewer, size = build_viewer.build(path)
        keep = ("days", "stopped_early", "stop_reason", "ships_generated", "ships_finished_after_warmup", "still_in_area",
                "removed_infeasible", "anchored_mean")
        stop.unlink(missing_ok=True)
        write_status(path, state="stopped" if manual else "done", finished=now_iso(), wall_s=round(time.time() - t0),
                     note=f"stopped manually at day {sim.t / 1440:.2f} of {cfg['days']:g}; everything up to then is saved" if manual else None,
                     viewer=viewer.name, viewer_mb=round(size / 1e6, 1), summary={k: summary.get(k) for k in keep})
        logging.getLogger("pipeline").info("run %s done in %.0f s: %s", path.name, time.time() - t0, path / viewer.name)
        return summary
    except Exception as e:                                   # the run fails, the folder says why
        logging.getLogger("pipeline").error("run %s failed: %s", path.name, e)
        (path / "error.txt").write_text(traceback.format_exc())
        write_status(path, state="failed", finished=now_iso(), wall_s=round(time.time() - t0), error=str(e))
        raise
    finally:
        root.removeHandler(fh)
        root.removeHandler(ph)
        fh.close()
        write_index()


def run(cfg: dict) -> Path:
    """New run folder for these settings, run it, return the folder."""
    path = new_run(clean_config(cfg))
    execute(path)
    return path


# ---------------------------------------------------------------------------------------------
# the list of runs

def list_runs():
    out = []
    for n in reversed(run_ids()):
        p = RUNS / f"{n:04d}"
        try:
            cfg = json.loads((p / "config.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            cfg = {}
        out.append({"id": p.name, "config": cfg, "status": read_status(p),
                    "viewer": (p / "viewer.html").is_file()})
    return out


def write_index():
    """results/runs/index.html: every run with its settings, state and a link to its viewer."""
    RUNS.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in list_runs():
        c, s = r["config"], r["status"]
        sm = s.get("summary") or {}
        link = f'<a href="{r["id"]}/viewer.html">open viewer</a>' if r["viewer"] else ""
        rows.append(f"<tr><td>{r['id']}</td><td>{html.escape(c.get('label', ''))}</td><td>{html.escape(s.get('state', ''))}</td>"
                    f"<td>{html.escape(str(c.get('start', '')))}</td><td>{c.get('days', '')}</td><td>{c.get('seed', '')}</td>"
                    f"<td>{html.escape(str(c.get('containers', '')))}</td><td>{sm.get('ships_generated', '')}</td>"
                    f"<td>{s.get('created', '')}</td><td>{link}</td></tr>")
    page = ("<!doctype html><meta charset='utf-8'><title>Simulation runs</title>"
            "<style>body{font:14px system-ui,sans-serif;margin:24px}table{border-collapse:collapse}"
            "td,th{padding:4px 10px;border-bottom:1px solid #ddd;text-align:left}</style>"
            "<h1>Simulation runs</h1><p>Start new runs from the setup page: <code>py src/ui/app.py</code></p>"
            "<table><tr><th>Id</th><th>Label</th><th>State</th><th>Start</th><th>Days</th><th>Seed</th>"
            "<th>Containers</th><th>Ships</th><th>Created</th><th></th></tr>" + "".join(rows) + "</table>")
    (RUNS / "index.html").write_text(page, encoding="utf-8")


# ---------------------------------------------------------------------------------------------

def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--label", default=DEFAULTS["label"], help="a name for the run")
    p.add_argument("--start", default=DEFAULTS["start"])
    p.add_argument("--days", type=float, default=DEFAULTS["days"])
    p.add_argument("--warmup", type=float, default=DEFAULTS["warmup"])
    p.add_argument("--seed", type=int, default=DEFAULTS["seed"])
    p.add_argument("--no-delays", action="store_true", help="containers berth at their scheduled time")
    p.add_argument("--no-background", action="store_true")
    p.add_argument("--weather", choices=("bootstrap", "replay"), default=DEFAULTS["weather"],
                   help="weather: real days of the same season drawn at random, or the observed dates")
    p.add_argument("--containers", choices=("replay", "nhpp"), default=DEFAULTS["containers"],
                   help="container ships: replay the schedule, or a Poisson process fitted to it")
    p.add_argument("--container-rate", type=float, default=DEFAULTS["container_rate"],
                   help="nhpp: multiply the fitted container arrival rate (scenarios)")
    p.add_argument("--no-bunching", action="store_true", help="nhpp: plain Poisson, without the daily gamma factor")
    p.add_argument("--routing", choices=("lanes", "shortest"), default=DEFAULTS["routing"],
                   help="lanes: ships hold the starboard side of the buoyed fairway; shortest: the shortest allowed path")
    p.add_argument("--progress-hours", type=float, default=DEFAULTS["progress_hours"], help="simulated hours between status lines")
    p.add_argument("--max-minutes", type=float, default=DEFAULTS["max_minutes"], help="stop (and save) after this much wall-clock time")
    p.add_argument("--run-dir", type=Path, help="run an existing, queued run folder (used by the setup page)")
    p.add_argument("--open", action="store_true", help="open the viewer when the run is done")
    return p


def main():
    a = parser().parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if a.run_dir:
        path = a.run_dir
        execute(path)
    else:
        cfg = {"label": a.label, "start": a.start, "days": a.days, "warmup": a.warmup, "seed": a.seed,
               "weather": a.weather, "containers": a.containers, "container_rate": a.container_rate,
               "bunching": not a.no_bunching, "delays": not a.no_delays, "background": not a.no_background,
               "routing": a.routing,
               "max_minutes": a.max_minutes, "progress_hours": a.progress_hours}
        path = new_run(clean_config(cfg))
        logging.getLogger("pipeline").info("run %s: %s", path.name, path)
        execute(path)
    print(f"run {path.name}: {path / 'viewer.html'}")
    if a.open:
        import webbrowser
        webbrowser.open((path / "viewer.html").resolve().as_uri())


if __name__ == "__main__":
    main()
