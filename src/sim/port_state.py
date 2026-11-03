"""What the port looks like at every step, for the viewer's statistics window: the state of every lock
chamber, the VTS queue, the terminals' quay queues and which ship each berth is kept for.

Called by the engine after each step (Simulation._record). To stay small, every item is logged only
when it changes: a list of [t, ...] records per item, the item's state from t until the next record.

    locks        "<lock>|<chamber>": [t, state, side, until, task, task ship, inside, waiting a, waiting b,
                 reserved for, reserved from]       state: open / closing / levelling / opening, at the
                 water of `side`; until: when the current task or gate movement ends; task: enter / exit / pass
    held         "<lock>": [t, ships]               kept in the lock while a ULCV passes (regs)
    vts          [t, [[ship, reason, since, departing, state, anchorage], ...]]   in the VTS's order of
                 treatment (distress, tide-dependent, first come first served); reason: the check that
                 failed at its last planning round (None: not looked at yet)
    quay_queue   "<terminal>": [t, [[ship, since], ...]]    ships waiting for room at the quay
    berths       "T:<terminal>": [t, [[ship, s0, s1, state, cranes], ...]]   quay kept or used
                 "B:<berth id>": [t, ship or None, state]
                 "P:<place>": [t, [[ship, state], ...]]   ports without a berth model (Vlissingen, ...)
    static       the locks' chambers and sides, the terminals' quay and slots, the berths that were used

The ship's state in the berth records tells where it is: sailing / lock_queue / ... = still coming,
mooring, at_berth, wait_clearance (ready to leave), unmooring.
"""

from __future__ import annotations

import gzip
import json


def _r(x, d=1):
    return None if x is None else round(float(x), d)


class PortStateLog:
    def __init__(self, sim):
        self.sim = sim
        self.locks, self.held, self.quay_queue, self.berths = {}, {}, {}, {}
        self.vts = []
        self._last = {}                     # item -> its last logged value (without t)
        self._vts_since = {}                # ship id -> when it joined the VTS queue
        self._used_berths = set()

    def _log(self, store, key, t, value):
        k = (id(store), key)
        if self._last.get(k) != value:
            self._last[k] = value
            store.setdefault(key, []).append([t, *value])

    # ------------------------------------------------------------------ one step
    def record(self, now):
        sim = self.sim
        t = round(float(now), 1)
        for name, (_, lock) in sim.locks.items():
            for c in lock.chambers:
                task, task_ship = None, None
                if c.task:
                    task, item = c.task
                    task_ship = item.ship.ship_id if hasattr(item, "ship") else item.ship_id
                reserved = c.reserved_for
                value = [c.state, c.side, _r(now + c.timer_min) if c.timer_min > 1e-9 else None, task, task_ship,
                         [p.ship.ship_id for p in c.ships], [s.ship_id for s in c.queue["a"]],
                         [s.ship_id for s in c.queue["b"]], reserved, _r(c.reserved_from) if reserved else None]
                self._log(self.locks, f"{name}|{c.name}", t, value)
            self._log(self.held, name, t, [[s.id for s in sim.held_exits.get(name, [])]])

        # the VTS queue, in the order the VTS treats it
        queue = sorted(sim.vts.requests, key=lambda s: s.vts_priority())
        ids = {s.id for s in queue}
        for s in list(self._vts_since):
            if s not in ids:
                del self._vts_since[s]
        rows = []
        for s in queue:
            since = self._vts_since.setdefault(s.id, t)
            rows.append([s.id, s.times.get("vts_wait_reason"), since, bool(s.departing), s.state.value, s.anchorage])
        value = [rows]
        if self._last.get("vts") != value:
            self._last["vts"] = value
            self.vts.append([t, rows])

        for name in sim.terminals:
            q = sim.terminal_waiting.get(name, {})
            self._log(self.quay_queue, name, t, [[[s, _r(since)] for s, since in sorted(q.items(), key=lambda x: x[1])]])

        # berths: the quay each terminal keeps or gives, the berth each ship is kept for, the ports
        by_id = sim.by_id
        for name, T in sim.terminals.items():
            rows = []
            for m in sorted(T.ships, key=lambda m: m.s0):
                s = by_id.get(m.ship_id)
                rows.append([m.ship_id, _r(m.s0), _r(m.s1), s.state.value if s else None, m.cranes])
            self._log(self.berths, f"T:{name}", t, [rows])
        held = {}
        for b, sid in sim.berth_ship.items():
            s = by_id.get(sid)
            held[b] = [sid, s.state.value if s else None]
        for b in self._used_berths - set(held):
            held[b] = [None, None]
        for b, value in held.items():
            self._used_berths.add(b)
            self._log(self.berths, f"B:{b}", t, value)
        ports = {}
        for s in sim.ships:
            b = s.berth or {}
            if b.get("kind") == "place":
                ports.setdefault(b["name"], []).append([s.id, s.state.value])
        for p in set(ports) | {k[2:] for k in self.berths if k.startswith("P:")}:
            self._log(self.berths, f"P:{p}", t, [sorted(ports.get(p, []))])

    # ------------------------------------------------------------------ output
    def static(self):
        sim = self.sim
        locks = {name: {"type": lock.lock_type,
                        "sides": {s: {"zone": d["zone"], "tidal": d["tidal"]} for s, d in lock.sides.items()},
                        "chambers": [{"name": c.name, "length_m": c.length_m, "width_m": c.width_m,
                                      "sill_m": c.sill_depth_m} for c in lock.chambers]}
                 for name, (_, lock) in sim.locks.items()}
        terminals = {name: {"quay_m": round(T.quay_length_m), "sts": T.sts,
                            "slots": {b: [r["s0"], r["s1"]] for b, r in sorted(T.berths.items(), key=lambda x: x[1]["s0"])}}
                     for name, T in sim.terminals.items()}
        berths = {}
        for b in sorted(self._used_berths):
            r = sim.berths.get(b, {})
            berths[b] = {"zone": r.get("zone"), "lpl": r.get("lpl"), "length_m": r.get("berth_length_m") or r.get("length_m"),
                         "max_draught_m": r.get("max_draught_m"), "tidal": r.get("tidal"), "type": r.get("berth_type"),
                         "tanker": r.get("tanker_berth")}
        return {"locks": locks, "terminals": terminals, "berths": berths}

    def save(self, path):
        out = {"static": self.static(), "locks": self.locks, "held": self.held, "vts": self.vts,
               "quay_queue": self.quay_queue, "berths": self.berths}
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(out, f, separators=(",", ":"), default=str)
