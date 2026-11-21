"""Fuel and emissions (src/sim/emissions.py) against the sources' own numbers and hand calculations.

    py -m pytest tests/test_emissions.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for d in ("sim", "agents", "environment", "data"):
    sys.path.insert(0, str(ROOT / "src" / d))

import emissions as E  # noqa: E402
from ship import Ship  # noqa: E402


def ship(cls, loa, beam, draught, **kw):
    return Ship(id="x", cls=cls, loa=loa, beam=beam, draught=draught, level=1 if cls == "container" else 2,
                source="s", destination="d", spawn_t=0.0, **kw)


# ------------------------------------------------------------------ inland craft: Bolt (2003), Table 1
@pytest.mark.parametrize("L,B,T,v,pb", [(38.85, 5.31, 2.42, 3.17, 98), (53.65, 6.63, 2.42, 3.79, 223),
                                         (70.95, 8.33, 2.61, 4.08, 392), (86.99, 9.39, 2.86, 4.34, 598)])
def test_bolt_reproduces_his_table(L, B, T, v, pb):
    """Classes M1-M6 sail loaded at h/T = 2.5 on wide water in Bolt's Table 1; his brake power within 3 %."""
    assert E.bolt_kw(L, B, T, v, depth=2.5 * T) == pytest.approx(pb, rel=0.03)


def test_bolt_shallow_water_and_canal_ask_more():
    deep = E.bolt_kw(110, 11.4, 3.0, 4.5)
    shallow = E.bolt_kw(110, 11.4, 3.0, 4.5, depth=4.5)
    canal = E.bolt_kw(110, 11.4, 3.0, 4.5, depth=4.5, canal_section=60 * 4.5)
    assert deep < shallow < canal
    assert E.bolt_kw(110, 11.4, 3.0, 0.0, depth=4.5) == 0.0


def test_installed_power_fit_follows_the_survey():
    for L, B, T, p in E.BOLT_SURVEY:
        assert E.installed_inland_kw(L, B, T) == pytest.approx(p, rel=0.25)


# ------------------------------------------------------------------ sea-going ships: IMO
def test_container_profile_from_table_35():
    p = E.Profile(ship("container", 366, 51, 14.5, teu=14000))
    assert (p.kind, p.mcr, p.v_ref, p.engine) == ("container_teu", 61231, 23.8, "SSD")
    big = E.Profile(ship("container", 400, 61, 15.0, teu=23000))
    assert big.p_ref == pytest.approx(0.75 * big.mcr)          # IMO p. 65: service speed at 75 % MCR


def test_admiralty_formula():
    p = E.Profile(ship("container", 300, 48, 13.0, teu=8500))
    t = p.t_ref
    half = E.admiralty_kw(p, p.v_ref / 2, t)
    assert half == pytest.approx(E.ME_POWER_FACTOR * p.p_ref / 8 / (E.ETA_WEATHER * E.ETA_FOULING))
    assert E.admiralty_kw(p, 2 * p.v_ref, t) == p.mcr          # never more than the MCR
    assert E.admiralty_kw(p, 0.0, t) == 0.0
    assert E.admiralty_kw(p, 10, 0.8 * t) < E.admiralty_kw(p, 10, t)


def test_sfc_curve_lowest_near_80_percent():
    p = E.Profile(ship("bulk_general", 190, 32, 11.0))
    loads = [i / 100 for i in range(5, 101)]
    best = min(loads, key=lambda x: E.sfc_main(p, x))
    assert 0.75 <= best <= 0.80
    assert E.sfc_main(p, 0.1) > E.sfc_main(p, 0.8)


def test_auxiliaries_by_phase_and_small_engines():
    p = E.Profile(ship("container", 366, 51, 14.5, teu=14000))
    assert p.aux_kw("berth") == (1300.0, 630.0)                  # IMO Table 17, 12,000-14,499 TEU
    assert p.aux_kw("sea") == (2050.0, 0.0)
    inland = E.Profile(ship("inland_cargo", 86, 9.5, 2.5))
    assert inland.aux_kw("berth") == (0.0, 0.0)                  # inland: 13 % on the main engine instead
    cruise = E.Profile(ship("passenger", 135, 11.4, 1.6))
    assert not cruise.sea and cruise.aux_kw("berth")[0] == 450.0


def test_dwt_from_dimensions():
    assert 35000 < E.dwt_from_dimensions(190, 32, 11.0) < 55000    # a handymax bulk carrier
