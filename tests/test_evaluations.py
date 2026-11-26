"""Evaluations from the setup page (src/ui/evaluations.py), without running anything: settings, the replicate.py command,
reading its folder from the log, and the paired comparison with the baseline on made-up replications."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "ui"))

import evaluations as EV  # noqa: E402

AVAILABLE = {"baseline": object, "local_lookahead": object, "chain_planning": object}


def test_settings_add_the_baseline_and_take_the_scenario():
    s = EV.clean({"strategies": ["local_lookahead"], "scenario": "stress"}, AVAILABLE)
    assert s["strategies"] == ["baseline", "local_lookahead"]
    assert (s["containers"], s["container_rate"], s["background_rate"]) == ("nhpp", 1.25, 1.75)
    assert (s["days"], s["warmup"], s["reps"], s["seed"], s["workers"]) == (18.0, 11.0, 3, 2001, 3)
    c = EV.clean({"strategies": ["chain_planning"], "scenario": "custom", "containers": "weeks",
                  "container_rate": 1.1, "background_rate": 1.4}, AVAILABLE)
    assert (c["containers"], c["container_rate"], c["background_rate"]) == ("weeks", 1.1, 1.4)


@pytest.mark.parametrize("body", [{"strategies": []}, {"strategies": ["nope"]},
                                  {"strategies": ["chain_planning"], "workers": 4},
                                  {"strategies": ["chain_planning"], "days": 5, "warmup": 5},
                                  {"strategies": ["chain_planning"], "scenario": "huge"}])
def test_bad_settings_are_refused(body):
    with pytest.raises(ValueError):
        EV.clean(body, AVAILABLE)


def test_the_command_is_a_replicate_call_with_the_strategy_and_its_options():
    s = EV.clean({"strategies": ["local_lookahead"], "options": {"local_lookahead": {"jit": False}}}, AVAILABLE)
    item = {"strategy": "local_lookahead", "options": s["options"]["local_lookahead"]}
    cmd = EV.command(s, item, "0007")
    assert cmd[1].endswith("replicate.py")
    assert cmd[cmd.index("--vts") + 1] == "local_lookahead"
    assert cmd[cmd.index("--vts-option") + 1] == "jit=false"
    assert cmd[cmd.index("--background-rate") + 1] == "1.25" and cmd[cmd.index("--workers") + 1] == "3"


def test_the_replication_folder_is_read_from_the_log(tmp_path):
    log = tmp_path / "x.log"
    log.write_text("3 replications of 18.0 days (seeds 2001-2003), 3 at once -> "
                   r"C:\St00dia\Antwerp_port_simulation\results\replications\0051_eval0001-loaded-baseline" + "\n")
    assert EV._replication_folder(log) == "0051_eval0001-loaded-baseline"


def test_compare_pairs_the_seeds(tmp_path, monkeypatch):
    monkeypatch.setattr(EV, "EVALS", tmp_path / "evaluations")
    monkeypatch.setattr(EV, "REPLICATIONS", tmp_path / "replications")
    s = EV.clean({"strategies": ["local_lookahead"]}, AVAILABLE)
    folder, plan = EV.create(s)
    for it, rows in zip(plan["items"], ([10.0, 12.0, 14.0], [9.0, 11.0, 13.5])):
        rep = tmp_path / "replications" / f"rep_{it['strategy']}"
        rep.mkdir(parents=True)
        pd.DataFrame({"seed": [2001, 2002, 2003], "anchored_mean": rows,
                      "inland_cargo.lock_queue_h_mean": [1.0, 1.0, 1.0]}).to_csv(rep / "replications.csv", index=False)
        it.update(state="done", replication=rep.name)
    EV._write(folder, plan)
    c = EV.compare(plan["id"])
    assert c["has_baseline"] and c["strategies"] == ["local_lookahead"]
    row = next(r for r in c["rows"] if r["metric"] == "anchored_mean")
    cell = row["strategies"]["local_lookahead"]
    assert row["baseline"] == pytest.approx(12.0) and cell["diff"] == pytest.approx(-5 / 6)
    assert cell["seeds"] == 3 and cell["significant"]          # differences -1, -1, -0.5: all below 0
    flat = next(r for r in c["rows"] if r["metric"] == "inland_cargo.lock_queue_h_mean")
    assert flat["strategies"]["local_lookahead"]["diff"] == 0 and not flat["strategies"]["local_lookahead"]["significant"]


def test_an_evaluation_left_running_by_a_restart_shows_as_interrupted(tmp_path, monkeypatch):
    monkeypatch.setattr(EV, "EVALS", tmp_path / "evaluations")
    folder, plan = EV.create(EV.clean({"strategies": ["chain_planning"]}, AVAILABLE))
    plan["state"], plan["items"][0]["state"] = "running", "running"
    EV._write(folder, plan)
    got = EV.list_evaluations()[0]
    assert got["state"] == "interrupted" and got["items"][0]["state"] == "interrupted"


def test_run_folders_are_named_by_their_label_and_a_used_label_is_refused(tmp_path):
    sys.path.insert(0, str(ROOT / "src" / "sim"))
    import pipeline as PL
    assert PL.run_name("loaded S1 / seed #1001") == "loaded-S1-seed-1001"
    assert PL.run_name("", "local_lookahead").startswith("local_lookahead-2")
    a = PL.new_folder(tmp_path, "my-run")
    assert a.name == "my-run"
    with pytest.raises(ValueError):
        PL.new_folder(tmp_path, "my-run")                    # never numbered: a label is an id
    b, c = PL.new_folder(tmp_path, "", "x"), PL.new_folder(tmp_path, "", "x")
    assert b != c and b.name.startswith("x-") and c.name.startswith("x-")   # automatic names never collide


def test_evaluations_are_named_by_their_label(tmp_path, monkeypatch):
    monkeypatch.setattr(EV, "EVALS", tmp_path / "evaluations")
    folder, plan = EV.create(EV.clean({"strategies": ["chain_planning"], "label": "loaded all"}, AVAILABLE))
    assert plan["id"] == folder.name == "loaded-all" and EV.folder_of("loaded-all") == folder
    with pytest.raises(ValueError):
        EV.create(EV.clean({"strategies": ["chain_planning"], "label": "loaded all"}, AVAILABLE))
    cmd = EV.command(plan["settings"], plan["items"][1], plan["id"])
    assert cmd[cmd.index("--label") + 1] == "loaded-all-chain_planning"
