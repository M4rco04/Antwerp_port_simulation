"""Validation: the model and the AIS record measured the same way.

    py src/sim/validate.py observe                      # the AIS record -> results/validation/observed.json
    py src/sim/validate.py compare results/replications/<id>_<label>

The AIS snapshots and the model's positions are both a list of fixes every 5 minutes (who, when, where, how
fast), so the same code counts both: ships passing a section of the river, the time between two sections, ships
under way in a zone, ships passing a lock and how long that takes. What a list of fixes cannot give (a berthed
ship is heard in six snapshots of ten) is taken from the visits and stops of the AIS pipeline on one side and
from the ships' states on the other: ships in the area, at a berth, at anchor.

Every number is labelled by what it can show:

    I  input      the model draws it from this very number (arrival rates, stays): a check of the generator
    C  calibrated a parameter was set so that it fits (now or while the model was built): no evidence
    E  emergent   nothing was set to it: it comes out of the routes, the speeds, the rules and the queues

The record is the one the model was fitted on (there is no other yet, docs/PINNED.md): the emergent numbers are
the validation, the rest shows that the model reproduces what went in.

A replication writes its numbers itself (replicate.py calls simulated()); `compare` sets their mean and
confidence interval against the record's, day by day for its uncertainty (a day is one observation).
"""

from __future__ import annotations

import argparse
import json
import math
import pickle
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "validation"
for _p in ("src/data", "src/environment", "src/agents", "src/sim"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

SEA = ("container", "bulk_general", "tanker")
INLAND = ("inland_cargo", "inland_tanker")
PILOTED = SEA + ("passenger",)
GROUP = {**{c: "sea_going" for c in SEA}, **{c: "inland" for c in INLAND}}
# sections of the river (km along its axis), away from lock mouths, anchorages and quays where craft cross a
# line without going anywhere (AIS_FITTING.md): Vlissingen roads 5, Everingen 15-19, Terneuzen 24, Hansweert 40,
# Marlemon 54, Kreekrak branch 58, Noordzee terminal and the Zandvliet locks 64-67, Deurganckdok 70,
# Boudewijn 74, Kallo 77, Royers 85
SECTIONS_KM = {"km08": 8.0, "km32": 32.0, "km48": 48.0, "km62": 62.0, "km68": 68.0, "km72": 72.3, "km80": 80.0,
               "km88": 88.0}
SECTION_NAMES = {"sea": "sea, 3.10°E (Wandelaar to Wielingen)", "km08": "km 8, off Vlissingen",
                 "km32": "km 32, Terneuzen to Hansweert", "km48": "km 48, Hansweert to Bath",
                 "km62": "km 62, Bath to the Zandvliet locks", "km68": "km 68, Zandvliet to Deurganckdok",
                 "km72": "km 72, Deurganckdok to Boudewijn", "km80": "km 80, Kallo to Antwerp",
                 "km88": "km 88, above Antwerp"}
BAND_M = 400.0                      # a ship has passed a section when it is this far beyond it
SEA_SECTION_LON, SEA_BAND_LON, SEA_SECTION_MAX_LAT = 3.10, 0.006, 51.50     # the western approach
MIN_SEA_LON = 2.85                  # east of every sea entry of the model: the sea both sides have
PILOT_MIN_LON = 2.715               # Wandelaar: further west no pilot is on board
UNDER_WAY_KN = 1.0
SNAP_MAX_M = 800.0                  # an AIS fix further from the model's water is not on it
TIGHT_GAP_MIN = 15.0                # a passage is timed only when the fixes either side are this close
TRANSITS = {"sea_to_km08": ("sea", "km08", "sea_going"), "km08_to_km62": ("km08", "km62", "sea_going"),
            "km32_to_km48": ("km32", "km48", "inland")}
TRANSIT_MAX_H = 12.0
# a ship being moored or unmoored, or taking or changing its pilot, lies at a node while a timer runs in the
# model; a real one is moving then (the AIS mooring times run from 1 km off the berth): under way on both sides
MANOEUVRING = ("mooring", "unmooring", "boarding", "pilot_change")
# a ship lying at a berth or in a port is heard by the AIS where it lies; in the model it gets a fix there too, lying
# still. Without one, a craft that called within 2 km of a lock and then passed it was timed from its last fix
# before the call: a sixth of the inland passages of Terneuzen took over 2.5 h, their 90th percentile 3.4 h
# where the AIS has 1.8 h
LYING = ("at_berth", "dwell_port")
# sea-going ships calling at Antwerp a day, from the port's own statistics: 13,655 in 2020, 10,608 from January
# to September 2021 (Port of Antwerp press releases): 37.3 and 38.9 a day. In the fixes: sea-going ships passing
# km 48 up-river (nothing but Antwerp lies beyond for them)
PORT_CALLS_A_DAY = (37.3, 38.9)
# lock complexes (twin locks lie side by side). With the locks taken out the water falls apart into basins: a
# ship has passed a lock when two fixes in a row lie in the two basins it joins (the nearest such lock, if more
# than one joins them). The passage is timed from the last fix LOCK_RING_M or more from the lock's middle before
# it to the first one after it, when both lie within LOCK_EDGE_M of that ring (so the clock starts and stops
# where the ship crosses it): the wait at the lock, the lockage and about 1 km of slow sailing on each side
LOCKS = {"Zandvliet-Berendrecht": ("Zandvliet", "Berendrecht"), "Boudewijn-Van Cauwelaert": ("Boudewijn", "Van Cauwelaert"),
         "Royers-Kattendijk": ("Royers", "Kattendijk"), "Kieldrecht": ("Kieldrecht",), "Kallo": ("Kallo",),
         "Terneuzen": ("Terneuzen",), "Hansweert": ("Hansweert",), "Kreekrak": ("Kreekrak",)}
LOCK_RING_M, LOCK_EDGE_M, LOCK_MAX_H = 1000.0, 800.0, 6.0
AWAY_H = 6.0                        # a ship under way, then silent this long, has been out of the area
# Rijkswaterstaat's commercial passages a day (NMCA 2017; IVS90 2018, Deltares 2021): generator.INLAND_TRIP_SCALE
RWS_PASSAGES = {"Kreekrak": 189.0, "Hansweert": 113.0, "Terneuzen": 126.0}
TERMINAL_ZONES = ("antwerp_deurganckdok", "antwerp_river_quays")
MIN_DAY_H = 22.0                    # a day of the record counts when this much of it was recorded
STEP_MIN = 5.0


# ------------------------------------------------------------------ what both sides share
def geometry(graph, fg):
    """Per node of the model's mesh: zone, river kilometre, position; and the lock complexes."""
    zl = np.array(fg.labels["speed_zone"] + [""], dtype=object)[fg.speed_zone]
    zone = np.where(zl == "canal", "dock", zl).astype(object)
    tl = np.array(fg.labels["type"] + [""], dtype=object)[fg.type]
    water = ~np.isin(tl, ("lock", "anchorage", "approach"))
    chain = np.where(zone == "river", fg.chainage_m, np.nan)
    # basins: the water with the lock nodes taken out (the build makes sure a lock's two sides then lie apart)
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    ok = water[fg.edge_u] & water[fg.edge_v]
    adj = coo_matrix((np.ones(ok.sum()), (fg.edge_u[ok], fg.edge_v[ok])), shape=(fg.n, fg.n))
    basin = connected_components(adj, directed=False)[1]
    basin = np.where(water, basin, -1)
    locks = {}
    by_name = {d["name"]: d["lock"] for _, d in graph.nodes(data=True) if d["type"] == "lock"}
    for name, members in LOCKS.items():
        pts = np.array([[graph.nodes[m]["x"], graph.nodes[m]["y"]] for k in members for s in ("a", "b")
                        for m in by_name[k].sides[s]["nodes"]])
        pair = {s: int(np.bincount(basin[[fg.index[m] for m in by_name[members[0]].sides[s]["nodes"]]]).argmax()) for s in ("a", "b")}
        locks[name] = (float(pts[:, 0].mean()), float(pts[:, 1].mean()), frozenset(pair.values()))
    return SimpleNamespace(zone=zone, chain=chain, lon=fg.longitude, lat=fg.latitude, x=fg.x, y=fg.y, water=water,
                           basin=basin, locks=locks, crs=graph.graph["crs"])


def passages(f, coord, at, band, name):
    """Fixes sorted by ship and time -> the passages of one section: the first fix `band` beyond it after one
    `band` before it. dir +1 = towards higher values (up-river, eastwards)."""
    c = f[coord].to_numpy()
    side = np.where(c > at + band, 1, np.where(c < at - band, -1, 0))
    keep = np.flatnonzero(side != 0)                         # NaN compares false: fixes off the coordinate drop out
    a, ids, t = side[keep], f.id.to_numpy()[keep], f.t.to_numpy()[keep]
    x = np.flatnonzero((a[1:] != a[:-1]) & (ids[1:] == ids[:-1]))
    rows = f.iloc[keep[x + 1]][["id", "cls", "grp", "t"]].copy()
    rows["dir"], rows["gap"], rows["section"] = a[x + 1], t[x + 1] - t[x], name
    return rows


def lock_passages(f, geo):
    """The lock passages in a list of fixes (see LOCKS): one row each, with the hours it took where it can be
    timed (tight)."""
    on = np.flatnonzero(f.basin.to_numpy() >= 0)
    x, y, ids, t, b = (f[c].to_numpy()[on] for c in ("x", "y", "id", "t", "basin"))
    names = list(geo.locks)
    dist = np.array([np.hypot(x - geo.locks[n][0], y - geo.locks[n][1]) for n in names])       # lock x fix
    rows = []
    for k in np.flatnonzero((b[1:] != b[:-1]) & (ids[1:] == ids[:-1])):
        joins = [i for i, n in enumerate(names) if geo.locks[n][2] == frozenset((int(b[k]), int(b[k + 1])))]
        if not joins:
            continue
        i = min(joins, key=lambda j: dist[j, k] + dist[j, k + 1])
        lo = k                                         # back to the last fix outside the ring, in the old basin
        while lo > 0 and ids[lo] == ids[k] and b[lo] == b[k] and dist[i, lo] < LOCK_RING_M and t[k] - t[lo] < LOCK_MAX_H * 60:
            lo -= 1
        hi = k + 1
        while hi < len(t) - 1 and ids[hi] == ids[k] and b[hi] == b[k + 1] and dist[i, hi] < LOCK_RING_M and t[hi] - t[k] < LOCK_MAX_H * 60:
            hi += 1
        ring = lambda j, basin: (ids[j] == ids[k] and b[j] == basin and LOCK_RING_M <= dist[i, j] <= LOCK_RING_M + LOCK_EDGE_M)
        tight = ring(lo, b[k]) and ring(hi, b[k + 1]) and t[hi] - t[lo] <= LOCK_MAX_H * 60
        rows.append((on[k + 1], names[i], (t[hi] - t[lo]) / 60.0, tight))
    out = f.iloc[[r[0] for r in rows]][["id", "cls", "grp", "t"]].reset_index(drop=True)
    out["lock"], out["hours"], out["tight"] = [r[1] for r in rows], [r[2] for r in rows], [r[3] for r in rows]
    return out


def tracks(f, geo):
    """Everything read from a list of fixes. f: id, t (min), cls, grp, piloted, x, y, lon, lat, zone, chain, basin,
    kn; sorted by id and t."""
    f = f.copy()
    f["sea_lon"] = np.where((f.zone == "sea") & (f.lat <= SEA_SECTION_MAX_LAT), f.lon, np.nan)
    p = [passages(f, "sea_lon", SEA_SECTION_LON, SEA_BAND_LON, "sea")]
    p += [passages(f, "chain", 1000.0 * km, BAND_M, name) for name, km in SECTIONS_KM.items()]
    under = f[(f.kn >= UNDER_WAY_KN) & f.zone.isin(("sea", "river", "dock")) & ((f.zone != "sea") | (f.lon >= MIN_SEA_LON))
              & f.grp.notna()]
    pil = f[(f.kn >= UNDER_WAY_KN) & f.piloted & f.zone.isin(("sea", "river", "dock")) & (f.lon >= PILOT_MIN_LON)]
    return SimpleNamespace(passages=pd.concat(p, ignore_index=True), locks=lock_passages(f, geo),
                           underway=under.groupby(["t", "zone", "grp"]).size(),
                           piloted=pil.groupby(["t", "zone"]).id.nunique())


def transits(pas):
    """Hours between two sections, per ship and direction: every passage of the first paired with the same
    ship's next passage of the second the same way."""
    out = []
    tight = pas[pas.gap <= TIGHT_GAP_MIN]
    for name, (a, b, grp) in TRANSITS.items():
        for d, (first, second) in ((1, (a, b)), (-1, (b, a))):
            u = tight[(tight.section == first) & (tight.dir == d) & (tight.grp == grp)].sort_values("t")
            v = tight[(tight.section == second) & (tight.dir == d) & (tight.grp == grp)].sort_values("t")
            if u.empty or v.empty:
                continue
            m = pd.merge_asof(u, v[["id", "t"]].rename(columns={"t": "t2"}).assign(t2b=lambda z: z.t2), left_on="t",
                              right_on="t2b", by="id", direction="forward", tolerance=TRANSIT_MAX_H * 60)
            m = m[m.t2.notna()]
            out.append(pd.DataFrame({"transit": name, "way": "in" if d == 1 else "out", "cls": m.cls, "grp": m.grp,
                                     "t": m.t, "hours": (m.t2 - m.t) / 60.0}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["transit", "way", "cls", "grp", "t", "hours"])


def from_tracks(tr, t0, t1, snapshots):
    """The numbers of the fixes between t0 and t1 (min). snapshots: the fix times in it (for the means)."""
    days = (t1 - t0) / 1440.0
    out = {}
    pas = tr.passages[(tr.passages.t >= t0) & (tr.passages.t < t1)]
    n = pas.groupby(["section", "grp"]).size()
    for sec in ["sea"] + list(SECTIONS_KM):
        for g in ("sea_going", "inland"):
            if sec == "sea" and g == "inland":
                continue
            out[f"flow.{sec}.{g}"] = n.get((sec, g), 0) / days
    out["port.antwerp_calls"] = int(((pas.section == "km48") & (pas.grp == "sea_going") & (pas.dir == 1)).sum()) / days
    lk = tr.locks[(tr.locks.t >= t0) & (tr.locks.t < t1)]
    n = lk.groupby(["lock", "grp"]).size()
    for name in LOCKS:
        for g in ("sea_going", "inland"):
            out[f"lockpass.{name}.{g}"] = n.get((name, g), 0) / days
    snaps = [s for s in snapshots if t0 <= s < t1]
    for (zone, g), s in tr.underway.groupby(level=["zone", "grp"]):
        s = s.droplevel(["zone", "grp"])
        out[f"underway.{zone}.{g}"] = float(s.reindex(snaps, fill_value=0).mean()) if snaps else math.nan
    for zone, s in tr.piloted.groupby(level="zone"):
        s = s.droplevel("zone").reindex(snaps, fill_value=0)
        out[f"pilots.{zone}.mean"] = float(s.mean()) if snaps else math.nan
        out[f"pilots.{zone}.p95"] = float(np.percentile(s, 95)) if snaps else math.nan
    return out


def durations(tr, t0, t1):
    """The samples of hours (not their summaries: the record's uncertainty is drawn from them)."""
    out = {}
    tt = transits(tr.passages)
    tt = tt[(tt.t >= t0) & (tt.t < t1)]
    for (name, way), g in tt.groupby(["transit", "way"]):
        out[f"transit.{name}.{way}"] = g.hours.to_numpy()
    lk = tr.locks[(tr.locks.t >= t0) & (tr.locks.t < t1) & tr.locks.tight]
    for (name, g_), g in lk.groupby(["lock", "grp"]):
        out[f"locktime.{name}.{g_}"] = g.hours.to_numpy()
    return out


def quantiles(samples, min_n=8):
    out = {}
    for k, v in samples.items():
        if len(v) >= min_n:
            out[k + ".median"] = float(np.median(v))
            out[k + ".p90"] = float(np.percentile(v, 90))
    return out


# ------------------------------------------------------------------ the model
def model_frame(sim, geo):
    """The model's positions as fixes: every ship under way, every step (bow position, at its mesh node)."""
    fg = sim.fg
    p = pd.DataFrame(sim.positions, columns=["step", "ship", "state", "route", "value", "offset"])
    m = p[p.route >= 0].sort_values(["ship", "step"], kind="stable").reset_index(drop=True)
    node = np.zeros(len(m), dtype=np.int64)
    rid, val = m.route.to_numpy(), m.value.to_numpy()
    order = np.argsort(rid, kind="stable")
    cuts = np.flatnonzero(np.r_[True, rid[order][1:] != rid[order][:-1], True])
    for i, j in zip(cuts[:-1], cuts[1:]):
        idx = order[i:j]
        n = np.asarray(sim.routes_rec[rid[idx[0]]], dtype=np.int64)
        ss = np.r_[0.0, np.cumsum(np.hypot(np.diff(fg.x[n]), np.diff(fg.y[n])))]
        node[idx] = n[np.clip(np.searchsorted(ss, val[idx], side="right") - 1, 0, len(n) - 1)]
    same = (m.ship == m.ship.shift()) & (m.route == m.route.shift()) & (m.step == m.step.shift() + 1)
    kn = (m.value.diff().where(same) / (STEP_MIN * 60.0) / 0.5144).to_numpy()
    nxt = np.r_[kn[1:], np.nan]                        # the first fix of a leg: the speed of the step after it
    kn = np.where(np.isnan(kn), np.where(np.r_[m.ship.to_numpy()[1:] == m.ship.to_numpy()[:-1], False], nxt, 0.0), kn)
    # the ships manoeuvring (MANOEUVRING): a fix at their node every step until their next record
    p = p.sort_values(["ship", "step"], kind="stable")
    until = p.step.shift(-1).where(p.ship.eq(p.ship.shift(-1)), sim.k + 1)
    still = p[(p.route < 0) & p.state.isin(MANOEUVRING + LYING)].assign(until=until)
    # (a pilot changed at a lock boards in the chamber, where a real ship lies still: only at sea and on the river)
    z = geo.zone[still.value.to_numpy().astype(np.int64)]
    still = still[still.state.isin(("mooring", "unmooring") + LYING) | np.isin(z, ("sea", "river"))]
    reps = (still.until - still.step).clip(lower=1).astype(int).to_numpy()
    s_ship = np.repeat(still.ship.to_numpy(), reps)
    s_step = np.repeat(still.step.to_numpy(), reps) + np.concatenate([np.arange(r) for r in reps]) if len(reps) else np.array([], dtype=int)
    s_node = np.repeat(still.value.to_numpy().astype(np.int64), reps)
    ship = np.r_[m.ship.to_numpy(), s_ship]
    step = np.r_[m.step.to_numpy(), s_step]
    node = np.r_[node, s_node]
    kn = np.r_[np.nan_to_num(kn), np.repeat(np.where(still.state.isin(LYING), 0.0, UNDER_WAY_KN), reps)]
    by = sim.by_id
    cls = pd.Series(ship).map(lambda i: by[i].cls)
    f = pd.DataFrame({"id": ship, "t": step * STEP_MIN, "cls": cls.to_numpy(),
                      "grp": cls.map(GROUP).to_numpy(), "piloted": pd.Series(ship).map(lambda i: by[i].needs_pilot).to_numpy(),
                      "x": fg.x[node], "y": fg.y[node], "lon": geo.lon[node], "lat": geo.lat[node],
                      "zone": geo.zone[node], "chain": geo.chain[node], "basin": geo.basin[node], "kn": kn})
    return f.sort_values(["id", "t"], kind="stable").reset_index(drop=True)


STATES = ("spawned", "to_station", "wait_clearance", "to_anchorage", "anchored", "boarding", "sailing", "pilot_change",
          "wait_pilot", "lock_queue", "in_lock", "mooring", "at_berth", "unmooring", "dwell_port", "exited")


def model_stocks(sim, t0, t1):
    """Mean number of ships per class in the area, at a berth, in another port and at anchor between t0 and t1
    (from the ships' state changes), and of container ships at the four terminals."""
    minutes = {}
    for s in sim.done + sim.ships:
        ev = [(e["t"], e["event"]) for e in s.log if e["event"] in STATES]
        for (a, state), (b, _) in zip(ev, ev[1:] + [(sim.t, "end")]):
            lo, hi = max(a, t0), min(b, t1)
            if hi <= lo or state == "exited":
                continue
            keys = ["in_area"] + {"at_berth": ["at_berth"], "dwell_port": ["at_berth"], "anchored": ["at_anchor"]}.get(state, [])
            if state == "at_berth" and s.terminal:
                keys.append("at_terminal")
            for k in keys:
                minutes[(s.cls, k)] = minutes.get((s.cls, k), 0.0) + hi - lo
    out = {}
    for c in SEA + INLAND:
        for k in ("in_area", "at_berth", "at_anchor"):
            out[f"stock.{c}.{k}"] = minutes.get((c, k), 0.0) / (t1 - t0)
    out["container.at_terminals"] = minutes.get(("container", "at_terminal"), 0.0) / (t1 - t0)
    return out


def simulated(sim, ships=None):
    """The numbers of one finished run, after its warm-up."""
    geo = geometry(sim.graph, sim.fg)
    t0, t1 = float(sim.warmup_min), float(sim.t)
    days = (t1 - t0) / 1440.0
    f = model_frame(sim, geo)
    tr = tracks(f, geo)
    out = from_tracks(tr, t0, t1, np.arange(t0, t1, STEP_MIN))
    out.update(quantiles(durations(tr, t0, t1)))
    out.update(model_stocks(sim, t0, t1))
    ships = sim.ship_table() if ships is None else ships
    new = ships[(ships.spawn_min >= t0) & (ships.spawn_min < t1)]
    for c, n in new.groupby("class").size().items():
        out[f"arrivals.{c}"] = n / days
    for lock, n in (sim.summary(ships).get("locks") or {}).items():         # the engine's own count of lockages
        name, kind = lock.rsplit(".", 1)
        if name in RWS_PASSAGES:
            out[f"rws.{name}"] = out.get(f"rws.{name}", 0.0) + n
    # container ships at the terminals
    c = ships[(ships["class"] == "container") & ships.terminal.notna() & ships.moored_min.notna() & (ships.spawn_min >= t0)]
    if len(c):
        late = (c.moored_min - c.scheduled_berth_min) / 60.0
        out["container.delay.mean"], out["container.delay.sd"] = float(late.mean()), float(late.std())
        out["container.anchoring_share"] = float((c.min_anchored.fillna(0) >= 30).mean())
        wait = (c.moored_min - c.planned_berth_min) / 60.0
        out["container.late_over_12h_share"] = float((wait > 12).mean())
        stay = c[c.finished].min_at_berth / 60.0
        if len(stay) >= 8:
            out["container.stay.median"] = float(stay.median())
        first = tr.passages[(tr.passages.section == "sea") & (tr.passages.dir == 1)].groupby("id").t.min()
        h = ((c.set_index("id").moored_min - first) / 60.0).dropna()
        h = h[h > 0]
        if len(h) >= 8:
            out["container.sea_to_berth.median"], out["container.sea_to_berth.p90"] = float(h.median()), float(np.percentile(h, 90))
    return {k: (None if isinstance(v, float) and math.isnan(v) else round(float(v), 4)) for k, v in out.items()}


# ------------------------------------------------------------------ the AIS record
def ais_frame(data, geo):
    from pyproj import Transformer
    from scipy.spatial import cKDTree

    df, ships, visits = data.df, data.ships, data.visits
    cls = df.mmsi.map(ships["class"])
    keep = cls.isin(PILOTED + INLAND) & df.visit.map(visits.scheldt_bound).fillna(False).astype(bool)
    df, cls = df[keep], cls[keep]
    x, y = Transformer.from_crs("EPSG:4326", geo.crs, always_xy=True).transform(df.lon.to_numpy(), df.lat.to_numpy())
    w = np.flatnonzero(geo.water)
    dist, i = cKDTree(np.column_stack([geo.x[w], geo.y[w]])).query(np.column_stack([x, y]))
    node, on = w[i], dist <= SNAP_MAX_M
    t0 = data.times.iloc[0]
    f = pd.DataFrame({"id": df.visit.to_numpy(), "t": (df.t - t0).dt.total_seconds().to_numpy() / 60.0, "cls": cls.to_numpy(),
                      "grp": cls.map(GROUP).to_numpy(),
                      "piloted": (cls.isin(PILOTED) & (df.mmsi.map(ships.length) > 80)).to_numpy(), "x": x, "y": y,
                      "lon": df.lon.to_numpy(), "lat": df.lat.to_numpy(), "zone": np.where(on, geo.zone[node], ""),
                      "chain": np.where(on, geo.chain[node], np.nan), "basin": np.where(on, geo.basin[node], -1),
                      "kn": df.sog.fillna(0.0).to_numpy()})
    return f.sort_values(["id", "t"], kind="stable").reset_index(drop=True), t0


def day_means(values):
    """Mean and standard error of a number that has one value a day."""
    v = np.asarray([x for x in values if x is not None and not math.isnan(x)], dtype=float)
    if not len(v):
        return None
    return {"value": float(v.mean()), "se": float(v.std(ddof=1) / math.sqrt(len(v))) if len(v) > 1 else None, "n": int(len(v))}


def interval_stock(start, end, day_edges):
    """Mean number of intervals open, per day (the overlap of each with the day, over the day's length)."""
    s, e = np.asarray(start, dtype=float), np.asarray(end, dtype=float)
    return [float(np.clip(np.minimum(e, b) - np.maximum(s, a), 0, None).sum() / (b - a)) for a, b in day_edges]


def observed(cache=None):
    """Every number of the AIS record with its day-to-day standard error."""
    import ais_pipeline as AP
    import container_calls as CC
    import entry_probabilities as EP
    import generator as G
    from fast_graph import FastGraph

    if cache and Path(cache).exists():
        data, stops = pickle.load(open(cache, "rb"))
    else:
        data = AP.prepare()
        stops = AP.find_stops(data.df)
        if cache:
            data.zones = None
            pickle.dump((data, stops), open(cache, "wb"))
    graph = pickle.load(open(ROOT / "cache" / "antwerp_scheldt_graph.pkl", "rb"))["graph"]
    geo = geometry(graph, FastGraph.load(ROOT / "cache" / "antwerp_scheldt_graph.arrays.npz", graph))
    f, t0 = ais_frame(data, geo)
    minute = lambda ts: (ts - t0).dt.total_seconds() / 60.0
    snaps = minute(data.times).to_numpy()
    span = float(snaps[-1])
    # whole days of the record (UTC), each with enough snapshots
    first = (t0.normalize() - t0).total_seconds() / 60.0
    edges = [(a, a + 1440.0) for a in np.arange(first, span, 1440.0)]
    edges = [(a, b) for a, b in edges if ((snaps >= a) & (snaps < b)).sum() * STEP_MIN >= MIN_DAY_H * 60]
    tr = tracks(f, geo)
    out = {}
    per_day = [from_tracks(tr, a, b, snaps) for a, b in edges]
    for k in per_day[0]:
        out[k] = day_means([d.get(k) for d in per_day])
    # durations: the median and the 90th percentile, their error by resampling the passages
    rng = np.random.default_rng(1)
    for k, v in durations(tr, edges[0][0], edges[-1][1]).items():
        if len(v) < 8:
            continue
        boot = np.array([[np.median(b), np.percentile(b, 90)] for b in (rng.choice(v, len(v)) for _ in range(400))])
        out[k + ".median"] = {"value": float(np.median(v)), "se": float(boot[:, 0].std()), "n": int(len(v))}
        out[k + ".p90"] = {"value": float(np.percentile(v, 90)), "se": float(boot[:, 1].std()), "n": int(len(v))}
    # ships in the area, at a berth, at anchor: the visits and stops of the pipeline
    import fit_background_traffic as FB

    visits, ships = data.visits, data.ships
    v = visits[visits.scheldt_bound & visits["class"].isin(SEA + INLAND)]
    st = stops[stops.visit.isin(v.index)].copy()
    st["cls"] = st.mmsi.map(ships["class"])
    # an inland craft not heard for hours has left (it comes back to the same quay days later): its stops are
    # cut there, as in the fit of the stays
    cut = AP.find_stops(data.df[data.df.visit.isin(v.index[v["class"].isin(INLAND)])], max_gap_h=FB.INLAND_SILENT_H)
    cut["cls"] = cut.mmsi.map(ships["class"])
    calls = pd.concat([AP.berth_calls(st[st.cls.isin(SEA)]), AP.berth_calls(cut)])
    anchor = st[st.kind == "anchorage"]
    # in the area: a visit, less the silences in which the ship was away (under way before or after one of
    # AWAY_H or more: out by an edge and back, which the pipeline keeps as one visit when it comes back near
    # where it left)
    d = data.df[data.df.visit.isin(v.index)].sort_values(["visit", "t"])
    tm, vis, sog = minute(d.t).to_numpy(), d.visit.to_numpy(), d.sog.fillna(0.0).to_numpy()
    cut = np.flatnonzero((vis[1:] != vis[:-1]) | ((tm[1:] - tm[:-1] >= AWAY_H * 60) & ((sog[1:] >= UNDER_WAY_KN) | (sog[:-1] >= UNDER_WAY_KN))))
    lo, hi = np.r_[0, cut + 1], np.r_[cut, len(tm) - 1]
    there = pd.DataFrame({"cls": pd.Series(vis[lo]).map(v["class"]).to_numpy(), "start": tm[lo], "end": tm[hi]})
    for c in SEA + INLAND:
        g = there[there.cls == c]
        out[f"stock.{c}.in_area"] = day_means(interval_stock(g.start, g.end, edges))
        b = calls[calls.cls == c]
        out[f"stock.{c}.at_berth"] = day_means(interval_stock(minute(b.start), minute(b.end), edges))
        a = anchor[anchor.cls == c]
        out[f"stock.{c}.at_anchor"] = day_means(interval_stock(minute(a.start), minute(a.end), edges))
    # container ships at the terminals
    cc = calls[(calls.cls == "container") & calls.zone.isin(TERMINAL_ZONES)]
    out["container.at_terminals"] = day_means(interval_stock(minute(cc.start), minute(cc.end), edges))
    whole = cc[cc.start_observed & cc.end_observed].hours.to_numpy()
    boot = np.array([np.median(rng.choice(whole, len(whole))) for _ in range(400)])
    out["container.stay.median"] = {"value": float(np.median(whole)), "se": float(boot.std()), "n": int(len(whole))}
    seen = cc[cc.start_observed & ~cc.at_visit_start].sort_values("start").groupby("visit").head(1)
    anch_start = anchor.groupby("visit").start.min()
    anchored = (seen.visit.map(anch_start) < seen.start).fillna(False)
    p = float(anchored.mean())
    out["container.anchoring_share"] = {"value": p, "se": math.sqrt(p * (1 - p) / len(seen)), "n": int(len(seen))}
    cross = tr.passages[(tr.passages.section == "sea") & (tr.passages.dir == 1)].groupby("id").t.min()
    h = ((minute(seen.set_index("visit").start) - cross) / 60.0).dropna()
    h = h[h > 0].to_numpy()
    boot = np.array([[np.median(b), np.percentile(b, 90)] for b in (rng.choice(h, len(h)) for _ in range(400))])
    out["container.sea_to_berth.median"] = {"value": float(np.median(h)), "se": float(boot[:, 0].std()), "n": int(len(h))}
    out["container.sea_to_berth.p90"] = {"value": float(np.percentile(h, 90)), "se": float(boot[:, 1].std()), "n": int(len(h))}
    d = np.asarray(CC.SCHEDULE_DELAY_H["arrival"]["values"], dtype=float)
    out["container.delay.mean"] = {"value": float(d.mean()), "se": float(d.std(ddof=1) / math.sqrt(len(d))), "n": int(len(d))}
    boot = np.array([rng.choice(d, len(d)).std(ddof=1) for _ in range(400)])
    out["container.delay.sd"] = {"value": float(d.std(ddof=1)), "se": float(boot.std()), "n": int(len(d))}
    # what goes in: the fitted arrival rates (inland craft scaled to the lock counts), the schedule's calls
    hours = EP.EXPOSURE_HOURS
    for c in SEA[1:] + INLAND + ("passenger",):
        rate = 24.0 * sum(EP.RATE_PER_HOUR[c].values())
        scaled = 24.0 * sum(r * (G.INLAND_TRIP_SCALE if c in INLAND and s in G.INLAND_SCALED_SOURCES else 1.0)
                            for s, r in EP.RATE_PER_HOUR[c].items())
        out[f"arrivals.{c}"] = {"value": scaled, "se": scaled / rate * math.sqrt(rate * hours / 24.0) / (hours / 24.0),
                                "n": int(rate * hours / 24.0)}
    sched = G.read_schedule()
    in_record = sched[(sched.arrival >= t0) & (sched.arrival <= data.times.iloc[-1])]
    days = span / 1440.0
    # ... and the container calls the schedule lacks, at the terminals (generator.UNSCHEDULED_CODES)
    off = getattr(CC, "UNSCHEDULED_CALLS", None) or {"per_day": 0.0, "zones": {}}
    extra = off["per_day"] * sum(off["zones"].get(z, 0.0) for z in G.UNSCHEDULED_CODES)
    out["arrivals.container"] = {"value": len(in_record) / days + extra, "se": math.sqrt(len(in_record) + extra * days) / days,
                                 "n": int(len(in_record) + extra * days)}
    for name, n in RWS_PASSAGES.items():
        out[f"rws.{name}"] = {"value": n, "se": None, "n": None}
    ais_calls = out["port.antwerp_calls"]
    out["port.antwerp_calls"] = {"value": sum(PORT_CALLS_A_DAY) / 2, "se": (PORT_CALLS_A_DAY[1] - PORT_CALLS_A_DAY[0]) / 2, "n": None}
    meta = {"first": str(t0), "last": str(data.times.iloc[-1]), "snapshots": int(len(snaps)), "days_counted": len(edges),
            "ais_container_class_per_day": round(24.0 * sum(EP.RATE_PER_HOUR["container"].values()), 2),
            "ais_antwerp_calls_per_day": round(ais_calls["value"], 1) if ais_calls else None}
    return {"meta": meta, "numbers": {k: v for k, v in out.items() if v is not None}}


# ------------------------------------------------------------------ the comparison
def label(metric):
    """(group, what it is, unit, kind I / C / E, tolerance) of a number, from its name."""
    p = metric.split(".")
    cls = {"container": "container ships", "bulk_general": "bulk and general cargo ships", "tanker": "tankers",
           "inland_cargo": "inland cargo craft", "inland_tanker": "inland tankers", "passenger": "passenger ships",
           "sea_going": "sea-going", "inland": "inland"}
    if p[0] == "arrivals":
        return "Arrivals", f"{cls[p[1]]} entering", "a day", "I", 0.10
    if p[0] == "flow":
        return "River traffic", f"{SECTION_NAMES[p[1]]}: {cls[p[2]]}", "passages a day", "E", 0.15 if p[2] == "sea_going" else 0.25
    if p[0] == "lockpass":
        return "Locks", f"{p[1]}: {cls[p[2]]} passing", "a day", "E", 0.15 if p[2] == "sea_going" else 0.25
    if p[0] == "rws":
        return "Locks", f"{p[1]}: commercial passages, Rijkswaterstaat's count", "a day", "C", 0.10
    if p[0] == "locktime":
        return "Locks", f"{p[1]}: {cls[p[2]]}, time to pass, {'median' if p[3] == 'median' else '90th percentile'}", "h", "C", 0.20
    if p[0] == "underway":
        return "Ships under way", f"{p[1]}: {cls[p[2]]}", "ships", "E", 0.15 if p[2] == "sea_going" else 0.25
    if p[0] == "pilots":
        return "Piloted ships under way", f"{p[1]}, {'mean' if p[2] == 'mean' else '95th percentile'}", "ships", "E", 0.15
    if p[0] == "port":
        return "River traffic", "sea-going ships calling at Antwerp (the port's statistics, 2020 and 2021)", "a day", "E", 0.10
    if p[0] == "transit":
        a, b, grp = TRANSITS[p[1]]
        way = f"{SECTION_NAMES[a].split(',')[0]} to {SECTION_NAMES[b].split(',')[0]}" if p[2] == "in" else \
            f"{SECTION_NAMES[b].split(',')[0]} to {SECTION_NAMES[a].split(',')[0]}"
        return "Sailing times", f"{cls[grp]}, {way}, {'median' if p[3] == 'median' else '90th percentile'}", "h", \
            "C" if grp == "sea_going" and p[3] == "median" else "E", 0.10
    if p[0] == "stock":
        what = {"in_area": "in the area", "at_berth": "at a berth", "at_anchor": "at anchor"}[p[2]]
        kind = "E" if p[2] == "in_area" else ("C" if (p[2] == "at_anchor" and p[1] in ("bulk_general", "tanker"))
                                              or (p[2] == "at_berth" and p[1] in INLAND) else "I" if p[2] == "at_berth" else "E")
        return "Ships in the area", f"{cls[p[1]]} {what}", "ships", kind, 0.15
    names = {"container.at_terminals": ("at the four terminals", "ships", "E", 0.15),
             "container.stay.median": ("time at the berth, median", "h", "I", 0.10),
             "container.anchoring_share": ("share that anchors before berthing", "", "E", 0.5),
             "container.sea_to_berth.median": ("3.10°E to the berth, median", "h", "E", 0.10),
             "container.sea_to_berth.p90": ("3.10°E to the berth, 90th percentile", "h", "E", 0.25),
             "container.delay.mean": ("berthing against the schedule, mean", "h", "I", 0.15),
             "container.delay.sd": ("berthing against the schedule, standard deviation", "h", "I", 0.15),
             "container.late_over_12h_share": ("share berthing over 12 h after their planned time", "", "E", 1.0)}
    if metric in names:
        return ("Container ships",) + names[metric]
    return "Other", metric, "", "E", 0.15


def compare(folder, observed_path=None):
    """Set the replications of a folder against the record. Returns the table (and writes it there)."""
    folder = Path(folder)
    obs = json.loads(Path(observed_path or OUT / "observed.json").read_text())
    reps = pd.read_csv(folder / "replications.csv")
    rows = []
    cols = [c for c in reps.columns if c.startswith("v.")]
    for col in cols:
        k = col[2:]
        x = reps[col].dropna().to_numpy(dtype=float)
        if not len(x):
            continue
        o = obs["numbers"].get(k)
        group, what, unit, kind, tol = label(k)
        m, se_m = float(x.mean()), (float(x.std(ddof=1) / math.sqrt(len(x))) if len(x) > 1 else None)
        row = {"number": k, "group": group, "what": what, "unit": unit, "kind": kind, "model": m, "model_se": se_m, "reps": len(x)}
        if o:
            se = math.sqrt((se_m or 0.0) ** 2 + (o["se"] or 0.0) ** 2)
            diff = m - o["value"]
            rel = diff / o["value"] if o["value"] else math.nan
            z = diff / se if se > 0 else math.inf
            ok = abs(z) <= 2.0 or (not math.isnan(rel) and abs(rel) <= tol)
            row.update(record=o["value"], record_se=o["se"], difference=rel, z=z, tolerance=tol,
                       verdict="agrees" if ok else "differs")
        rows.append(row)
    order = ["Arrivals", "River traffic", "Sailing times", "Ships under way", "Piloted ships under way", "Locks",
             "Ships in the area", "Container ships", "Other"]
    t = pd.DataFrame(rows)
    t["g"] = t.group.map(order.index)
    t = t.sort_values(["g", "number"], kind="stable").drop(columns="g").reset_index(drop=True)
    t.to_csv(folder / "validation.csv", index=False)
    (folder / "validation.md").write_text(markdown(t, obs["meta"], folder.name), encoding="utf-8")
    return t


def markdown(t, meta, name):
    def num(v, se=None):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return ""
        d = 2 if abs(v) < 10 else 1 if abs(v) < 100 else 0
        return f"{v:.{d}f}" + (f" ± {1.96 * se:.{d}f}" if se else "")

    seen = t[t.record.notna()] if "record" in t else t.iloc[:0]
    lines = [f"# Validation of {name}", "",
             f"AIS record {meta['first'][:16]} to {meta['last'][:16]} UTC, {meta['snapshots']} snapshots, {meta['days_counted']} whole days. "
             f"Model: mean of {int(t.reps.max())} replications. ± is a 95 % interval (the record's from its day-to-day spread).",
             "A number agrees when the difference is within twice its standard error or within the tolerance.", ""]
    for kind, title in (("E", "emergent"), ("C", "calibrated"), ("I", "input")):
        g = seen[seen.kind == kind]
        if len(g):
            lines.append(f"- {title}: {int((g.verdict == 'agrees').sum())} of {len(g)} agree")
    for group, g in t.groupby("group", sort=False):
        lines += ["", f"## {group}", "", "| | Kind | Record | Model | Difference | |", "| --- | --- | --- | --- | --- | --- |"]
        for r in g.itertuples():
            rec = getattr(r, "record", math.nan)
            has = rec is not None and not (isinstance(rec, float) and math.isnan(rec))
            lines.append(f"| {r.what}{', ' + r.unit if r.unit else ''} | {r.kind} | {num(rec, r.record_se) if has else ''} | "
                         f"{num(r.model, r.model_se)} | {f'{100 * r.difference:+.0f} %' if has else ''} | {r.verdict if has else ''} |")
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("observe", help="measure the AIS record")
    o.add_argument("--cache", help="keep the prepared AIS here (a pickle) to run again faster")
    c = sub.add_parser("compare", help="set a folder of replications against the record")
    c.add_argument("folder")
    a = p.parse_args()
    if a.cmd == "observe":
        OUT.mkdir(parents=True, exist_ok=True)
        out = observed(a.cache)
        (OUT / "observed.json").write_text(json.dumps(out, indent=1))
        print(f"{len(out['numbers'])} numbers of the record -> {OUT / 'observed.json'}")
    else:
        t = compare(a.folder)
        pd.set_option("display.width", 250, "display.max_rows", 400, "display.max_colwidth", 70)
        show = t[t.record.notna()] if "record" in t else t
        print(show[["what", "kind", "record", "model", "difference", "z", "verdict"]].round(2).to_string())
        print(f"\n{Path(a.folder) / 'validation.md'}")


if __name__ == "__main__":
    main()
