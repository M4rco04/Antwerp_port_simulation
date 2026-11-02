"""Weather gates (regs §9) and the other weather effects on ships.

start_gate(ship, weather, now, route_info) -> None if the ship may start, else the reason. The VTS
asks it before clearing a ship; route_info says whether the voyage passes a lock, ends at a tidal
terminal, crosses into the river, and when the ship will arrive (minutes from now).

    visibility < 1000 m              marginal ships (LOA >= 300 m, B >= 45 m, T >= 12.5 m) do not start   JA22, GB24
    IMO2 gas tanker                  needs 1000 m at sea, 2000 m upstream of De Nolle - Nieuwe Sluis     NtM 1/60
    ULCV (container >= 350 m)        no permit at > 5 Bft for a voyage through a lock                    JA22
                                     tidal terminal: > 6 Bft arriving / > 7 Bft leaving, and the wind must
                                     stay at or below the limit for 3 h after its ETA                    JA22
    Everingen / Put van Terneuzen    T >= 12.5 m: no departure from those anchorages at >= 7 Bft          GB24
    cruise ships at the locks        max 7 Bft (LOA 170-200 m) / 6 Bft (200-265 m)                         NtM 1/39
    extreme weather                  sea-going ships do not start at >= STORM_BAN_BFT (GNA ban; assumed)  NtM 1/12
    pilot boarding at sea            at >= STORM_PILOT_BFT only ships the shore-based pilotage may take
                                     (LOA <= 175 m, T <= 8 m, not IMO2 / special transports)               NtM 1/21-22

Other effects (assumed values, regs give none): speed in restricted visibility (VIS_SPEED_CAP_KN,
COLREG 19), STS cranes stop in gusts over CRANE_STOP_GUST_MS, one extra tug for sea-going ships of
EXTRA_TUG_LOA_M or more at EXTRA_TUG_BFT or more.
"""

from __future__ import annotations

import pandas as pd

STORM_BAN_BFT = 9                       # assumed threshold of the GNA's extreme-weather ban
STORM_PILOT_BFT = 8                     # storm pilotage: no boarding at sea from this force on (assumed)
SHORE_PILOTAGE_MAX = (175.0, 8.0)       # LOA, T that shore-based pilotage can take (Scheur / Wielingen)
VIS_LIMIT_M = 1000.0
IMO2_RIVER_VIS_M = 2000.0
ULCV_LOCK_MAX_BFT = 5
ULCV_TERMINAL_MAX_BFT = {"arrival": 6, "departure": 7}
ULCV_TREND_H = 3.0
EVERINGEN = ("Everingen A", "Everingen B", "Everingen C", "Everingen D", "Everingen E",
             "Put van Terneuzen A", "Put van Terneuzen B")
EVERINGEN_MAX_BFT = 6                   # >= 7 Bft: the GNA decides; taken as no departure
CRUISE_LOCK_MAX_BFT = ((200.0, 7), (265.0, 6))
VIS_SPEED_CAP_KN = ((500.0, 5.0), (1000.0, 8.0))     # visibility below -> speed at most (assumed)
CRANE_STOP_GUST_MS = 20.0               # assumed
EXTRA_TUG_BFT = 6                       # assumed
EXTRA_TUG_LOA_M = 200.0


def start_gate(ship, weather, now, info):
    """Reason the ship may not start now (a pandas Timestamp), or None. info: dict with via_lock, tidal_terminal,
    river (the voyage enters the river), eta_min, boarding_at_sea."""
    w = weather.at(now)
    bft, vis = int(w.bft), float(w.visibility_m)
    if ship.sea_going and bft >= STORM_BAN_BFT:
        return f"storm ban ({bft} Bft)"
    if ship.marginal_visibility and vis < VIS_LIMIT_M:
        return f"visibility {vis:.0f} m (marginal ship)"
    if ship.imo2_gas and vis < (IMO2_RIVER_VIS_M if info.get("river") else VIS_LIMIT_M):
        return f"visibility {vis:.0f} m (IMO2 gas tanker)"
    if info.get("boarding_at_sea") and bft >= STORM_PILOT_BFT and not (
            ship.loa <= SHORE_PILOTAGE_MAX[0] and ship.draught <= SHORE_PILOTAGE_MAX[1] and not ship.imo2_gas):
        return f"no pilot boarding at sea ({bft} Bft)"
    if ship.ulcv:
        if info.get("via_lock") and bft > ULCV_LOCK_MAX_BFT:
            return f"ULCV at the locks ({bft} Bft)"
        if info.get("tidal_terminal"):
            limit = ULCV_TERMINAL_MAX_BFT["departure" if ship.departing else "arrival"]
            t_end = now + pd.Timedelta(minutes=info.get("eta_min", 0.0) + ULCV_TREND_H * 60)
            if bft > limit or weather.max_bft(now, t_end) > limit:
                return f"ULCV at a tidal terminal ({bft} Bft now, limit {limit} through ETA + 3 h)"
    if ship.anchorage in EVERINGEN and ship.draught >= 12.5 and bft > EVERINGEN_MAX_BFT:
        return f"leaving {ship.anchorage} ({bft} Bft)"
    if ship.cls == "passenger" and info.get("via_lock") and ship.loa >= 170:
        for top, limit in CRUISE_LOCK_MAX_BFT:
            if ship.loa <= top and bft > limit:
                return f"cruise ship at the locks ({bft} Bft)"
    return None


def speed_cap_kn(weather, now):
    vis = float(weather.at(now).visibility_m)
    for below, cap in VIS_SPEED_CAP_KN:
        if vis < below:
            return cap
    return None


def cranes_stopped(weather, now):
    return float(weather.at(now).gust_ms) > CRANE_STOP_GUST_MS


def extra_tugs(ship, weather, now):
    return 1 if ship.sea_going and ship.loa >= EXTRA_TUG_LOA_M and int(weather.at(now).bft) >= EXTRA_TUG_BFT else 0
