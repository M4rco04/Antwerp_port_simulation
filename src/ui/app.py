"""Setup page for the simulation: set a run up, start it, follow it, open its viewer.

    py src/ui/app.py                 # http://127.0.0.1:8800 opens in the browser
    py src/ui/app.py --port 8801 --no-browser

A local web page (standard library only). Each run goes through the pipeline
(src/sim/pipeline.py): it gets the next id and its own folder results/runs/<id>/ with its output
and its viewer, which the page links to. One run at a time (a run holds the whole port model in
memory); it runs as its own process, so the page stays responsive. Stopping a run ends it after the
current step and saves it like a finished run (output, log, viewer); a second, forced stop kills it.
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

PAGE = Path(__file__).with_name("index.html")
ACTIVE = ("queued", "loading", "running", "saving", "building viewer", "stopping")
TYPES = {".html": "text/html; charset=utf-8", ".json": "application/json", ".csv": "text/csv; charset=utf-8",
         ".log": "text/plain; charset=utf-8", ".txt": "text/plain; charset=utf-8", ".gz": "application/gzip"}
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


def running():
    return [k for k, p in procs.items() if p.poll() is None]


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
        if path == "/api/runs":
            return self.send(200, {"runs": runs(), "running": running()})
        if path.startswith("/api/runs/") and path.endswith("/log"):
            rid = path.split("/")[3]
            f = PL.RUNS / rid / "run.log"
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()[-60:] if f.is_file() else []
            return self.send(200, {"lines": lines})
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
                try:
                    cfg = PL.clean_config(body)
                except (ValueError, TypeError) as e:
                    return self.send(400, {"error": str(e)})
                run_dir = PL.new_run(cfg)
                log = open(run_dir / "process.log", "w", encoding="utf-8")
                procs[run_dir.name] = subprocess.Popen(
                    [sys.executable, str(ROOT / "src" / "sim" / "pipeline.py"), "--run-dir", str(run_dir)],
                    cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return self.send(201, {"id": run_dir.name})
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


if __name__ == "__main__":
    main()
