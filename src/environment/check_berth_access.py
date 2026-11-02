"""Check that every berth can be reached by a ship with the berth's allowed draught.

For each berth of graph.graph["berths"] with a maximum allowed draught (harbour master's data),
a ship of that draught + the berth's minimum UKC must reach the berth from the deepest cell of the
main channel, at the water level it can expect: the fixed level in the docks behind the locks and
mean high water on tidal water. The check uses the simulation's own router (fast_graph: depths,
lock sills and chamber sizes), not the builder's widest-path step, so it checks that step.

Usage:
    py src/environment/check_berth_access.py
Prints the berths that cannot be reached, and exits with 1 if there are any.
"""

from __future__ import annotations

import collections
import pickle
import sys

import numpy as np

from antwerp_port import DEFAULT_BERTH_UKC_M, DEFAULT_OUTPUT, _mean_high_water
from fast_graph import FastGraph
from tide import TideModel


def main():
    graph = pickle.load(open(DEFAULT_OUTPUT, "rb"))["graph"]
    fg = FastGraph.load(DEFAULT_OUTPUT.with_suffix(".arrays.npz"), graph)
    model = TideModel.load()
    fg.bind_tide(model)
    mhw = _mean_high_water(model)
    level = fg.levels(mhw)                                      # tidal cells at mean high water, basins at their level
    river = np.flatnonzero(fg.mask("region", "river"))
    source = int(fg.ids[river[np.argmax(fg.depth_m[river])]])
    berths = graph.graph["berths"]
    by_need = collections.defaultdict(list)
    for bid, b in berths.items():
        if b.get("max_draught_m") is None or not b["nodes"] or b.get("berth_type") == "Sluis":
            continue                                            # lock chambers are not berths
        need = round(b["max_draught_m"] + (b.get("min_ukc_m") or DEFAULT_BERTH_UKC_M), 2)
        size = (float(b.get("max_loa_m") or 0.0), float(b.get("max_beam_m") or 0.0))
        by_need[(need, size)].append(bid)
    failed = []
    for (need, (loa, beam)), ids in sorted(by_need.items()):
        reach = fg.reachable(source, need, 0.0, loa, beam, level=level)
        for bid in ids:
            b = berths[bid]
            if not reach[fg.index[b["nodes"][len(b["nodes"]) // 2]]]:
                failed.append((bid, b["zone"], b["max_draught_m"], need, b.get("access")))
    checked = sum(len(v) for v in by_need.values())
    print(f"berths with an allowed draught and graph cells: {checked}; reachable at that draught: {checked - len(failed)}")
    by_access = collections.Counter(b.get("access") for b in berths.values())
    print(f"builder access result: {dict(by_access)}")
    for row in failed:
        print("  NOT REACHABLE:", row)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
