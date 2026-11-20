"""The VTS strategy API (docs/VTS_API.md): the parts that need no model, in a second.

Strategies are found and built by name or spec; restrictions pick the ships they apply to; options from the command
line are read as JSON. What a strategy does in a run is checked by running it (and the baseline against the model
before the API: docs/VTS_API.md §10).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for d in ("sim", "agents", "environment", "data"):
    sys.path.insert(0, str(ROOT / "src" / d))
sys.path.append(str(ROOT / "src"))

import strategies  # noqa: E402
from ship import Ship  # noqa: E402
from vts_api import LEVERS, Restriction, Result, Strategy, lever_hooks  # noqa: E402


def test_the_strategies_of_the_repository_are_found():
    found = strategies.available()
    assert {"baseline", "container_first", "template"} <= set(found)
    for name, cls in found.items():
        assert issubclass(cls, Strategy) and cls.name == name
        assert set(cls.levers) <= set(LEVERS), f"{name} declares a lever that does not exist"


def test_load_by_name_spec_and_instance():
    s = strategies.load("container_first", {"classes": ["tanker"]})
    assert s.name == "container_first" and s.options == {"classes": ["tanker"]}
    assert strategies.load(s) is s
    assert type(strategies.load("strategies.baseline:Baseline")).name == "baseline"
    assert type(strategies.load(str(ROOT / "src" / "strategies" / "template.py") + ":Template")).name == "template"
    with pytest.raises(ValueError):
        strategies.load("no_such_strategy")
    with pytest.raises(ValueError):
        strategies.load("strategies.baseline:Ship")


def test_every_hook_has_a_lever():
    hooks = lever_hooks()
    assert set(hooks.values()) <= set(LEVERS)
    for name in hooks:
        assert callable(getattr(Strategy, name))


def test_result_is_true_only_when_ok():
    assert Result(True)
    assert not Result(False, "tide")


def ship(cls="bulk_general", loa=200.0, beam=32.0, draught=11.0):
    return Ship(id=f"T-{cls}-{loa}", cls=cls, loa=loa, beam=beam, draught=draught, level=2, source="sea_west",
                destination="exit_sea_west", spawn_t=0.0)


def test_restriction_applies_by_size_and_kind():
    big = Restriction(1, "no_meet", frozenset({1, 2}), 0.0, 60.0, who={"min_loa": 250.0})
    assert not big.applies(ship(loa=200.0)) and big.applies(ship(loa=300.0))
    barges = Restriction(2, "closed", frozenset({1}), 0.0, 60.0, who={"sea_going": False})
    assert barges.applies(ship("inland_cargo", 110.0, 11.4, 3.0)) and not barges.applies(ship())
    deep = Restriction(3, "one_way", frozenset({1}), 0.0, 60.0, direction=1, who={"min_draught": 12.0, "classes": ["tanker"]})
    assert deep.applies(ship("tanker", draught=13.0)) and not deep.applies(ship("tanker", draught=10.0))
    assert not deep.applies(ship("bulk_general", draught=13.0))
    every = Restriction(4, "closed", frozenset({1}), 30.0, 90.0)
    assert every.applies(ship()) and not every.active(0.0) and every.active(30.0) and not every.active(90.0)


def test_options_are_read_as_json_where_they_can_be():
    import pipeline
    assert pipeline.parse_options(["horizon_min=360", "classes=[\"container\"]", "mode=greedy", "on=true"]) == {
        "horizon_min": 360, "classes": ["container"], "mode": "greedy", "on": True}
    with pytest.raises(ValueError):
        pipeline.parse_options(["no_value"])
