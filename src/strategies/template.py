"""A template for a new VTS strategy: every hook of the API, documented, each doing what the baseline does.

Copy this file to src/strategies/<your_name>.py, rename the class and its `name`, and change what you decide.
Delete the hooks you do not use: an overridden hook makes the engine build its options even when it returns None.
docs/VTS_API.md is the full guide (the view, the orders, what is checked, what cannot be changed).
"""

from __future__ import annotations

from strategies.baseline import Baseline


class Template(Baseline):
    name = "template"
    description = "the baseline, with every hook written out (a starting point)"
    levers = ("clearance", "anchorage")         # declare every lever you use (vts_api.LEVERS)

    def start(self):
        """Once before the first step: read self.options (Simulation(vts_options=...)), set up your state."""
        self.horizon_min = float(self.options.get("horizon_min", 0.0))

    # ---------------------------------------------------------------- clearance
    def on_request(self, ship):
        """A ship asked, or a recheck you set came due. Clear it now (self.control.clear), set a recheck, or
        leave it for on_tick. The baseline clears ships without a pilot at once and leaves pilot ships for the
        round."""
        super().on_request(ship)

    def on_tick(self, now):
        """Every 15 min. self.view.requests() are the waiting ships; self.control.clear(ship) clears one if it
        passes the checks, else returns why not (Result.reason). What to do with a ship that is not cleared is
        yours: wait (do nothing), self.control.wait_at_sea(ship, max_min), self.control.send_to_anchorage(ship)."""
        super().on_tick(now)

    # ---------------------------------------------------------------- choices: return None for the default
    def arrival_delay(self, ship, default_min):
        """Minutes to hold this ship at sea before it enters (0 .. vts_api.ARRIVAL_DELAY_MAX_MIN)."""
        return None

    def choose_berth(self, ship, options, default):
        """A berth id from options for a ship bound to a berth zone."""
        return None

    def choose_quay_position(self, ship, terminal, options, default):
        """A quay metre s0 at a container terminal: [s0, s0 + ship.loa] inside one of options [(a, b)]."""
        return None

    def anchorage_order(self, ship, options):
        """Anchorage names to try, in order (a subset of options; [] keeps the ship where it is)."""
        return None

    def exit_order(self, ship, options):
        """Sea exits to try first (the others follow)."""
        return None

    def avoid_locks(self, ship, default):
        """Lock names this ship keeps off where it has a choice (a cost on its routes, not a ban)."""
        return None

    def assign_pilots(self, ship, zone, n, free, default):
        """n pilot ids from free."""
        return None

    def assign_tugs(self, ship, n, free, default):
        """n tug ids from free (nearest first)."""
        return None

    def choose_chamber(self, ship, lock, options, default):
        """A chamber name from options."""
        return None

    def lock_priority(self, ship, lock, default):
        """1 ordered ahead, 2 tide-dependent, 3 sea-going, 4 inland."""
        return None

    def keep_lock_open(self, lock, chamber, default):
        """True: keep the gates open for more ships; False: close and start the lockage now."""
        return None
