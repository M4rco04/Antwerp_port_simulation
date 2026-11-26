# VTS strategies: feasibility review and an implementable plan

Status: **review + plan, nothing implemented.** Reviews the two proposals on `origin/main`:
`docs/strategies/strategie_vts_A_i_L.md` (A: arrival-time game, L: dynamic lock policy) and
`docs/strategies/evolved_priority_rule.md` (learned clearance priority). Each one is checked against the code
(`src/agents/vts_api.py`, `vts.py`, `src/environment/locks.py`, `src/sim/engine.py`) and against real runs
(`results/runs/0045`, `0046`, `results/replications/0042_*`). Each is then cut down to something that can be built
with the current API and run on this machine in a reasonable time.

---

## 0. Facts that decide feasibility

| Fact | Where from | Consequence |
|---|---|---|
| **~3.6–4 min of wall time per simulated day** (216–241 s/day, `background_rate` 1.75) | `run.log` of runs 0045, 0046 | A 7-day run takes ~28 min, not the ~7 min per 5 days the evolved-priority budget assumes (about 3× off) |
| **Warm-up used in practice: 11–15 days** (default `--warmup` is 2) | `config.json` of replications 0001–0042, run 0046 | One evaluation run is ≥ 14 simulated days, **~50–55 min** |
| **Runs one at a time; `replicate.py --workers 3` is the most that has run without a memory kill** (15.6 GB RAM) | project memory, 16 Nov | No "5 parallel processes". At most 3 seeds in parallel inside one `replicate.py` |
| ~~There is no fuel or emissions model~~ **Correction (2026-11-26):** `origin/main` has one (`src/sim/emissions.py`, MODEL.md §17.1, validated against EU MRV), not yet merged into this working copy. It does not count the fuel of ships held at sea before the area | `git diff HEAD origin/main --stat` | Merge `origin/main` before experiments; use its fuel books, plus an approach-leg term for ships held at sea (§4) |
| **Where waiting actually is** (run 0046, ships after warm-up, sum of `min_wait_clearance + min_anchored + min_lock_queue + min_wait_pilot`, 15 measured days; corrected 2026-11-26, the first figures also counted time inside the lock): inland ≈ 29 000 ship-h (mostly **lock queue**, mean 4–6.5 h), tanker 6 600, bulk 3 300, **container 1 150** | `ships.csv` of run 0046 | The lock policy (L) has by far the most room to help. Clearance ordering and the arrival game touch a small share |
| **Why clearance is refused** (run 0046): `pilot` 930 ships, `destination` 502, `tide` 102, `weather` 28 | `vts_hold` events | Ordering matters only when pilots are short. A container ship's quay (`destination`) gates it whatever its place in the queue |
| Ships ask the lock **when their route is planned** (`lock.request(..., ready_at=inf)`, engine.py:1794), so the lock queue already lists ships still sailing towards it | engine.py, locks.py `summary()` | "Wait only for a ship that is really coming" (L1) can be built from `view.locks()` + `ShipView.remaining_m`, with no new information |
| The default arrival is **already JIT**: `slow_down_min` holds a container ship at sea until it berths on time | engine.py:1391 | The status quo is not FCFS racing. Strategy A's baseline has to be built on purpose (§2) |
| ~~`replicate.py` does not start: `--background-rate` declared twice~~ fixed 2026-11-26 | `py src/sim/replicate.py --help` | |

---

## 1. Verdict per proposal

| Proposal part | Verdict | Why |
|---|---|---|
| **L1** wait only for a ship really coming within h | ✅ build first | Hook exists (`keep_lock_open`), information is observable, and it acts on the largest waiting component |
| **L2** marginal rule λ̂·ū·T_c > U_in | ✅ merged into L1 as its decision rule | Becomes deterministic once the ETA of the coming ship is known (§3) |
| L3 MDP per lock | ❌ drop | State (two queues, sizes, tide, arrivals) is too large and the transitions only exist inside the simulator |
| L4 oracle | ❌ drop | Needs `view._sim` (breaks VTS_API §6). L1 with a large h is a near-oracle anyway, because en-route ships are already in the queue |
| Ship packing / "whom to admit" | ❌ not a lever | `_next_to_enter` belongs to the engine. Only `lock_priority` 1–4 and `choose_chamber` are open |
| Shapley / karma cost sharing | ❌ drop | No money and no credits in the model. At most a paragraph in the write-up |
| **A1** queue keyed by plan, not arrival | ✅ build | One sort key in `on_tick` (`scheduled_berth_min` exists in `ShipView`) |
| A0 vs A1 **ship-side equilibrium** | ⚠️ simplified | Ships do not choose in the model. Emulated by one "eagerness" parameter through `arrival_delay` and measured with a mutant design (§2), not full EGTA |
| A2 entry windows | ⚠️ optional | Possible with `arrival_delay` + a booking table. Low value at today's container volume |
| A3 window trading with karma | ❌ drop | Many runs and a mechanism the model has no hook for |
| **Evolved priority**, as specified | ❌ budget | Stage 1 ≈ 9×30×3 runs × ~50 min ≈ **670 h**, stage 2 ≈ 900 h, serial. f3 (fuel) needs the `origin/main` emissions module |
| Evolved priority, reduced | ✅ after a go/no-go gate | 4 features, one objective, ~40 candidates, warm-up snapshot (§5) |

Recommended order: **P0 prerequisites → L (lookahead lockage) → A1 (plan-keyed clearance) → evolved priority only if
the headroom gate passes.**

---

## P0. Prerequisites (shared)

1. ✅ **Fix `replicate.py`**: the duplicate `--background-rate` argument is removed (done 2026-11-26).
2. **Check the baseline against the pre-API model** (VTS_API §10, still open): one seed, compare `summary.json` and
   `ships.csv`. Every comparison below depends on the baseline being the reference.
3. ✅ **Expose chamber size in `view.locks()`** (done 2026-11-26): added `"length_m": c.length_m, "width_m": c.width_m` to
   `Lock.summary()` (locks.py:497). Static infrastructure, so fair under VTS_API §6. This is the only API change in
   the plan. L needs it to know whether a coming ship would fit.
4. **Experiment config, fixed for the whole study** (record it in each result's `config.json`):
   - two scenarios: **base** (`--background-rate 1.0`, `--containers weeks`) and **loaded** (`--background-rate 1.75`
     as in run 0046, or `--containers nhpp --container-rate 1.2`). Results are expected only under load (both
     proposals say so too),
   - `--days 18 --warmup 11` (11 days is what the Welch check gave in replications 0001–0042; re-check with
     `warmup.png` on the loaded scenario),
   - seeds: training `1001..`, evaluation `2001..`, disjoint,
   - `replicate.py --workers 3`, runs chained one after another, never two `replicate.py` at once.
   - Cost: one 3-seed comparison ≈ 18 days × 4 min ≈ **70–75 min wall**.
5. **(Optional, large saving) Warm-up snapshot.** Check whether a `Simulation` can be pickled at the end of
   warm-up and resumed with another strategy. That is a legitimate common starting state for every strategy. If it
   works, a training evaluation costs 7 days instead of 18 (~2.5× cheaper). Needed only for §5.

---

## 2. Strategy A, reworked: plan-keyed clearance + an eagerness test

### 2.1 A1, the VTS rule (`src/strategies/plan_keyed.py`)

`class PlanKeyed(Baseline)`, `levers = ("clearance", "anchorage", "arrival_time")`.

In `on_tick`, sort pilot ships by `(priority class, key_time)` in place of `(priority class, request_t)`:

- container ship with a berth window: `key_time = scheduled_berth_min − lead`, where
  `lead = view.travel_minutes(ship, control.check(ship).route)`. That is the moment it *should* leave the station to
  be on time. If `check` gives no route, fall back to `request_t`,
- every other ship: `key_time = request_t` (background ships have no plan, so they keep FCFS among themselves and
  interleave by time with the planned ships).

This way an early arrival buys no place in the queue, and a late container ship moves up. Distress and
tide-dependent ships stay ahead (class 0/1 untouched). `not_cleared` is inherited. Option `rule = "A0" | "A1"`: A0
is the baseline order, so one class serves both arms.

### 2.2 The ship side, emulated: eagerness `a`

Ships make no choices in the model. The generated entry time is treated as the **earliest** a ship could come
(full speed), and the engine's virtual-arrival delay `d0 = default_min` as the JIT choice. A ship with eagerness
`a ∈ [0, 1]` enters after

```
arrival_delay(ship, d0) = (1 − a) · d0          # a = 0: JIT (today's model), a = 1: race, no slowing
```

Only container ships with a window have `d0 > 0`, so only they play. This is a modelling assumption (the hook is a
VTS hook used here to stand for the ship's decision) and has to be stated as such in the results.

### 2.3 Measuring the incentive with mutants, without full EGTA

Full best-response iteration is too expensive. Instead, **one run gives the whole best-response curve at one
population strategy**: 70 % of container ships (chosen by a hash of `ship.id`, so the split is fixed across seeds)
play `a_pop`, and three mutant groups of 10 % play the other values of `{0, 0.5, 1}`. Per group, compute the
private cost (§4) and compare the groups inside the same run, paired across seeds.

- Grid: `a_pop ∈ {0, 0.5, 1}` × rule `{A0, A1}` × 3 seeds = **6 replicate calls ≈ 7–8 h** per scenario (overnight).
- Reading the result: under A0, if the `a = 1` mutants beat the `a = 0` population, JIT is not an equilibrium (racing
  pays). Under A1, racing should not pay. That is the proposal's claim, now testable.
- ε (largest gain from deviating) = the largest mutant-minus-population cost difference, with its paired CI.
- Expected outcome, stated up front: at ~6 container ships a day, with the quay (not the queue) gating most of
  them, the gain from racing under A0 is probably small. A null result is a valid result. Run the loaded scenario.

### 2.4 Acceptance

- With `rule=A0` and `a ≡ 0`, `plan_keyed` gives the same `summary.json` as `baseline` on one seed.
- No `vts.rejected.arrival_time` and no change in the order of class 0/1.

---

## 3. Strategy L, reworked: lookahead lockage (`src/strategies/lookahead_lock.py`)

`class LookaheadLock(Baseline)`, `levers = ("clearance", "anchorage", "lockage")`. It overrides only
`keep_lock_open` (and `start`).

### 3.1 What the default does today (L0)

When an open chamber has nothing to load or unload (locks.py `_hold_open`): it waits for a called ship sailing in
(up to 12 min, or until it is in for a sea-going ship), waits up to `BUNDLE_HOLD_MIN = 3` min from the first entry
while there is room, and waits 3 min before crossing empty. It does not look at ships that are still on their way
and not yet called.

### 3.2 The rule

On each call `keep_lock_open(lock, chamber, default)`:

1. Read `view.locks()[lock][chamber]`: `side`, `inside`, `waiting_a/b`, `length_m/width_m` (P0.3).
2. **Coming ships** C = ships in `waiting_<side>` that are not inside, with
   `eta_j = remaining_m / (speed)`, where speed is the ship's lock sail-in speed or its `planning_speed_kn`, and
   `eta_j ≤ h`. Keep only those that fit next to the ships inside (1-D check: sum of `loa + 10 m` ≤ `length_m` per
   lane of `width_m`, conservative).
3. **Cost of waiting per minute**: `U_in = Σ w_i` over ships inside plus ships waiting on the far side.
4. **Value of waiting for the first coming ship** j: it rides this lockage instead of the next one, which saves
   about `w_j · T_c`, where `T_c` is the lock's cycle time.
5. **Keep open iff** `w_j · T_c > U_in · eta_j` for some j in C (L2 with a known ETA). Otherwise close.

Parameters (options): `h` (default 30 min, the API cap `KEEP_OPEN_MAX_MIN`), class weights `w` (default 1 for all, so
the rule just counts ship-minutes), `T_c` per lock (a table measured from one baseline run: median `closing → open`
of the same chamber in `events.csv`).

### 3.3 Hard rules inside the strategy (the engine does not enforce them for this hook)

- Never return `True` when a ship inside is tide-dependent, an ULCV or exclusive (`ShipView.tide_dependent`, `.ulcv`),
  or when `default` is `False` because of one of these. In those cases return `None`.
- Return `None` (keep the default) whenever nothing is coming within h and the default would close anyway, so that
  `vts.overrides.lockage` counts only real decisions.
- Note each override with `control.note(None, "lookahead_hold", lock=..., chamber=..., eta=...)`.

### 3.4 Experiments

1. **h sweep** with `w ≡ 1`: `h ∈ {0, 10, 20, 30}` (h = 0 means "close as soon as nothing is in sight", which also
   tests whether the calibrated 3-min holds cost time) × 3 seeds × 2 scenarios = 8 replicate calls ≈ 10 h.
2. **Weights**: `w = 3` for sea-going ships against 1 for inland craft, at the best h.
3. Report per lock and per class: `lock_queue_h_mean`, `in_lock_h_mean`, lockages per day, ships per lockage,
   `v.locktime.*` against the AIS. **Fairness is reported per class, not optimised.** A rule that wins on inland
   craft by making sea-going ships wait is shown as such.

### 3.5 Caveats kept from the proposal

L0 is calibrated to AIS passage times, so gains are potential above real operators. Holds are calibrated, not
observed. Canal locks run 12–24 % slow near the gates. Compare strategies with each other, not with absolute hours.

---

## 4. Shared metrics module (`src/sim/strategy_metrics.py`, post-processing only)

One function `metrics(run_dir, warmup_min) -> dict`, reading `ships.csv` (+ `summary.json`), ships with
`spawn_min ≥ warmup`:

- **waiting** per ship = `min_wait_clearance + min_anchored + min_lock_queue + min_wait_pilot + min_to_anchorage`
  (NaN → 0), mean and p95 per class. Note: `min_anchored` includes the AIS-drawn anchor stays that ships *enter
  with* (`anchor_wait_h`), which no strategy can change. Report waiting with and without it,
- **window delay** (container ships): `max(moored_min − scheduled_berth_min, 0)`, plus the early share,
- **fuel** (corrected 2026-11-26): take the fuel, CO₂ and fuel by activity from the emissions module on
  `origin/main` (MODEL.md §17.1). Add one term it leaves out, the **approach leg of ships held at sea**: a ship
  covers a fixed distance D before the area at its design speed v0 in T0 = D / v0 (D = 24 h at v0, assumed). A
  hold d spreads over it, so v = D / (T0 + d), and its main-engine fuel follows the module's own Admiralty formula
  at that speed. Without this term, holding a ship outside the area takes its fuel out of the books. Only
  differences between strategies on the same seed are meaningful,
- **feasibility flags**: `stopped_early`, `removed_infeasible`, and the `silent` block against the baseline.

Unit tests on a tiny hand-made `ships.csv`.

---

## 5. Evolved priority, reworked: a small learned rule, behind a go/no-go gate

### 5.1 Gate: is there anything to learn? (~4 h)

Before any optimiser, run the loaded scenario, 3 seeds, with: `baseline`, `container_first`, and a deliberately
bad `reverse_fcfs` (newest request first). If the waiting difference between the best and the worst of these is
inside the paired CI, **stop**: the clearance order does not move the outcome enough to learn a rule. Write that
up as the result.

### 5.2 If the gate passes

- **Controller** as in the proposal (`EvolvedPriority(Baseline)`, key `(distress, tide_dependent, score,
  request_t)`, `theta0` = baseline), but with **4 features** that act on the real bottleneck (pilots):
  `waited_h`, `pilots_needed(first zone)` (pilot-hours asked: a shortest-job-first effect, the only way reordering
  lowers *total* waiting rather than reshuffling it), `slack_h` to the window (0 if none), `is_container`.
- **One objective**: `J = waiting_ratio + 0.5 · window_delay_ratio` (paired against the baseline on the same seed).
  Fairness and fuel are reported, not optimised. A per-class worsening above 20 % makes a candidate
  infeasible.
- **Optimiser**: CMA-ES with population 6, 6–7 generations (≈ 40 candidates), 2 seeds each, seeds rotated per
  generation. With the warm-up snapshot (P0.5) that is ≈ 40 × 7 days × 4 min ≈ 19 h (the 2 seeds run in parallel).
  Without it, ≈ 48 h. Then re-evaluate the best 3 plus the baseline on 5 evaluation seeds.
- **Dropped**: NSGA-II and the Pareto front (4 noisy objectives at 2–3 seeds yield a front of noise), racing,
  surrogates, GP and neural networks. These can be revisited only if the linear rule shows a clear gain.

### 5.3 Acceptance

`theta0` reproduces the baseline on one seed. The sphere test for the CMA-ES wrapper. A short end-to-end trial
(1 generation, 2 seeds, 3 days) writes `single.json` and `generations.csv`.

---

## 6. Budget summary (wall time, chained, `--workers 3`)

| Step | Runs | Wall |
|---|---|---|
| P0 checks (baseline equivalence, T_c table, warm-up check) | 3 | ~3 h |
| L: h sweep + weights, 2 scenarios | ~10 replicate calls | ~12 h |
| A: mutant grid, loaded scenario (+ base if interesting) | 6 (12) | ~8 h (16 h) |
| Evolved: gate | 3 | ~4 h |
| Evolved: CMA-ES + evaluation (only if the gate passes) | ~45 | ~20–50 h |

L and A fit into about three nights. Evolved priority is the expensive, uncertain part and comes last.

## 7. What changes against the original proposals, in one list

- L3, L4, packing, Shapley/karma, A3 dropped. L1 and L2 merged into one ETA-based rule.
- The A0 "race" made explicit through an eagerness parameter, because the model already does JIT. Equilibrium
  measured with mutant groups in place of best-response iteration.
- "Fuel" taken from the emissions module on `origin/main`, plus the approach leg of ships held at sea (corrected
  2026-11-26: the first version of this review said no emissions module existed; it was only missing locally).
- Evolved priority: run times corrected (~4 min/day, 11-day warm-up, ≤ 3 runs at once), a gate added, the controller
  cut to 4 features with a pilot-hours feature, a single objective, CMA-ES with ~40 candidates, NSGA-II dropped.
- One small API change (chamber size in `view.locks()`), one bug fix (`replicate.py`). No engine physics touched.
