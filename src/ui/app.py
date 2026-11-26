"""Setup page for the simulation: set a run up, start it, follow it, open its viewer.

    py src/ui/app.py                 # http://127.0.0.1:8800 opens in the browser
    py src/ui/app.py --port 8801 --no-browser

A local web page (standard library only). Each run goes through the pipeline
(src/sim/pipeline.py): its label is its id and its folder results/runs/<label>/ with its output
and its viewer, which the page links to. One run at a time (a run holds the whole port model in
memory); it runs as its own process, so the page stays responsive. Stopping a run ends it after the
current step and saves it like a finished run (output, log, viewer); a second, forced stop kills it.

Evaluations (src/ui/evaluations.py): several strategies on the same seeds with src/sim/replicate.py, one after the
other, compared with the baseline seed by seed. Never beside a single run (memory).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "sim"))
import pipeline as PL                                      # noqa: E402
for _sub in ("agents", "environment", "data"):             # what the strategies import (vts_api, ...)
    if str(ROOT / "src" / _sub) not in sys.path:
        sys.path.insert(0, str(ROOT / "src" / _sub))
if str(ROOT / "src") not in sys.path:
    sys.path.append(str(ROOT / "src"))

import evaluations as EV                                   # noqa: E402  (src/ui/evaluations.py)

PAGE = Path(__file__).with_name("index.html")
ACTIVE = ("queued", "loading", "running", "saving", "building viewer", "stopping")
TYPES = {".html": "text/html; charset=utf-8", ".json": "application/json", ".csv": "text/csv; charset=utf-8",
         ".log": "text/plain; charset=utf-8", ".txt": "text/plain; charset=utf-8", ".gz": "application/gzip"}
# the strategies the setup page offers first, in this order, with a label; any other one in src/strategies follows
STRATEGY_ORDER = {"baseline": "Baseline: first come first served (reference)",
                  "local_lookahead": "S1 Local look-ahead",
                  "chain_planning": "S2 Chain planning",
                  "equilibrium_guidance": "S3 Equilibrium guidance",
                  "evolutionary_guidance": "S4 Equilibrium guidance with a genetic algorithm"}
procs: dict[str, subprocess.Popen] = {}
lock = threading.Lock()


def runs():
    """All runs, newest first; a run whose process is gone without finishing is marked so."""
    out = PL.list_runs()
    for r in out:
        st = r["status"].get("state")
        p = procs.get(r["id"])
        if st in ACTIVE and (p is None or p.poll() is not None):
            r["status"]["state"] = "interrupted"
        elif st in ("loading", "running") and (PL.RUNS / r["id"] / PL.STOP_FILE).exists():
            r["status"]["state"] = "stopping"
    return out


def strategy_list():
    """The VTS strategies a run can be given (src/strategies), the reference and the four port strategies first."""
    import strategies
    found = strategies.available()
    names = [n for n in STRATEGY_ORDER if n in found] + sorted(n for n in found if n not in STRATEGY_ORDER)
    return [{"name": n, "label": STRATEGY_ORDER.get(n, n), "description": found[n].description,
             "levers": list(found[n].levers)} for n in names]


def running():
    return [k for k, p in procs.items() if p.poll() is None]


def run_dir(rid):
    """The folder of a run named in a URL, or None (a run id is a folder name: no path parts)."""
    if not rid or rid in (".", "..") or not PL.NAME_CHARS.sub("", rid) == rid:
        return None
    f = PL.RUNS / rid
    return f if f.is_dir() else None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else (json.dumps(body, default=str) if not isinstance(body, str) else body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = unquote(self.path.split("?")[0])
        if path in ("/", "/index.html"):
            return self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/defaults":
            return self.send(200, PL.DEFAULTS)
        if path == "/api/strategies":
            try:
                return self.send(200, {"strategies": strategy_list()})
            except Exception as e:                        # a broken strategy module: the page keeps the baseline
                return self.send(500, {"error": f"{type(e).__name__}: {e}", "strategies": []})
        if path == "/api/runs":
            return self.send(200, {"runs": runs(), "running": running()})
        if path.startswith("/api/runs/") and path.endswith("/log"):
            d = run_dir(path.split("/")[3])
            f = d / "run.log" if d else None
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()[-60:] if f and f.is_file() else []
            return self.send(200, {"lines": lines})
        if path == "/api/evaluations":
            return self.send(200, {"evaluations": EV.list_evaluations(), "running": EV.running(),
                                   "scenarios": EV.SCENARIOS, "max_workers": EV.MAX_WORKERS})
        if path.startswith("/api/evaluations/") and path.endswith("/compare"):
            got = EV.compare(path.split("/")[3])
            return self.send(200, got) if got else self.send(404, {"error": "no such evaluation"})
        if path.startswith("/api/evaluations/") and "/log/" in path:
            parts = path.split("/")
            return self.send(200, {"lines": EV.log_tail(parts[3], int(parts[5]))})
        if path.startswith("/runs/"):                    # files of a run folder (the viewer, outputs)
            f = (PL.RUNS / path[len("/runs/"):]).resolve()
            if PL.RUNS.resolve() in f.parents and f.is_file():
                return self.send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))
        return self.send(404, {"error": "not found"})

    def do_POST(self):
        path = unquote(self.path.split("?")[0])
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        if path == "/api/runs":
            with lock:
                if running():
                    return self.send(409, {"error": f"run {running()[0]} is still going: wait for it or stop it"})
                if EV.running():
                    return self.send(409, {"error": f"evaluation {EV.running()} is going: one model at a time (memory)"})
                try:
                    cfg = PL.clean_config(body)
                    run_dir = PL.new_run(cfg)                 # its folder is its label: refused when used
                except (ValueError, TypeError) as e:
                    return self.send(400, {"error": str(e)})
                log = open(run_dir / "process.log", "w", encoding="utf-8")
                procs[run_dir.name] = subprocess.Popen(
                    [sys.executable, str(ROOT / "src" / "sim" / "pipeline.py"), "--run-dir", str(run_dir)],
                    cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return self.send(201, {"id": run_dir.name})
        if path == "/api/evaluations":
            with lock:
                if running():
                    return self.send(409, {"error": f"run {running()[0]} is still going: wait for it or stop it"})
                if EV.running():
                    return self.send(409, {"error": f"evaluation {EV.running()} is still going"})
                try:
                    import strategies
                    settings = EV.clean(body, strategies.available())
                    folder, plan = EV.create(settings)        # refuses a label already used
                except (ValueError, TypeError) as e:
                    return self.send(400, {"error": str(e)})
                EV.start(folder, plan)
            return self.send(201, {"id": plan["id"]})
        if path.startswith("/api/evaluations/") and path.endswith("/stop"):
            eid = path.split("/")[3]
            return self.send(202, {"stopping": eid}) if EV.stop(eid) else self.send(404, {"error": "that evaluation is not going"})
        if path.startswith("/api/runs/") and path.endswith("/stop"):
            rid = path.split("/")[3]
            p = procs.get(rid)
            if p is None or p.poll() is not None:
                return self.send(404, {"error": "that run is not going"})
            flag = PL.RUNS / rid / PL.STOP_FILE
            if body.get("force") and flag.exists():         # asked again: kill it, nothing more is saved
                p.terminate()
                p.wait(timeout=30)
                flag.unlink(missing_ok=True)
                PL.write_status(PL.RUNS / rid, state="failed", error="killed from the setup page (not saved)",
                                finished=PL.now_iso())
                PL.write_index()
                return self.send(200, {"killed": rid})
            # the run finishes its step, saves everything and builds its viewer, as if it had finished
            flag.write_text(PL.now_iso())
            return self.send(202, {"stopping": rid})
        return self.send(404, {"error": "not found"})


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--port", type=int, default=8800)
    a.add_argument("--no-browser", action="store_true")
    args = a.parse_args()
    PL.RUNS.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Simulation setup page: {url}  (Ctrl+C to stop; a run in progress is stopped with it)")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs.values():
            if p.poll() is None:
                p.terminate()
        if EV.running():
            EV.stop(EV.running())


if __name__ == "__main__":
    main()
