"""Evaluations started from the setup page: several strategies, each run on the same seeds with src/sim/replicate.py,
one after the other, and compared with the baseline seed by seed (docs/strategies/run_plan.md, phase 3).

Each evaluation has a folder results/evaluations/<label>/ (its id; eval-<date>-<time> without a label) with
    plan.json       the settings and, per strategy, its state, its replicate.py folder and when it ran
    <n>_<name>.log  the output of that strategy's replicate.py
The page reads plan.json; the comparison is computed from the replications.csv files when it is asked for.

One evaluation at a time, and never beside a single run: a replication set holds up to --workers copies of the model
(15.6 GB of memory on this machine: project memory). Stopping kills the replicate.py going (and its workers) and
cancels the strategies not started yet; the finished ones keep their results.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVALS = ROOT / "results" / "evaluations"
REPLICATIONS = ROOT / "results" / "replications"
REPLICATE = ROOT / "src" / "sim" / "replicate.py"

SCENARIOS = {          # docs/strategies/run_plan.md: the same container process in all three, only the load differs
    "base": {"containers": "nhpp", "container_rate": 1.0, "background_rate": 1.0},
    "loaded": {"containers": "nhpp", "container_rate": 1.25, "background_rate": 1.25},
    "stress": {"containers": "nhpp", "container_rate": 1.25, "background_rate": 1.75},
}
MAX_WORKERS = 3                                    # the most that has run without running out of memory

# what the comparison shows: (column of replications.csv, label, unit); classes are added below
METRICS = [
    ("anchored_mean", "Ships at anchor (mean)", "ships"),
    ("containers.berth_delay_h_mean", "Container berth delay, mean", "h"),
    ("containers.late_over_2h_share", "Containers more than 2 h late", "share"),
    ("containers.late_over_12h_share", "Containers more than 12 h late", "share"),
    ("emissions.after_warmup_per_day.fuel_t", "Fuel in the area", "t/day"),
    ("emissions.after_warmup_per_day.co2_t", "CO₂ in the area", "t/day"),
    ("emissions.after_warmup_per_day.nox_t", "NOₓ in the area", "t/day"),
    ("utilisation_mean.pilot_boats_busy", "Pilot boats busy (mean)", "boats"),
    ("utilisation_mean.pilots_busy_river", "River pilots busy (mean)", "pilots"),
    ("silent.anchorage_full", "Anchorage full (hidden shortage)", "events"),
    ("removed_infeasible", "Ships removed (infeasible)", "ships"),
]
CLASSES = ("container", "bulk_general", "tanker", "inland_cargo", "inland_tanker", "passenger")
PER_CLASS = (("hours_in_area_mean", "time in the area"), ("anchored_h_mean", "at anchor"),
             ("wait_clearance_h_mean", "waiting for clearance"), ("lock_queue_h_mean", "in lock queues"))

_lock = threading.Lock()
_current = {"id": None, "proc": None, "stop": False}


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _slug(text):
    return "".join(ch if ch.isalnum() else "-" for ch in str(text or "")).strip("-")[:40]


def _read(folder):
    try:
        return json.loads((folder / "plan.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write(folder, plan):
    tmp = folder / "plan.json.tmp"
    tmp.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    tmp.replace(folder / "plan.json")


def folder_of(eid):
    f = EVALS / str(eid)
    return f if EVALS.is_dir() and "/" not in str(eid) and "\\" not in str(eid) and f.is_dir() else None


def running():
    """The id of the evaluation going now, or None."""
    return _current["id"] if _current.get("thread_alive") else None


def list_evaluations():
    """Every evaluation, newest first; one marked as going whose runner is gone (the page was restarted) is shown as
    interrupted."""
    out = []
    if not EVALS.is_dir():
        return out
    plans = [(f, _read(f)) for f in EVALS.iterdir() if f.is_dir()]
    for f, plan in sorted(((f, p) for f, p in plans if p), key=lambda fp: fp[1].get("created") or "", reverse=True):
        if plan["state"] in ("queued", "running", "stopping") and plan["id"] != running():
            plan["state"] = "interrupted"
            for it in plan["items"]:
                if it["state"] in ("queued", "running"):
                    it["state"] = "interrupted"
        out.append(plan)
    return out


def clean(body, available):
    """Check and complete the settings of a new evaluation (ValueError when they are wrong)."""
    strategies = [s for s in (body.get("strategies") or []) if s]
    if not strategies:
        raise ValueError("choose at least one strategy")
    unknown = [s for s in strategies if s not in available]
    if unknown:
        raise ValueError(f"unknown strategies: {', '.join(unknown)}")
    if "baseline" not in strategies and body.get("with_baseline", True):
        strategies = ["baseline"] + strategies                  # the reference every strategy is compared with
    scenario = body.get("scenario", "loaded")
    traffic = dict(SCENARIOS[scenario]) if scenario in SCENARIOS else None
    if traffic is None:
        if scenario != "custom":
            raise ValueError(f"unknown scenario {scenario!r}")
        traffic = {"containers": body.get("containers", "nhpp"), "container_rate": float(body.get("container_rate", 1.0)),
                   "background_rate": float(body.get("background_rate", 1.0))}
    days, warmup = float(body.get("days", 18)), float(body.get("warmup", 11))
    reps, seed, workers = int(body.get("reps", 3)), int(body.get("seed", 2001)), int(body.get("workers", 3))
    if not 0 <= warmup < days:
        raise ValueError("the warm-up must be shorter than the run")
    if not 1 <= reps <= 20:
        raise ValueError("replications: 1 to 20")
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"replications at once: 1 to {MAX_WORKERS} (memory)")
    options = body.get("options") or {}
    if not isinstance(options, dict):
        raise ValueError("options must be {strategy: {key: value}}")
    return {"label": str(body.get("label") or "").strip(), "scenario": scenario, **traffic, "days": days,
            "warmup": warmup, "reps": reps, "seed": seed, "workers": workers,
            "start": str(body.get("start") or "2026-10-21 00:00"), "weather": body.get("weather", "bootstrap"),
            "strategies": strategies, "options": {k: v for k, v in options.items() if k in strategies}}


def create(settings):
    """The evaluation's folder, named by its label (refused when the label is used: ValueError), and its plan."""
    sys.path.insert(0, str(ROOT / "src" / "sim"))
    from pipeline import new_folder
    folder = new_folder(EVALS, settings["label"], f"eval-{settings['scenario']}")
    eid = label = folder.name
    items = [{"n": i + 1, "strategy": s, "options": settings["options"].get(s, {}), "state": "queued",
              "replication": None, "started": None, "finished": None, "returncode": None,
              "log": f"{i + 1:02d}_{_slug(s)}.log"} for i, s in enumerate(settings["strategies"])]
    plan = {"id": eid, "folder": folder.name, "label": label, "created": now_iso(), "state": "queued",
            "settings": settings, "items": items, "started": None, "finished": None}
    _write(folder, plan)
    return folder, plan


def command(settings, item, eval_label):
    s = settings
    label = f"{eval_label}-{item['strategy']}"            # the replication's folder: unique as the evaluation is
    cmd = [sys.executable, str(REPLICATE), "--label", label, "--days", str(s["days"]), "--warmup", str(s["warmup"]),
           "--reps", str(s["reps"]), "--seed", str(s["seed"]), "--workers", str(s["workers"]),
           "--start", s["start"], "--weather", s["weather"], "--containers", s["containers"],
           "--container-rate", str(s["container_rate"]), "--background-rate", str(s["background_rate"]),
           "--vts", item["strategy"]]
    for k, v in (item.get("options") or {}).items():
        cmd += ["--vts-option", f"{k}={json.dumps(v)}"]
    return cmd


def start(folder, plan):
    """Run the plan's strategies one after the other in a background thread."""
    with _lock:
        _current.update(id=plan["id"], proc=None, stop=False, thread_alive=True)
    t = threading.Thread(target=_run, args=(folder, plan["id"]), daemon=True)
    t.start()


def _run(folder, eid):
    try:
        plan = _read(folder)
        plan["state"], plan["started"] = "running", now_iso()
        _write(folder, plan)
        for i, item in enumerate(plan["items"]):
            if _current["stop"]:
                break
            item["state"], item["started"] = "running", now_iso()
            _write(folder, plan)
            with open(folder / item["log"], "w", encoding="utf-8") as log:
                proc = subprocess.Popen(command(plan["settings"], item, plan["id"]), cwd=str(ROOT), stdout=log,
                                        stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                _current["proc"] = proc
                while proc.poll() is None:
                    time.sleep(2)
                    if item["replication"] is None:
                        item["replication"] = _replication_folder(folder / item["log"])
                        if item["replication"]:
                            _write(folder, plan)
            item["returncode"] = proc.returncode
            item["replication"] = item["replication"] or _replication_folder(folder / item["log"])
            item["finished"] = now_iso()
            item["state"] = "stopped" if _current["stop"] else ("done" if proc.returncode == 0 else "failed")
            _write(folder, plan)
        for item in plan["items"]:
            if item["state"] == "queued":
                item["state"] = "cancelled"
        states = {it["state"] for it in plan["items"]}
        plan["state"] = ("stopped" if _current["stop"] else "failed" if "failed" in states else "done")
        plan["finished"] = now_iso()
        _write(folder, plan)
    finally:
        with _lock:
            _current.update(id=None, proc=None, stop=False, thread_alive=False)


def _replication_folder(log_path):
    """replicate.py's folder, from the first line of its log ("... -> <folder>")."""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"->\s*(.+?replications[\\/][^\s\\/]+)", text)
    return Path(m.group(1).strip()).name if m else None


def stop(eid):
    """Stop the evaluation going: kill its replicate.py and the workers, cancel the rest."""
    if running() != eid:
        return False
    _current["stop"] = True
    p = _current["proc"]
    if p is not None and p.poll() is None:
        if sys.platform == "win32":                  # the process pool's workers are children: kill the tree
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
        else:
            p.terminate()
    return True


def log_tail(eid, n, lines=60):
    folder = folder_of(eid)
    plan = _read(folder) if folder else None
    if not plan:
        return []
    item = next((it for it in plan["items"] if it["n"] == n), None)
    f = folder / item["log"] if item else None
    if not f or not f.is_file():
        return []
    return f.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]


# ------------------------------------------------------------------ the comparison
def _t_half_width(diffs):
    from scipy import stats
    n = len(diffs)
    if n < 2:
        return None
    mean = sum(diffs) / n
    sd = math.sqrt(sum((d - mean) ** 2 for d in diffs) / (n - 1))
    return float(stats.t.ppf(0.975, n - 1) * sd / math.sqrt(n))


def compare(eid):
    """Each strategy against the baseline, seed by seed: for every metric the baseline's mean, the strategy's mean, the
    mean paired difference with its 95 % interval (Student's t over the seeds) and whether the interval excludes 0."""
    import pandas as pd

    folder = folder_of(eid)
    plan = _read(folder) if folder else None
    if not plan:
        return None
    reps = {}
    for it in plan["items"]:
        if it["state"] == "done" and it["replication"]:
            f = REPLICATIONS / it["replication"] / "replications.csv"
            if f.is_file():
                reps[it["strategy"]] = pd.read_csv(f).set_index("seed")
    metrics = list(METRICS) + [(f"{c}.{k}", f"{c.replace('_', ' ')}: {lab}", "h") for c in CLASSES for k, lab in PER_CLASS]
    base = reps.get("baseline")
    rows = []
    for col, label, unit in metrics:
        if not any(col in df.columns for df in reps.values()):
            continue
        row = {"metric": col, "label": label, "unit": unit, "strategies": {}}
        b = base[col] if base is not None and col in base.columns else None
        row["baseline"] = None if b is None or b.dropna().empty else float(b.mean())
        for name, df in reps.items():
            if name == "baseline" or col not in df.columns:
                continue
            cell = {"mean": None if df[col].dropna().empty else float(df[col].mean())}
            if b is not None:
                seeds = [s for s in df.index if s in b.index and pd.notna(df.at[s, col]) and pd.notna(b.at[s])]
                diffs = [float(df.at[s, col] - b.at[s]) for s in seeds]
                if diffs:
                    d = sum(diffs) / len(diffs)
                    hw = _t_half_width(diffs)
                    cell.update(diff=d, half_width=hw, seeds=len(diffs),
                                pct=(100.0 * d / row["baseline"]) if row["baseline"] else None,
                                significant=bool(hw is not None and abs(d) > hw))
            row["strategies"][name] = cell
        rows.append(row)
    names = [it["strategy"] for it in plan["items"] if it["strategy"] in reps and it["strategy"] != "baseline"]
    return {"id": eid, "label": plan["label"], "strategies": names, "has_baseline": base is not None, "rows": rows}
