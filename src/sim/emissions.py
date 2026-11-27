"""Fuel consumption and exhaust emissions of the ships (MODEL.md §17.1).

Bookkeeping only: it reads what the ships do each 5-minute step (state, distance sailed, draught, the water and the
current where they are) and draws no random numbers, so a run with it is the same run as without it (§1).

Every step each ship in the area gets a power demand from three engines, a specific fuel consumption, and from the
fuel and the energy its emissions:

    main engine (ME)   sea-going ships under way: the Admiralty formula of the Fourth IMO GHG Study (eq. 8)
                           P = P_ref (v_stw / v_ref)^3 (T / T_ref)^0.66 / (eta_w eta_f),   at most the MCR
                       with v_stw the speed through the water: the distance it made good in the step less the
                       current along its heading (the physical current, not the share of it ships' SOG shows, §4.4);
                       inland craft (and river cruise ships): the resistance of Bolt (2003) with the shallow-water
                       and canal terms, P_b = 2 u_rel R_tot, at most the craft's installed power
    auxiliary (AE)     sea-going: IMO Table 17 by type, size and phase (berth, anchored, manoeuvring, sea);
                       inland cargo craft: 13 % on the main engine's fuel (EMS protocol, annex A)
    boiler             sea-going: IMO Table 17

    fuel  = sum over engines of P x SFC x dt          SFC: IMO Table 19 (MDO, built 2001+), the ME's raised at low
                                                      load by IMO eq. 10
    CO2   = fuel x 3.206 (MDO, IMO Table 21); inland: EMS park factors (g/kWh) at the engine's load
    SOx   = fuel x 2 x 0.97753 x S (IMO eq. 15), S = 0.1 % (North Sea ECA) ; inland: EMS (EN590)
    NOx, PM = energy x EMEP/EEA 2023 Tier 3 factors (Table 3-15, MDO, by engine and phase), NOx at Tier II
              (Table 3-6) as the fleet average; inland: EMS park factors

Each step's fuel and emissions are also put down to one of four activities, the ones port management changes:
sailing (under way at speed), manoeuvring (slow under way, docks, mooring, boarding, pilot change), waiting (at anchor,
waiting for clearance away from a berth, at or in a lock, waiting for a pilot) and berth (at the berth or in a port).

Sources (ecology/): IMO = Fourth IMO GHG Study 2020; EMEP = EMEP/EEA guidebook 2023, 1.A.3.d; MAN = Basic principles
of ship propulsion; EMS = EMS-protocol Emissies door binnenvaart: verbrandingsmotoren, v5 (2018); Bolt = Schatting
energiegebruik binnenvaartschepen, v3 (2003).
"""

from __future__ import annotations

import math

import numpy as np

KNOT = 1852.0 / 3600.0
RHO = 1000.0                    # fresh to brackish water, kg/m3 (Bolt uses 1000)
G = 9.81

ACTIVITIES = ("sailing", "manoeuvring", "waiting", "berth")
CLASSES = ("container", "bulk_general", "tanker", "passenger", "inland_cargo", "inland_tanker")   # the fuel by class a step
POLLUTANTS = ("co2", "nox", "sox", "pm")

# ------------------------------------------------------------------ sea-going ships: IMO Fourth GHG Study 2020
# Table 35 (pp. 99-100): mean main engine power (kW) and design speed (kn) of the 2018 fleet by type and size bin,
# as (lower bound of the bin, kW, kn). The model knows no ship's engine: a ship gets its bin's mean.
ME_BINS = {
    "container_teu": [(0, 5077, 16.0), (1000, 12083, 19.0), (2000, 20630, 21.1), (3000, 34559, 23.1),
                      (5000, 52566, 24.6), (8000, 57901, 23.9), (12000, 61231, 23.8), (14500, 60202, 20.2),
                      (20000, 60210, 20.3)],
    "general_cargo_dwt": [(0, 1454, 11.1), (5000, 3150, 12.7), (10000, 5280, 14.0), (20000, 9189, 15.0)],
    "bulk_dwt": [(0, 1796, 11.8), (10000, 5941, 13.8), (35000, 8177, 14.3), (60000, 9748, 14.4),
                 (100000, 16741, 14.5), (200000, 20094, 14.6)],
    "chemical_dwt": [(0, 987, 12.2), (5000, 3109, 12.9), (10000, 5101, 13.8), (20000, 8107, 14.7), (40000, 8929, 14.6)],
    "oil_dwt": [(0, 966, 11.4), (5000, 2761, 12.1), (10000, 4417, 12.9), (20000, 8975, 14.6), (60000, 11837, 14.8),
                (80000, 13319, 14.8), (120000, 17446, 15.1), (200000, 27159, 15.5)],
    "gas_cbm": [(0, 2236, 14.2), (50000, 12832, 16.4), (100000, 30996, 19.0), (200000, 36735, 19.2)],
    "cruise_gt": [(0, 911, 12.7), (2000, 3232, 13.8), (10000, 19378, 19.0), (60000, 51518, 21.8),
                  (100000, 67456, 21.3), (150000, 73442, 22.0)],
}
# Table 17 (pp. 68-69): auxiliary boiler and auxiliary engine power (kW) by phase, as
# (lower bound, (boiler at berth, anchored, manoeuvring, sea), (AE at berth, anchored, manoeuvring, sea))
AUX_BINS = {
    "container_teu": [(0, (250, 250, 240, 0), (370, 450, 790, 410)), (1000, (340, 340, 310, 0), (820, 910, 1750, 900)),
                      (2000, (460, 450, 430, 0), (610, 910, 1900, 920)), (3000, (480, 480, 430, 0), (1100, 1350, 2500, 1400)),
                      (5000, (590, 580, 550, 0), (1100, 1400, 2800, 1450)), (8000, (620, 620, 540, 0), (1150, 1600, 2900, 1800)),
                      (12000, (630, 630, 630, 0), (1300, 1800, 3250, 2050)), (14500, (630, 630, 630, 0), (1400, 1950, 3600, 2300)),
                      (20000, (700, 700, 700, 0), (1400, 1950, 3600, 2300))],
    "general_cargo_dwt": [(0, (0, 0, 0, 0), (90, 50, 180, 60)), (5000, (110, 110, 100, 0), (240, 130, 490, 180)),
                          (10000, (150, 150, 130, 0), (720, 370, 1450, 520)), (20000, (150, 150, 130, 0), (720, 370, 1450, 520))],
    "bulk_dwt": [(0, (70, 70, 60, 0), (110, 180, 500, 190)), (10000, (70, 70, 60, 0), (110, 180, 500, 190)),
                 (35000, (130, 130, 120, 0), (150, 250, 680, 260)), (60000, (260, 260, 240, 0), (240, 400, 1100, 410)),
                 (100000, (260, 260, 240, 0), (240, 400, 1100, 410)), (200000, (260, 260, 240, 0), (240, 400, 1100, 410))],
    "chemical_dwt": [(0, (670, 160, 130, 0), (110, 170, 190, 200)), (5000, (670, 160, 130, 0), (330, 490, 560, 580)),
                     (10000, (1000, 240, 200, 0), (330, 490, 560, 580)), (20000, (1350, 320, 270, 0), (790, 550, 900, 660)),
                     (40000, (1350, 320, 270, 0), (790, 550, 900, 660))],
    "oil_dwt": [(0, (500, 100, 100, 0), (250, 250, 375, 250)), (5000, (750, 150, 150, 0), (375, 375, 560, 375)),
                (10000, (1250, 250, 250, 0), (690, 500, 580, 490)), (20000, (2700, 270, 270, 270), (720, 520, 600, 510)),
                (60000, (3250, 360, 360, 280), (620, 490, 770, 560)), (80000, (4000, 400, 400, 280), (800, 640, 910, 690)),
                (120000, (6500, 500, 500, 300), (2500, 770, 1300, 860)), (200000, (7000, 600, 600, 300), (2500, 770, 1300, 860))],
    "gas_cbm": [(0, (1000, 200, 200, 100), (240, 240, 360, 240)), (50000, (1000, 200, 200, 100), (1700, 1700, 2600, 1700)),
                (100000, (1500, 300, 300, 150), (2500, 2000, 2300, 2650)), (200000, (3000, 600, 600, 300), (6750, 7200, 7200, 6750))],
    "cruise_gt": [(0, (1100, 950, 980, 0), (450, 450, 580, 450)), (10000, (1100, 950, 980, 0), (3500, 3500, 5500, 3500)),
                  (60000, (1100, 950, 980, 0), (11500, 11500, 14900, 11500))],
    "ferry_pax_gt": [(0, (0, 0, 0, 0), (190, 190, 190, 190))],
}
PHASE_INDEX = {"berth": 0, "anchored": 1, "manoeuvring": 2, "sea": 3}
# p. 64: the weather (coastal: within 5 nm of the shore, as all of the area is) and hull-fouling modifiers
ETA_WEATHER, ETA_FOULING = 0.909, 0.917
# p. 65: for container ships of 14,500 TEU and more the IHS "speed" is a service speed at about 75 % MCR
SERVICE_SPEED_SHARE = {"container": (14500, 0.75)}
DRAUGHT_EXPONENT = 0.66
# Table 19 (pp. 70-71), g/kWh, MDO (the North Sea is an ECA at 0.10 % S: Table 18 switches HFO to MDO), built 2001+
SFC_BASE = {"SSD": 165.0, "MSD": 175.0, "HSD": 185.0, "AE": 185.0, "boiler": 320.0}
SSD_FROM_KW = 5000.0            # assumed: main engines of this power and more are two-stroke (MAN Table 1.01: liners,
                                # tankers and bulk carriers 2-stroke, feeders and general cargo 2- or 4-stroke)
# Table 21 (p. 74) and eq. 15
CO2_PER_FUEL = 3.206            # g CO2 / g MDO
SULPHUR_SHARE = 0.001           # 0.10 % m/m in the North Sea ECA
SOX_PER_FUEL = 2.0 * 0.97753 * SULPHUR_SHARE
# decision tree of p. 68: small engines get small auxiliaries
AE_OFF_BELOW_KW, AE_SHARE_BELOW_KW, AE_SHARE = 150.0, 500.0, 0.05

# ------------------------------------------------------------------ sea-going ships: EMEP/EEA 2023, Table 3-15 (MDO/MGO)
# g/kWh: (NOx at Tier 0, PM10) by engine and phase; "cruise" for sailing at speed, "manoeuvring" for the rest
EF_SEA = {
    ("ME", "SSD", "cruise"): (17.7, 0.180), ("ME", "SSD", "manoeuvring"): (24.3, 0.361),
    ("ME", "MSD", "cruise"): (10.8, 0.180), ("ME", "MSD", "manoeuvring"): (14.8, 0.361),
    ("ME", "HSD", "cruise"): (8.53, 0.188), ("ME", "HSD", "manoeuvring"): (11.7, 0.367),
    ("AE", "MSD", "cruise"): (12.6, 0.284), ("AE", "MSD", "manoeuvring"): (10.8, 0.215),
}
# Table 3-6: NOx reduction from Tier 0. Assumed: Tier II for the whole fleet (engines built 2011-2020 are most of it;
# Tier III holds only for ships built from 2021 in the North Sea NECA, Tier I and 0 for the older ones)
NOX_TIER_REDUCTION = {"SSD": 0.361, "MSD": 0.232, "HSD": 0.302}
# Table 3-20 (Entec 2002): a ship lying still but ready to sail (at a lock, waiting for a pilot) runs its main engine
# at 20 % MCR 5 % of the time: 1 % MCR on average
STANDBY_ME_SHARE = 0.20 * 0.05
# the main engine while a timer runs under way (boarding, pilot change, mooring with tugs): manoeuvring, 20 % MCR
MANOEUVRE_ME_SHARE = 0.20
# Calibrated on EU MRV 2024 (ecology/, MODEL.md §17.1, src/data/fit_mrv_calibration.py): for the sea-going ships of
# the AIS record, the fuel an hour the method gives at a ship's mean speed at sea over the fuel an hour at sea the
# ship reported. With the fleet means of IMO Table 35 alone the median was 0.88 (574 ships); this factor on the
# main engine's power makes it 1.00. On MRV 2025, held out (851 ships): 1.03 (fuel-weighted 1.00; containers 1.01,
# bulk / general cargo 1.03, tankers 1.04), where it was 0.91 without it. One factor for all types: per type, the
# 2024 values did not hold on 2025 (bulk carriers and tankers 7 % over). Set again when a new year is published
ME_POWER_FACTOR = 1.19

# ------------------------------------------------------------------ sea-going ships: size from dimensions
# Deadweight is the size measure of IMO's bins, and the model has only LOA, beam and draught. MAN Table 1.01 (p. 9):
# block coefficient and lightweight / deadweight per type (middle of the ranges)
#   displacement = 1.025 Cb Lpp B T, Lpp = 0.97 LOA (assumed), deadweight = displacement / (1 + lwt/dwt)
HULL = {"bulk_general": (0.80, 0.20), "tanker": (0.76, 0.30), "gas": (0.70, 0.40)}
LPP_SHARE = 0.97
CBM_PER_DWT_GAS = 1.5           # assumed: cargo volume of a gas carrier per tonne of deadweight (LPG / ethylene)
GENERAL_CARGO_BELOW_DWT = 10000.0   # the class mixes the two: general cargo below, bulk carriers above (assumed)
OIL_FROM_DWT = 60000.0          # tankers: chemical / product tankers below, oil tankers above (assumed)

# ------------------------------------------------------------------ inland craft: EMS protocol (2018) and Bolt (2003)
# EMS Tables 17 and 18 (pp. 7-6, 7-7): fleet emission factors 2017 in g/kWh at 100 % and 25 % engine load by tonnage
# category (L1 small: M0-M4; L2: M5-M7; L3 large: M8 and up, Table 5), as (NOx, PM10, CO2, SO2)
EF_INLAND = {"L1": {1.0: (8.8, 0.28, 677.1, 0.004), 0.25: (9.7, 0.32, 750.1, 0.005)},
             "L2": {1.0: (8.7, 0.27, 674.8, 0.004), 0.25: (9.5, 0.31, 747.5, 0.005)},
             "L3": {1.0: (8.7, 0.26, 673.4, 0.004), 0.25: (9.6, 0.30, 746.0, 0.005)}}
CO2_PER_FUEL_INLAND = 3.173     # EMS Table 15: g CO2 / g diesel
INLAND_AUX_SHARE = 0.13         # EMS annex A: the auxiliaries burn 13 % on top of the main engines
L1_BELOW_M, L2_BELOW_M = 75.0, 100.0   # LOA bounds of the tonnage categories (M4 71 m, M5-M7 80-87 m, M8 107 m: Bolt Table 1)
# Bolt (2003): resistance coefficients (eqs. 7, 10, 12) and the brake power (eq. 15: propulsive efficiency 0.55 and
# 5 % shaft losses, P_b = 2 u_rel R_tot)
BOLT_CP, BOLT_CZ = 0.15, 0.2
# Bolt Table 1 (p. 7), the survey of 2003: (L, B, T, installed power kW) of the mean craft of classes M1-M8, to which
# the installed power of a craft is fitted (P = a (L B T)^b): the cap on what Bolt's resistance asks of it
BOLT_SURVEY = [(38.85, 5.31, 2.42, 185), (53.65, 6.63, 2.42, 278), (59.84, 7.06, 2.54, 311), (70.95, 8.33, 2.61, 451),
               (80.35, 8.20, 2.69, 646), (86.99, 9.39, 2.86, 881), (84.84, 9.50, 3.20, 746), (106.95, 11.25, 3.35, 1267)]
_b, _a = np.polyfit(np.log([l * b * t for l, b, t, _ in BOLT_SURVEY]), np.log([p for *_, p in BOLT_SURVEY]), 1)
INSTALLED_A, INSTALLED_B = float(math.exp(_a)), float(_b)
MIN_DEPTH_RATIO = 1.15          # h / T at least this in the shallow-water term (the model's UKC keeps ships above it)
MIN_SCHIJF_DENOMINATOR = 0.2    # canal blockage term kept finite (a craft cannot sail faster than the critical speed)
# river cruise and day-trip ships (inland passenger ships): their hotel load, taken from IMO Table 17 for the
# nearest sea-going kind (assumed): cruise ships under 2,000 GT for the large ones, passenger ferries for the rest
RIVER_CRUISE_FROM_M = 80.0


def _bin(table, size):
    row = table[0]
    for r in table:
        if size >= r[0]:
            row = r
    return row


def dwt_from_dimensions(loa, beam, draught, kind="bulk_general"):
    cb, lwt = HULL[kind]
    return 1.025 * cb * LPP_SHARE * loa * beam * draught / (1.0 + lwt)


def installed_inland_kw(loa, beam, draught):
    return INSTALLED_A * (loa * beam * draught) ** INSTALLED_B


class Profile:
    """What a ship's engines are, from its class and size (set once, when it enters)."""

    __slots__ = ("kind", "sea", "mcr", "p_ref", "v_ref", "t_ref", "engine", "aux_table", "aux_size", "category",
                 "installed", "hotel")

    def __init__(self, ship):
        self.sea = ship.sea_going
        self.installed = self.hotel = None
        draught = max(ship.arrival_draught or ship.draught, ship.draught)
        if not self.sea:
            self.kind = "inland_passenger" if ship.cls == "passenger" else "inland"
            self.installed = installed_inland_kw(ship.loa, ship.beam, draught)
            self.category = "L1" if ship.loa < L1_BELOW_M else "L2" if ship.loa < L2_BELOW_M else "L3"
            self.mcr = self.installed
            self.engine = "inland"
            if self.kind == "inland_passenger":
                table = "cruise_gt" if ship.loa >= RIVER_CRUISE_FROM_M else "ferry_pax_gt"
                self.hotel = _bin(AUX_BINS[table], 0)[2]
            return
        # sea-going: the type's bins and the ship's size in their unit
        if ship.cls == "container":
            teu = ship.teu if ship.teu else math.exp((math.log(ship.loa) - 3.204) / 0.277)   # MODEL.md §2.1 inverted
            self.kind, size, aux = "container_teu", teu, "container_teu"
            self.t_ref = math.exp(0.788 + 0.190 * math.log(teu))     # the draught of its size (MODEL.md §2.1)
        elif ship.cls == "bulk_general":
            dwt = dwt_from_dimensions(ship.loa, ship.beam, draught, "bulk_general")
            self.kind = aux = "general_cargo_dwt" if dwt < GENERAL_CARGO_BELOW_DWT else "bulk_dwt"
            size, self.t_ref = dwt, None
        elif ship.cls == "tanker":
            gas = ship.dg == "A"
            dwt = dwt_from_dimensions(ship.loa, ship.beam, draught, "gas" if gas else "tanker")
            if gas:
                self.kind, size = "gas_cbm", dwt * CBM_PER_DWT_GAS
            else:
                self.kind, size = ("oil_dwt" if dwt >= OIL_FROM_DWT else "chemical_dwt"), dwt
            aux, self.t_ref = self.kind, None
        else:                                                         # sea-going passenger ship: a cruise ship
            gt = 0.25 * ship.loa * ship.beam * draught * 3.0          # assumed: GT from the hull's volume
            self.kind, size, aux, self.t_ref = "cruise_gt", gt, "cruise_gt", None
        _, self.mcr, self.v_ref = _bin(ME_BINS[self.kind], size)
        lo, share = SERVICE_SPEED_SHARE.get(ship.cls, (math.inf, 1.0))
        self.p_ref = self.mcr * (share if size >= lo else 1.0)
        self.engine = "MSD" if ship.cls == "passenger" or self.mcr < SSD_FROM_KW else "SSD"
        self.aux_table, self.aux_size = aux, size
        self.category = None

    def aux_kw(self, phase):
        """(AE kW, boiler kW) in an IMO phase (berth, anchored, manoeuvring, sea)."""
        if not self.sea:
            if self.hotel is not None:
                return float(self.hotel[PHASE_INDEX[phase]]), 0.0
            return 0.0, 0.0
        _, boiler, ae = _bin(AUX_BINS[self.aux_table], self.aux_size)
        k = PHASE_INDEX[phase]
        if self.mcr < AE_OFF_BELOW_KW:
            return 0.0, 0.0
        if self.mcr < AE_SHARE_BELOW_KW:
            return AE_SHARE * self.mcr, float(boiler[k])
        return float(ae[k]), float(boiler[k])


# ------------------------------------------------------------------ power
def admiralty_kw(prof, stw_kn, draught):
    """Main engine power of a sea-going ship at a speed through the water (IMO eq. 8), at most its MCR."""
    if stw_kn <= 0.0:
        return 0.0
    t_ref = prof.t_ref or draught
    p = prof.p_ref * (stw_kn / prof.v_ref) ** 3 * (min(draught / t_ref, 1.2) if t_ref > 0 else 1.0) ** DRAUGHT_EXPONENT
    return min(ME_POWER_FACTOR * p / (ETA_WEATHER * ETA_FOULING), prof.mcr)


def sfc_main(prof, load):
    """g/kWh of a sea-going main engine at a load (share of MCR): IMO eq. 10."""
    return SFC_BASE[prof.engine] * (0.455 * load * load - 0.710 * load + 1.280)


def bolt_kw(loa, beam, draught, v, depth=None, current=0.0, canal_section=None):
    """Brake power (kW) of an inland craft sailing at v m/s through the water (Bolt 2003, eqs. 6-15).

    depth (m) under the craft's water line, None for deep water; current the return flow is added to (m/s);
    canal_section the wet cross-section of a canal (m2), None on wide water."""
    if v <= 0.0:
        return 0.0
    am = beam * draught
    u_ret = z = 0.0
    v_eff = v
    if depth is not None:
        h = max(depth, MIN_DEPTH_RATIO * draught)
        if canal_section:                                    # Schijf: return flow and the drop of the water (eqs. 8, 9)
            fnh2 = v * v / (G * h)
            ratio = min(am / canal_section, 0.6)
            den = max(1.0 - ratio - fnh2, MIN_SCHIJF_DENOMINATOR)
            u_ret = ratio / den * v
            z = ratio / den * fnh2 * h
        v_eff = v / (1.0 - math.exp(4.0 * (1.0 - h / draught)))   # wide shallow water (eq. 11)
    u_rel = max(v + u_ret, v_eff)                                # eq. 11 (the second)
    rf = 53.0 * (math.log10(u_rel * loa) + 4.0) ** -2 * (loa * beam + 2.0 * loa * draught) * u_rel ** 2
    rp = BOLT_CP * 0.5 * RHO * v * v * beam * draught
    rz = BOLT_CZ * RHO * G * z * beam * draught
    return 2.0 * u_rel * (rf + rp + rz) / 1000.0              # eq. 15: kN x m/s -> kW, with 1 / (0.55 x 0.95)


# ------------------------------------------------------------------ the accounting
class Accounting:
    """Fuel and emissions of every ship, step by step (engine.Simulation.emissions)."""

    def __init__(self, sim):
        self.sim = sim
        fg = sim.fg
        self.zone = sim.mover.zone_label
        self.depth = fg.depth_m
        self.clearance = getattr(fg, "clearance", None)
        self.step = {}                                       # the last step's totals (for the time series)
        self.by_class = {}                                   # class -> totals (kg) of the steps after the warm-up

    # where a ship is and which way it heads
    def _heading_current(self, node, nxt, k):
        """The current along the ship's way (m/s, + = with it) at node, heading to nxt."""
        sim, fg = self.sim, self.sim.fg
        sl = sim.slice_of[node]
        if sl < 0 or nxt is None:
            return 0.0
        dx, dy = fg.x[nxt] - fg.x[node], fg.y[nxt] - fg.y[node]
        n = math.hypot(dx, dy)
        if n == 0 or np.isnan(fg.flow_dir[node, 0]):
            return 0.0
        u = sim.current_u[min(k, sim.current_u.shape[0] - 1), sl]
        return float(u * (dx * fg.flow_dir[node, 0] + dy * fg.flow_dir[node, 1]) / n)

    def _where(self, ship):
        """The route edge (node, next node) under the ship's bow, or (node it lies at, None)."""
        if ship.route and ship.s is not None:
            i = int(np.searchsorted(ship.s, ship.head, side="right")) - 1
            i = min(max(i, 0), len(ship.route) - 1)
            if i + 1 < len(ship.route):
                return ship.route[i], ship.route[i + 1]
            if i > 0:                                      # at the end: the last edge
                return ship.route[i - 1], ship.route[i]
            return ship.route[i], None
        return (ship.cells[-1] if ship.cells else ship.at), None

    def activity(self, ship, State):
        """(activity for the books, IMO phase for the auxiliaries, how the main engine runs) of a ship now."""
        st = ship.state
        if st in (State.AT_BERTH, State.DWELL_PORT):
            return "berth", "berth", "off"
        if st == State.WAIT_CLEARANCE:
            if ship.departing and ship.berth:
                return "berth", "berth", "off"
            return "waiting", "anchored", "off"
        if st == State.ANCHORED:
            return "waiting", "anchored", "off"
        if st in (State.LOCK_QUEUE, State.IN_LOCK, State.WAIT_PILOT):
            return "waiting", "manoeuvring", "standby"
        if st in (State.MOORING, State.UNMOORING) and getattr(ship, "timer", None) is None:
            # waiting for its quay to clear, the tide, tugs or boatmen before (un)mooring starts: 20 % MCR is for
            # while the timer runs; until then it waits at standby, as at a lock (counted as manoeuvring, a ship
            # waiting off a quay still taken ran at 20 % MCR for hours)
            return "waiting", "manoeuvring", "standby"
        if st in (State.BOARDING, State.PILOT_CHANGE, State.MOORING, State.UNMOORING):
            return "manoeuvring", "manoeuvring", "manoeuvre"
        if st in (State.SAILING, State.TO_STATION, State.TO_ANCHORAGE):
            return "sailing", "sea", "under_way"
        return None, None, "off"

    def account(self, ships, k, dt_min, State):
        """Add one step of fuel and emissions to every ship in the area; returns the step's totals."""
        dt_h = dt_min / 60.0
        tot = {"fuel_kg": 0.0, **{f"{p}_kg": 0.0 for p in POLLUTANTS}, **{f"fuel_kg_{a}": 0.0 for a in ACTIVITIES},
               **{f"fuel_kg_cls_{c}": 0.0 for c in CLASSES}}
        level = self.sim.level_now
        counted = k * dt_min >= self.sim.warmup_min
        for ship in ships:
            act, phase, me_mode = self.activity(ship, State)
            if act is None:
                continue
            prof = getattr(ship, "em_profile", None)
            if prof is None:
                prof = ship.em_profile = Profile(ship)
                ship.em = {"fuel_kg": 0.0, **{f"{p}_kg": 0.0 for p in POLLUTANTS}, **{f"fuel_kg_{a}": 0.0 for a in ACTIVITIES}}
            me_kw, stw_kn, ef_phase = 0.0, 0.0, "manoeuvring"
            if me_mode == "under_way":
                moved = ship.moved_m if getattr(ship, "moved_k", -1) == k else 0.0
                sog = moved / (dt_min * 60.0)
                node, nxt = self._where(ship)
                cur = self._heading_current(node, nxt, k) if node is not None else 0.0
                stw = abs(sog - cur)                       # holding still against a current takes power too
                stw_kn = stw / KNOT
                zone = self.zone[node] if node is not None else None
                if prof.sea:
                    me_kw = admiralty_kw(prof, stw_kn, ship.draught)
                    # IMO Table 16: under 5 kn, or in the docks, a ship manoeuvres; faster it sails
                    if stw_kn <= 5.0 or sog / KNOT <= 5.0 or zone == "dock":
                        act, phase = "manoeuvring", "manoeuvring"
                    else:
                        ef_phase = "cruise"
                else:
                    depth = None
                    canal = None
                    if node is not None and not np.isnan(self.depth[node]):
                        depth = float(self.depth[node] + level[node])
                        if zone == "canal" and self.clearance is not None:
                            width = 2.0 * max(float(self.clearance[node]), 2.0 * ship.beam)
                            canal = width * depth
                    me_kw = min(bolt_kw(ship.loa, ship.beam, ship.draught, stw, depth, 0.0, canal), prof.installed)
                    if stw_kn <= 5.0 or zone == "dock":
                        act, phase = "manoeuvring", "manoeuvring"
            elif me_mode == "manoeuvre":
                me_kw = MANOEUVRE_ME_SHARE * prof.mcr
            elif me_mode == "standby":
                me_kw = STANDBY_ME_SHARE * prof.mcr
            ae_kw, boiler_kw = prof.aux_kw(phase)
            load = me_kw / prof.mcr if prof.mcr else 0.0
            # fuel (kg) and emissions (kg) this step
            if prof.sea:
                fuel = (me_kw * sfc_main(prof, load) + ae_kw * SFC_BASE["AE"] + boiler_kw * SFC_BASE["boiler"]) * dt_h / 1000.0
                nox_me, pm_me = EF_SEA[("ME", prof.engine, ef_phase)]
                nox_ae, pm_ae = EF_SEA[("AE", "MSD", ef_phase)]
                nox = (me_kw * nox_me * (1 - NOX_TIER_REDUCTION[prof.engine]) + ae_kw * nox_ae * (1 - NOX_TIER_REDUCTION["MSD"])) * dt_h / 1000.0
                pm = (me_kw * pm_me + ae_kw * pm_ae) * dt_h / 1000.0
                co2, sox = fuel * CO2_PER_FUEL, fuel * SOX_PER_FUEL
            else:
                f = EF_INLAND[prof.category]
                w = min(max((load - 0.25) / 0.75, 0.0), 1.0)          # between the 25 % and 100 % load factors
                nox_g, pm_g, co2_g, so2_g = ((1 - w) * a + w * b for a, b in zip(f[0.25], f[1.0]))
                me_kwh = me_kw * dt_h * (1.0 + (INLAND_AUX_SHARE if prof.hotel is None else 0.0))
                hotel_kwh = ae_kw * dt_h
                co2 = (me_kwh * co2_g + hotel_kwh * SFC_BASE["AE"] * CO2_PER_FUEL) / 1000.0
                fuel = (me_kwh * co2_g / CO2_PER_FUEL_INLAND + hotel_kwh * SFC_BASE["AE"]) / 1000.0
                nox = (me_kwh * nox_g + hotel_kwh * EF_SEA[("AE", "MSD", "manoeuvring")][0] * (1 - NOX_TIER_REDUCTION["MSD"])) / 1000.0
                pm = (me_kwh * pm_g + hotel_kwh * EF_SEA[("AE", "MSD", "manoeuvring")][1]) / 1000.0
                sox = (me_kwh * so2_g + hotel_kwh * SFC_BASE["AE"] * SOX_PER_FUEL) / 1000.0
            e = ship.em
            for key, v in (("fuel_kg", fuel), ("co2_kg", co2), ("nox_kg", nox), ("sox_kg", sox), ("pm_kg", pm)):
                e[key] += v
                tot[key] += v
            e[f"fuel_kg_{act}"] += fuel
            tot[f"fuel_kg_{act}"] += fuel
            tot[f"fuel_kg_cls_{ship.cls}"] = tot.get(f"fuel_kg_cls_{ship.cls}", 0.0) + fuel
            if counted:
                c = self.by_class.setdefault(ship.cls, {"fuel_kg": 0.0, **{f"{p}_kg": 0.0 for p in POLLUTANTS},
                                                        **{f"fuel_kg_{a}": 0.0 for a in ACTIVITIES}})
                for key, v in (("fuel_kg", fuel), ("co2_kg", co2), ("nox_kg", nox), ("sox_kg", sox), ("pm_kg", pm),
                               (f"fuel_kg_{act}", fuel)):
                    c[key] += v
        self.step = tot
        return tot
