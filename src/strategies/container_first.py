"""An example strategy: the baseline with container ships first.

Container ships are cleared before the other ships of their priority class (after ships in distress and
tide-dependent ships, as in the baseline), are given right of way under way ahead of the ships cleared before them,
and go into the lock queues as "ordered ahead" (priority 1). Everything else is the baseline. A small example of
three levers (clearance order, rank, lock priority), not a recommendation.

Options: classes (list of ship classes to put first, default ["container"]).
"""

from __future__ import annotations

from strategies.baseline import Baseline


class ContainerFirst(Baseline):
    name = "container_first"
    description = "baseline order, but container ships first in their class, in right of way and at the locks"
    levers = ("clearance", "anchorage", "rank", "lock_priority")

    def start(self):
        self.first = set(self.options.get("classes", ["container"]))

    def order(self, ship):
        base = self.view.default_priority(ship)
        return (base[0], ship.cls not in self.first, base[1])

    def on_tick(self, now):
        view, control = self.view, self.control
        for ship in sorted((s for s in view.requests() if s.needs_pilot), key=self.order):
            if not ship.ready:
                continue
            result = control.clear(ship)
            if result.ok and ship.cls in self.first:
                control.set_rank(ship, max(ship.rank - 1000, 0))     # ahead of the last thousand cleared
            if result.ok or result.removed or result.reason == "pilot_lost":
                continue
            self.not_cleared(ship, result)

    def lock_priority(self, ship, lock, default):
        return 1 if ship.cls in self.first and default > 1 else None
