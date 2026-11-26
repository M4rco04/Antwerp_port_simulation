# Run plan for the four port strategies

What to run, in what order, and what each step must show before the next one starts. Strategies:
`baseline` (reference), `local_lookahead` (S1), `chain_planning` (S2), `equilibrium_guidance` (S3),
`evolutionary_guidance` (S4). Design: `port_management_strategies.md`.

**Rules for every step**

- One command at a time, never two side by side (15.6 GB RAM; project memory). `replicate.py --workers 3` is the most
  that has run safely. Each command below is one line: run them in the order given, each after the previous one ends.
- Each `--label` is the run's id and folder name (`results/runs/<label>/`, `results/replications/<label>/`), so it
  must be new: a label already used is refused. No viewer is built unless `--viewer` is given (or the box is ticked
  on the setup page).
- Run from the repository root. The commands are the same in PowerShell and Git Bash.
- Single runs go through `pipeline.py` (they save `events.csv`, which the strategy diagnostics and the lock calibration
  need). Multi-seed comparisons go through `replicate.py` (confidence intervals; no `events.csv`).
- Wall times assume ~3.5–4 min per simulated day per replication, measured on the baseline. S3 and S4 may be slower;
  phase 0 measures it.

**Scenarios** (same container process in all three, so they differ only in load)

| Name | Flags |
|---|---|
| base | `--containers nhpp --container-rate 1.0 --background-rate 1.0` |
| loaded (the main case) | `--containers nhpp --container-rate 1.25 --background-rate 1.25` |
| stress | `--containers nhpp --container-rate 1.25 --background-rate 1.75` |

**Seeds**: phase 0 seed 1; phases 1–2 seed 1001 (development); phases 3–4 seeds 2001–2003 (evaluation, looked at only
once the strategies are frozen).

---

## Phase 0: smoke runs (~25–40 min)

Does each strategy run for a day without crashing, does it act (overrides in `summary.json`), and how much slower is it
than the baseline? 1 day, no warm-up, loaded scenario.

```
py src/sim/pipeline.py --label smoke-baseline --days 1 --warmup 0 --seed 1 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts baseline
py src/sim/pipeline.py --label smoke-S1 --days 1 --warmup 0 --seed 1 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts local_lookahead
py src/sim/pipeline.py --label smoke-S2 --days 1 --warmup 0 --seed 1 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts chain_planning
py src/sim/pipeline.py --label smoke-S3 --days 1 --warmup 0 --seed 1 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts equilibrium_guidance
py src/sim/pipeline.py --label smoke-S4 --days 1 --warmup 0 --seed 1 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts evolutionary_guidance
```

**Go on when:** all five finish (`status.json` "done"); each strategy shows overrides in `summary.json → vts.overrides`;
few refused orders (`vts.rejected`); S3/S4 runs have `eq_round` events in `events.csv`; no strategy takes more than
about 1.5× the baseline's wall time (`run.log`, "s per day"). A crash or a much slower strategy is fixed first.

## Phase 1: the reference run and the estimator check (~75 min)

One baseline run of the length used for evaluation, saved with its events. It checks the estimators every strategy
rests on (B1, B2): the lock cycle times in `strategies/_common.py` (`CYCLE_MIN`, priors) against the `closing → open`
times in the events, and the predicted against the actual lock waits.

```
py src/sim/pipeline.py --label ref-baseline-loaded --days 18 --warmup 11 --seed 1001 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts baseline --max-minutes 300
```

**Go on when:** the cycle times are updated from this run where they differ by more than 20 %. Lock-wait estimates
are within ~20 min (median absolute error) of the waits in the events. The ships in the area and the queues in
`timeseries.csv` level off before day 11 (else the warm-up of every later step must be longer).

## Phase 2: development runs, one seed (~5–6 h)

Each strategy over the full length on the development seed, with events, to catch behaviour that a day cannot show
(degraded mode in S2, the regret and price of anarchy in S3, the GA's gain over its seed in S4, speed orders that
linger).

```
py src/sim/pipeline.py --label dev-S1-loaded --days 18 --warmup 11 --seed 1001 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts local_lookahead --max-minutes 300
py src/sim/pipeline.py --label dev-S2-loaded --days 18 --warmup 11 --seed 1001 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts chain_planning --max-minutes 300
py src/sim/pipeline.py --label dev-S3-loaded --days 18 --warmup 11 --seed 1001 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts equilibrium_guidance --max-minutes 400
py src/sim/pipeline.py --label dev-S4-loaded --days 18 --warmup 11 --seed 1001 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts evolutionary_guidance --max-minutes 400
```

**Go on when:** against `ref-baseline-loaded` (same seed) no strategy makes any class's p95 waiting more than 10 %
worse without a reason it was designed for, `silent` (hidden shortages) is no worse, S2 spends less than a fifth of the
time in degraded mode, S3's regret stays small. Any change to a strategy after this phase means repeating its
phase-2 run, never tuning on the evaluation seeds.

**Freeze the strategies here** (commit), so phases 3–4 test fixed code.

## Phase 3: evaluation, three seeds, three scenarios (~17–20 h)

**From the setup page** (`py src/ui/app.py`, card *Evaluation*): choose the scenario, tick the strategies (the
baseline is always included), keep 3 replications from seed 2001, 3 at once, 18 days with 11 of warm-up, and start. It
runs the same `replicate.py` calls as below, one after another, and its *Compare with the baseline* button gives the
paired differences with their 95 % intervals. One evaluation per scenario. Phase 4 can be started the same way only for
strategies without options; the ablations with `--vts-option` stay on the command line.

The comparison itself: every strategy against the baseline on the same seeds (2001–2003). Loaded first (the main case),
then base, then stress.

Loaded:
```
py src/sim/replicate.py --label eval-loaded-baseline --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts baseline
py src/sim/replicate.py --label eval-loaded-S1 --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts local_lookahead
py src/sim/replicate.py --label eval-loaded-S2 --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts chain_planning
py src/sim/replicate.py --label eval-loaded-S3 --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts equilibrium_guidance
py src/sim/replicate.py --label eval-loaded-S4 --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts evolutionary_guidance
```

Base:
```
py src/sim/replicate.py --label eval-base-baseline --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.0 --background-rate 1.0 --vts baseline
py src/sim/replicate.py --label eval-base-S1 --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.0 --background-rate 1.0 --vts local_lookahead
py src/sim/replicate.py --label eval-base-S2 --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.0 --background-rate 1.0 --vts chain_planning
py src/sim/replicate.py --label eval-base-S3 --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.0 --background-rate 1.0 --vts equilibrium_guidance
py src/sim/replicate.py --label eval-base-S4 --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.0 --background-rate 1.0 --vts evolutionary_guidance
```

Stress:
```
py src/sim/replicate.py --label eval-stress-baseline --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.25 --background-rate 1.75 --vts baseline
py src/sim/replicate.py --label eval-stress-S1 --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.25 --background-rate 1.75 --vts local_lookahead
py src/sim/replicate.py --label eval-stress-S2 --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.25 --background-rate 1.75 --vts chain_planning
py src/sim/replicate.py --label eval-stress-S3 --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.25 --background-rate 1.75 --vts equilibrium_guidance
py src/sim/replicate.py --label eval-stress-S4 --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.25 --background-rate 1.75 --vts evolutionary_guidance
```

**Read out** (paired against the baseline on the same seeds): waiting by class, mean and p95; container berth delay
(share over 2 h and 12 h); lock queue time per class; fuel and CO₂, total and by activity (the emissions block);
`silent`; refused orders. If the loaded scenario shows no difference beyond the confidence intervals for any strategy,
the base runs can be skipped (they will show less).

## Phase 4: what makes the difference (~9–10 h, loaded, evaluation seeds)

Only for the strategies that phase 3 shows to work. Each line changes one thing.

S1, one component off at a time (which of them carries the gain):
```
py src/sim/replicate.py --label abl-S1-no-balance --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts local_lookahead --vts-option balance=false
py src/sim/replicate.py --label abl-S1-no-lookahead --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts local_lookahead --vts-option lookahead=false
py src/sim/replicate.py --label abl-S1-no-jit --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts local_lookahead --vts-option jit=false
```

S2 without the quay lever (tier 2 against tier 3: power against algorithm):
```
py src/sim/replicate.py --label abl-S2-tier2 --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts chain_planning --vts-option quay=false
```

S3, the toll at its two ends (selfish against fully internalised):
```
py src/sim/replicate.py --label abl-S3-lam0 --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts equilibrium_guidance --vts-option lam=0
py src/sim/replicate.py --label abl-S3-lam1 --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts equilibrium_guidance --vts-option lam=1
```

S4 without the perturbed futures (does robust scoring matter?):
```
py src/sim/replicate.py --label abl-S4-nominal --days 18 --warmup 11 --reps 3 --seed 2001 --workers 3 --containers nhpp --container-rate 1.25 --background-rate 1.25 --vts evolutionary_guidance --vts-option samples=1
```

---

## Totals and order of priority

| Phase | Commands | Wall time (est.) | Can be skipped? |
|---|---|---|---|
| 0 Smoke | 5 | 0.5 h | No |
| 1 Reference + estimators | 1 | 1.2 h | No |
| 2 Development | 4 | 5–6 h | No |
| 3 Evaluation: loaded | 5 | 6–7 h | No |
| 3 Evaluation: base, stress | 10 | 11–13 h | Base if loaded shows nothing |
| 4 Ablations | 7 | 9–10 h | Yes, if phase 3 shows no gain |
| **All** | **32** | **~34–38 h** | |

Phases 0–2 fit in one working day and a night; the loaded evaluation in a night; the rest in two more nights.

**Not in this plan yet** (code not written): the disruption runs (wrapper B5: a lock closed for 6 h, a river stretch
closed for 4 h) and the robustness check of the fuel results at speed exponents 2.5 and 3.5 (P3). They are added once
that code exists.
