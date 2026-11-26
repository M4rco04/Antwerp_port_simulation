# VTS strategy API

This is the guide for writing a traffic-management strategy for the simulation and comparing it with others. The model (MODEL.md) owns the physics and the rules; a strategy owns the decisions a vessel traffic service could make, together with the lock planners, the pilot and tug dispatchers and the harbour master behind it. Every strategy runs on the same model, the same ships and the same weather (common random numbers, MODEL.md §1), so the difference between two runs on one seed is the difference the decisions made.

The code: `src/agents/vts_api.py` (the API a strategy sees), `src/agents/vts.py` (the engine's side: the queue, the checks, carrying out orders), `src/strategies/` (the strategies, one module each).

## 1. Quick start

1. Copy `src/strategies/template.py` to `src/strategies/my_strategy.py`. Rename the class and set `name = "my_strategy"`.
2. Change the hooks you decide; delete the ones you don't.
3. Run it:

```powershell
py src/sim/pipeline.py --days 7 --vts my_strategy --label "my strategy"
```

4. Compare it with the baseline on the same seeds:

```powershell
py src/sim/replicate.py --days 14 --reps 5 --label baseline
```

```powershell
py src/sim/replicate.py --days 14 --reps 5 --label mine --vts my_strategy
```

Options reach the strategy's constructor as `self.options`: `--vts-option horizon_min=360` (values read as JSON where they can be), or `Simulation(vts="my_strategy", vts_options={"horizon_min": 360})`. A strategy kept outside the repository is named by `module:Class` or `path/to/file.py:Class`. The setup page (`py src/ui/app.py`) has a field for it.

A minimal strategy, the baseline with tide-dependent and container ships first and nothing else changed:

```python
from strategies.baseline import Baseline


class DeepFirst(Baseline):
    name = "deep_first"
    description = "tide-dependent ships, then container ships, then first come first served"
    levers = ("clearance", "anchorage")

    def on_tick(self, now):
        key = lambda s: (not s.tide_dependent, s.cls != "container", s.request_t)
        for ship in sorted((s for s in self.view.requests() if s.needs_pilot), key=key):
            if not ship.ready:
                continue
            result = self.control.clear(ship)
            if not (result.ok or result.removed or result.reason == "pilot_lost"):
                self.not_cleared(ship, result)          # off the station, or to an anchorage
```

## 2. How it fits together

```
          the engine (physics, rules, resources)                   the strategy (decisions)
  ┌──────────────────────────────────────────────────┐        ┌───────────────────────────────┐
  │ a ship asks before a voyage ── vts.request ───────┼──────► │ on_request(ship)              │
  │ every 15 min ─────────────────── vts.plan ────────┼──────► │ on_tick(now)                  │
  │ a choice to make (berth, chamber, tugs, ...) ─────┼──────► │ choose_* / assign_* hooks     │
  │                                                   │ ◄──────┼─ control.clear / set_speed / …│
  │ every order checked: refused → Result(ok=False)   │ ◄──────┼─ view.* (read only)           │
  └──────────────────────────────────────────────────┘        └───────────────────────────────┘
```

A strategy is given three things before the run starts (`Strategy.bind`, then `start()`):

- `self.view`: read-only queries about the port now (`View`, `ShipView`).
- `self.control`: orders to the engine (`Control`). Each order is checked first; one that is not allowed changes nothing, returns `Result(ok=False, reason=...)` and is logged as a `vts_rejected` event.
- hooks: methods of `Strategy` the engine calls when it has a choice. Each is offered the options and the engine's default. Returning `None` keeps the default; returning something that is not on offer is refused (the default is used and the refusal logged).

Exceptions in a strategy are not caught: a broken strategy stops the run with its traceback.

## 3. Clearance: every ship asks

Every ship in the area asks the VTS before every voyage and sails only when the strategy has cleared it. `on_request(ship)` is called the moment it asks; the strategy may clear it at once or leave it for `on_tick`, the planning round every 15 minutes.

| Kind (`ShipView.request_kind`) | When | Who |
| --- | --- | --- |
| `go` | an arrival at the pilot station or at anchor, a ship entering the area at a source on the river or a canal, a ship at the end of a stay in a port | all ships |
| `unmoor` | ready to leave its berth (handling or dwell done) | all ships |
| `hop` | an inland craft moving on to its next call in the port | inland craft |
| `resume` | an inland craft weighing anchor after a stop on its way | inland craft |

**The checks of `control.clear(ship)`.** A ship that needs a pilot is cleared when it passes, in this order: route (one exists for its draught, size and locks, at some tide), weather (the gates of regs §9), tide (the whole route deep enough leaving now and 60 minutes later; the arrival windows at CP), pilots (free for the first stretch, bookable for the later ones; a pilot boat for a boarding at sea), destination (quay room at its terminal or a free berth). MODEL.md §9 gives them in full. A ship without a pilot (inland craft, small sea-going ships) is cleared when its route and destination exist: its master keeps to the tide and the weather, and under way the mesh still stops it where the water is too shallow.

**On clearance** the engine reserves the destination, books and takes the pilots (`book_ahead=False`: only the first stretch's), orders a ULCV's lock chamber, and the ship boards, unmoors or sails. **A ship that fails** keeps its request; `Result.reason` names the first check it failed (`no_route`, `destination`, `weather`, `tide`, `pilot`). A voyage that cannot be made at any tide removes the ship (`Result.removed`). `pilot_lost` means the ship was cleared but a pilot booked for it went to another ship in the same round: it is back in the queue, in its place.

**What to do with a ship that is not cleared** is the strategy's decision: leave it waiting where it is (a departure at its berth, an arrival off the pilot station), `control.wait_at_sea(ship, max_min)` (an arrival waits off the station, counted in the area but not at anchor), `control.send_to_anchorage(ship)`, or `control.recheck(ship, at)` to be asked again at a set time.

A ship left waiting that does not need a pilot is put in the state `wait_clearance` where it lies (at its berth, at its anchorage, at a port), so it does not move on by itself.

## 4. Hooks

| Hook | Lever | Offered | Default | Refused when |
| --- | --- | --- | --- | --- |
| `on_request(ship)` | clearance | a ship that asked, or whose recheck came due | (the baseline: ships without a pilot cleared at once) | |
| `on_tick(now)` | clearance | every 15 min | (the baseline: first come first served, §6) | |
| `arrival_delay(ship, default_min)` | arrival_time | a ship at the edge of the area | the virtual arrival of container ships with a berth time | below 0 or over 48 h |
| `choose_berth(ship, options, default)` | berth | free berths of its zone that take it | drawn by the AIS calls at each berth | not in options |
| `choose_quay_position(ship, terminal, options, default)` | quay_position | free, suitable stretches of quay at its planned arrival | best fit | the hull does not lie inside one |
| `anchorage_order(ship, options)` | anchorage | anchorages it may use with room, sea anchorages first then nearest | that order | a name not offered; leaving some out is allowed (an empty list keeps the ship waiting) |
| `exit_order(ship, options)` | exit | the sea exits | its drawn exit first | a name not offered; exits left out are tried after (never no way out) |
| `avoid_locks(ship, default)` | lock_route | the locks it may keep off | drawn once by the AIS shares of the twin locks and lock complexes | an unknown lock |
| `assign_pilots(ship, zone, n, free, default)` | pilots | free pilots of the zone | its own booked pilots first | not n distinct ids from free |
| `assign_tugs(ship, n, free, default)` | tugs | free tugs, nearest first | the n nearest | not n distinct ids from free |
| `choose_chamber(ship, lock, options, default)` | lock_chamber | chambers it fits at this water | fill a chamber before starting another | not in options |
| `lock_priority(ship, lock, default)` | lock_priority | its priority in the lock's queues | 2 tide-dependent, 3 sea-going, 4 inland | not 1 to 4 |
| `keep_lock_open(lock, chamber, default)` | lockage | an open chamber with nothing to load or unload now | wait a little for ships coming | kept open against the default for over 30 min |

Notes:

- **Defaults are computed first, in every case.** A draw the engine makes for a choice (a berth, the locks a ship keeps off) is made whatever the strategy then decides, so every strategy sees the same ships make the same draws, and only the decisions differ.
- `avoid_locks` is a cost on the routes (100 km of route a lock, fast_graph.LITTLE_USED_LOCK_PENALTY_M), not a ban: a ship that cannot go another way still passes the lock. `control.set_avoid_locks(ship, names)` changes it later, for the ship's next route.
- `lock_priority` 1 is "ordered ahead". Priorities 1 to 3 keep a lockage with the ship in it from being held (locks.HOLD_FREE_PRIORITY), and 1 and 2 keep the lock from waiting to fill up.
- `keep_lock_open(...) = False` closes the gates at once: the lockage starts with the ships inside, or the chamber crosses empty to fetch the ships on the other side. A ship called and still sailing in then waits for the next lockage. The random holds of a lock (faults, shift changes, MODEL.md §14) still happen.
- An overridden hook makes the engine build its options even when the hook returns `None`; leave out the hooks you don't use.

## 5. Orders (`self.control`)

| Order | What it does | Refused when |
| --- | --- | --- |
| `clear(ship, book_ahead=True)` | clear the ship if it passes the checks (§3) | not waiting; under way to its anchorage; lying out the anchor stay it entered with |
| `check(ship)` | the checks without clearing: `Result(ok, reason, route)`. It chooses the ship's destination for this round, as clear() does, but reserves nothing | as clear() |
| `recheck(ship, at)` | call `on_request` for the ship again at minute `at` (the next step at the earliest) | not waiting |
| `wait_at_sea(ship, max_min)` | an arrival waits off the pilot station, for up to max_min from when it first did; `ok` False once that is over | not an arrival waiting at the station |
| `send_to_anchorage(ship)` | to an anchorage, in the order of `anchorage_order`; `ok` False if none has room or can be reached (it waits where it is) | as wait_at_sea() |
| `set_speed(ship, kn)` / `clear_speed(ship)` | a speed through the water from 3 kn to the ship's own maximum (`ShipView.max_speed_kn`); speed limits and the current still apply on top. It holds through locks until the voyage ends (berth, anchorage, pilot station, port, exit) | out of that range |
| `set_rank(ship, rank)` | right of way under way (after distress and the regulated stretches): lower goes first. The baseline gives each cleared pilot ship the next number; ships without a pilot rank last | not an integer ≥ 0 |
| `set_avoid_locks(ship, names)` | the locks its routes keep off from its next route | an unknown lock |
| `restrict(kind, stretch=... or cells=..., direction, who, start, until)` | a restriction on a stretch of water (below); `Result.value` is its id | a bad kind, stretch, cell, direction, filter or time |
| `lift(id)` | end a restriction now | an unknown id |
| `note(ship, event, **extra)` | write an event in the ship's log (events.csv) to record a decision; ship `None`: a run-level event | |

**Restrictions.** A restriction keeps the ships it applies to from entering its cells while it is in force:

- `closed`: no entry;
- `one_way`: no entry against `direction` (`vts_api.UP`, inland and up the river; `vts_api.DOWN`, towards the sea);
- `no_meet`: no entry while a ship it applies to is inside coming the other way.

A ship already inside carries on. `who` filters the ships: `min_loa`, `min_beam`, `min_draught`, `classes`, `sea_going`, `needs_pilot` (empty: every ship). The stretch is a regulated stretch of regs §6 by name (`view.stretches()`) or a set of cell ids. It lasts at most 24 h from now and can be renewed. Directions are known on the river and the estuary; in the docks only `closed` works. A restriction is an order: there is no release valve, and a ship held by one waits until it ends (`hold_vts_restriction` in its log).

## 6. The view (`self.view`)

- **Ships:** `requests()` (waiting ships, in the order they asked), `ships()` (all in the area), `ship(id)`, `at_sea()` (ships held at sea and the minute they will enter), `default_priority(ship)` (the baseline's order).
- **A ship** (`ShipView`): what it is (`cls`, `loa`, `beam`, `draught`, `teu`, `dg`, `needs_pilot`, `tide_dependent`, `ulcv`, `distress`), where it is and goes (`state`, `departing`, `terminal`, `destination`, `exit`, `berth`, `anchorage`, `lock`, `node`, `position`, `target`, `remaining_m`), its request (`waiting`, `request_t`, `request_kind`, `wait_reason`, `at_station`, `ready`, `waited_min`), a container ship's `scheduled_berth_min`, its speeds (`max_speed_kn(leg)`, `planning_speed_kn(leg)`, `ordered_speed_kn`), `rank`, `tugs_needed()`, `pilots_needed(zone)`.
- **Resources:** `pilots_free(zone)`, `pilots_total(zone)`, `pilot_boats_free()`, `tugs()`, `locks()` (each chamber: state, side, size, the ships inside and queued at each side), `anchorages()`, `terminals()`, `terminal_free(name, at)`, `berth_holder(id)`, `zone_berths(zone)`.
- **Water and time:** `now`, `step_min` (5), `round_min` (15), `travel_minutes(ship, route)` (planning speed, speed limits and locks, the clock of the tide check), `tide_ok(ship, route, start)`, `high_waters()`, `water_level(node, minute)`, `weather(minute)`, `stretches()`, `restrictions()`.
- **Randomness:** `rng`, the strategy's own random stream from the seed. Draws from it move nothing else in the model.

**What a strategy may know.** The view shows the port as a VTS sees it: the ships in the area and what they asked for, the resources, the tide (forecast exactly, as it is in practice) and the weather now. It does not show a ship's hidden speed spread (`max_speed_kn` is the ship's own service speed, as a ship reports it), its future draws, or ships that have not yet reached the area (except those a strategy itself holds at sea). Python cannot enforce this: a strategy can reach the engine through private attributes (`view._sim`). Don't; a comparison is only fair when every strategy plays by the same information.

## 7. What no strategy can change

The tide, surge, depths and currents; under-keel clearance; the weather gates; ship sizes and the rules that follow from them (pilots needed, tugs needed, ULCV rules); lockage, mooring and handling times and the random holds of the locks; collision avoidance, the encounter and spacing rules on the mesh and their release valves; the generator's arrivals; the container schedule's berth times (a strategy can delay an arrival but not move the window it was planned for). Everything a strategy orders is checked against these, so no strategy can make the model unsafe or physically impossible.

Not yet levers (they stay with the engine): the pilot station a ship boards at (Wandelaar or Steenbank), the ULCV fallback terminal, boatmen (identical crews), moving a ship to another chamber when one opens at its side (locks.py, the lock planner's rule), and announced arrivals (a strategy sees a ship only when it reaches the edge of the area).

## 8. Authority tiers

Each strategy declares the levers it uses (`levers`, from `vts_api.LEVERS`); the run's summary records them with the hooks it overrides. Grouping results by tier separates what a better algorithm gains from what more power gains.

| Tier | Levers | Counterpart |
| --- | --- | --- |
| 0 | the baseline | first come first served |
| 1 | clearance, arrival_time, anchorage, rank, speed (advice under way) | a river VTS |
| 2 | tier 1 + pilots, tugs, lock_chamber, lock_priority, lockage, lock_route, exit | the VTS with the pilotage service, the lock planners and the harbour master |
| 3 | tier 2 + restriction, berth, quay_position | a central planner of river space and berths: an upper bound |

## 9. Output

- `summary.json` → `vts`: the strategy's name, description, levers, options and overridden hooks; ships cleared (with and without a pilot); refused orders and choices by lever (`rejected`); choices made other than the default by lever (`overrides`); restrictions made.
- `events.csv`: `vts_request`, `vts_hold` (the first failed check, when it changes), `vts_cleared`, `waits_at_sea`, `vts_rejected` (lever, reason, ship), `vts_restriction` / `vts_restriction_lifted`, `hold_vts_restriction`, and whatever the strategy writes with `control.note`.
- `replicate.py`: the columns `vts.cleared`, `vts.cleared_without_pilot`, `vts.restrictions_made`, `vts.rejected.<lever>`, `vts.overrides.<lever>`, with their confidence intervals like every other result.
- The time series' `vts_requests` counts every ship waiting for clearance, with or without a pilot.

## 10. The strategies in the repository

- `baseline`: the first-come-first-served VTS the model was calibrated with (MODEL.md §9). Pilot ships are cleared in the round in order of (distress, tide-dependent, request time); an arrival that is not cleared waits off the station (a container ship with a berth time waiting for its quay or tide, up to 18 h) or goes to an anchorage; ships without a pilot are cleared the moment they ask and, if they cannot go, tried again after a back-off of 30 minutes doubling to 8 hours. Every choice is left to its default.
- `container_first`: an example of three levers. The baseline, with container ships first in their priority class, ahead in right of way, and "ordered ahead" in the lock queues. Option `classes` (default `["container"]`).
- `template`: every hook written out, each doing what the baseline does.

**The baseline and the model before the API.** The baseline is written to make the same decisions, in the same order, with the same random draws, as the VTS the model had before the API (`SimpleVTS`), and ships without a pilot to start their voyages as they did. On one seed it should give the same run. This has not yet been checked with a run: before results from other strategies are compared with earlier ones, run the baseline and the commit before the API on one seed and compare their `summary.json` and `ships.csv`.

## 11. Writing a good strategy

- Start from the baseline (`class Mine(Baseline)`) and change one lever at a time; a run then shows what that lever is worth.
- Keep a ship without a pilot moving unless you mean to hold it: the baseline clears it in `on_request`. If you take that over, give every ship you leave waiting a `recheck` or clear it in `on_tick`, or it waits for good.
- A ship you do not clear stays in the queue: nothing times it out. Look at `waited_min`.
- `control.check` and `control.clear` choose a destination each time they run (the berth the route goes to); calling them for every ship every round is what the baseline does, and is fine.
- Planning ahead: `view.travel_minutes` and `view.tide_ok(ship, route, start)` give when a ship would be where on its route and whether the water is there then; `view.high_waters()` the windows.
- Record decisions with `control.note`, so a run can be read back.
