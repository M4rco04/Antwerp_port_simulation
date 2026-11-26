# Three strategies for running the whole port: local look-ahead, chain planning, equilibrium guidance

Status: **proposal, nothing implemented.** Built on the five papers in `docs/strategies/` (§1), on what the runs
show about where the time goes (§2: runs `0043` and replication `0042`), and on the levers of the strategy API
(`docs/VTS_API.md`). It extends `vts_strategies_feasible.md`: the lock look-ahead (L), plan-keyed clearance (A1)
and the evolved priority rule become parts of the strategies below (§8).

Each strategy covers the three things the port has to manage: **routing** (which lock, complex, anchorage, berth
and quay; when and how fast), **resource allocation** (pilots, pilot boats, quay, chambers: who gets them first)
and **lock operation** (when a chamber closes, which chamber a ship takes, who goes first). The three differ in
*how* they decide, not in what they touch:

| | **S1 Local look-ahead** | **S2 Chain planning** | **S3 Equilibrium guidance** |
|---|---|---|---|
| Paradigm | Decentralised rules, each resource on its own | Central plan with time slots, re-planned | Approximate Nash equilibrium of the ships' guidance game |
| From the reading | VTS 1 (loosely coupled), with the foresight it lacks | VTS 3 (chain planning, "aviation-like" slots), with buffers | PULSE and its simulator: polymatrix games, replicator dynamics |
| Horizon | Now plus at most ~1 h | 6 h (12 h with announcements) | To the ship's next shared resource, every 15 min |
| Routing | Twin lock / complex with the least expected delay; wait at sea or anchor by expected wait; just-in-time (JIT) speed to locks | Lock, complex, anchorage, berth and quay taken from the plan | Lock, complex, time and speed are each ship's strategies in the game |
| Resource allocation | Clearance by a priority index, with small reserves of pilots and boats | Reservation tables for pilots, boats, chambers and quay | Pairwise contention payoffs; the VTS tunes how much each ship internalises |
| Lock operation | Wait only for a ship really coming; fill when busy; earliest-entry chamber | Lockages planned (members, chamber, time) | Lockage membership emerges from the ships' equilibrium choices |
| Fuel | JIT speeds to locks | JIT along the plan, entry windows at sea | Fuel is part of every ship's payoff |
| Authority tier (VTS_API §8) | 2 | 3, plus a tier-2 variant | 2 (same levers as S1) |
| Information | `view` only | `view`; a variant adds announced arrivals | `view` only |
| Build effort (rough) | ~1 week | ~3 weeks, plus an API extension for the variant | ~2 weeks |
| Main risk | Myopia: no coordination between resources | Brittleness and model mismatch | Approximate payoffs; convergence of the solver |

S1 and S3 use the same levers, so comparing them isolates *rules against equilibrium*. S2 at tier 3 against its
tier-2 variant separates *more power* from *a better algorithm*. S2 with and without announcements separates
*more information* from both.

---

## 1. What the reading brings, and what follows for the design

| Paper | What it shows | Design decision taken here |
|---|---|---|
| **Praetorius, Hollnagel, Dahlman (2015)**, VTS and resilience (FRAM) | Two working VTS archetypes. **VTS 1**: information service only, one operator, feedback control, no notice of a ship before it crosses the reporting line; flexible, but weak at anticipating. **VTS 3** (a tidal river entrance run jointly by two countries, bilingual, with locks; it matches the Scheldt, though the paper does not name it): a traffic planner (senior VTSO + pilot) makes sailing plans for deep-draught ships, including meeting positions and tidal windows, from up to two days ahead, with notices 12 h ahead and confirmations 6 h ahead (in VTS 1 only the other services get notice: pilots 5 h, tugs and port 24 h). It is "almost aviation-like … with clearances and time slots", anticipates well, but is **stiff**: a disruption in one or two functions propagates, e.g. "multiple vessels missing their tidal windows creating future congestions". A VTS adds value by *shaping preconditions* (buffers of time and room) and *creating foresight* (synchronising ships and services). Individual goals ("be the first vessel to pick up a pilot") can work against the system goal. | The two archetypes are the axis between **S1** and **S2**. S2 keeps buffers, a frozen near-term plan and a degraded mode that falls back to S1. Every strategy is tested with **disruptions** and judged on **recovery**, not only on means (§7). The notice horizons parametrise S2's announcement variant. The individual/system conflict is what **S3** measures (price of anarchy, regret). |
| **Guo et al. (2022)**, DNV VERDE: fuel from AIS with physics + ML | Resistance-based power (Holtrop–Mennen, fouling, waves, wind) beats the cubic rule. The speed exponent that the cubic rule fixes at 3 ranges **1.5 to 4.8** across ship types. The cubic rule ignores draught (ballast) and depends on unreliable design speeds. Weather adds 7–18 % at sea. Random-forest emulators make the physics fast enough for whole fleets. | Every speed decision (JIT in S1–S3) depends on the exponent, so rankings are re-checked at exponents 2.5 and 3.5 (§9, P3). In-loop fuel estimates use cheap functions or tables, the emulator idea, not the full physics. |
| **Kim et al. (2023)**, MariTEAM: resistance and power for the global fleet | Chooses a resistance method per ship by applicability (Holtrop–Mennen, Hollenbach, Guldhammer–Harvald, Oortmerssen); wetted surface and propeller from draught. Auxiliaries run a constant hotel load (5 % of MCR above 10 MW, else 2.5 % + 250 kW), whatever the ship does. Against EU MRV: median error under 3 %, semi-interquartile range 14 %. About 0.4 CPU-hours per ship: too slow inside a simulation loop. | Waiting is not free in fuel: auxiliaries and boilers burn at anchor. The fuel–time trade-off is therefore explicit in S1's speed floors, S2's speed choice and S3's payoffs. Strategies are compared on fleet totals over the same seeds, not on single ships, whose error is larger. |
| **Grgičević (2024)**, multi-agent maritime traffic simulator | A VTS as a centralised game-theoretic model predictive controller: each vessel has a small strategy set (speed and heading setpoints); a reward oracle scores efficiency against collision, grounding and rule compliance; repeated polymatrix games are solved by evolutionary dynamics; the equilibrium is broadcast as advice every δ, predicted over Δ. | S3's cycle: δ = the 15-min planning round, Δ = the time to a ship's next shared resource. Strategies are time, speed and route choices, not headings, because collision avoidance is fixed in our engine (VTS_API §7). |
| **Grgičević & Coates (2026)**, PULSE | Pure Nash equilibria (PNE) of polymatrix "guidance games" whose payoffs are bounded to [0, 1] as u = k₂·u_o − k₁·u_s (internal preference against externalities). The solver uses **random-edge replicator dynamics**: one two-player game at a time, gossip-like. For a fixed number of edge updates its solve time does not grow with the number of players; building the game does, and dominates. Uniform initial strategies converge consistently. A strategy is picked once it holds more than 50 % of the mass. Early time-outs can return a non-equilibrium. The games resemble congestion games with individual preferences; the paper compares social cost with a worst case. | S3's solver, its payoff form and normalisation, and its checks: a regret test of the answer, and a fallback when a player has not converged. The interaction graph is sparse (only ships that share a resource), not complete as in PULSE. The congestion-game structure is what makes a PNE likely to exist. |

Not covered by the reading, and taken from elsewhere: lock scheduling (Passchyn et al. 2016; Verstichel et al.
2014, already in the team's documents), batch-service queues (threshold rules, §4.3) and berth allocation (§5).

**Correction to `vts_strategies_feasible.md`.** That review said no fuel model existed. One exists on `origin/main`
(`src/sim/emissions.py`, MODEL.md §17.1, validated against EU MRV); it was only missing from this working copy.
The review is corrected. All three strategies use that module for fuel, both in deciding and in evaluating (§3).

---

## 2. What the simulator says

### 2.1 Where the time and the contention are

| Resource | Loaded, ×1.25 (replication `0042`, seed 401) | Stress, ×1.75 background (run `0043`) |
|---|---|---|
| Waiting ship-hours after warm-up, by class (clearance, anchor, lock queue, pilot) | inland 4 400, tankers 2 100, bulk 930, containers 770 (9 measured days) | inland 29 000, tankers 6 600, bulk 3 300, containers 1 150 (15 measured days: the run stopped at day 29.9) |
| Lock queues (inland craft) | 1.4–1.5 h mean per craft | **Kreekrak** 5.2 h mean (p90 12.2 h): 22 500 of ~35 000 lock-queue ship-hours. **Van Cauwelaert** 2.0 h next to **Boudewijn** 0.64 h (its twin; it takes 4 in 5 of the complex's inland craft) |
| Lockage fill | – | Kreekrak 3.0 ships per lockage, never empty. Hansweert and Terneuzen 17–24 % of lockages empty |
| Pilot boats (8) | all busy 10 % of the time | all busy 27 % |
| River pilots (51) | never short | 49 or more busy 16 % of the time |
| Container berth windows | late > 2 h: 33 %; > 12 h: 15 %; mean 7.2 h | late > 2 h: 42 % |
| Anchorages | 13 "anchorage full" | 58 "anchorage full", 20 "no anchorage" |
| Why clearance was refused | – | pilot 930 ships, destination (quay) 502, tide 102 |

The loaded case is the team's "x1.25" set-up (containers `nhpp` at 1.25 and background traffic at 1.25). Kreekrak's
saturation at ×1.75 may come from scaling all inland traffic evenly. So ×1.25 is the **main loaded scenario**, and
×1.75 is a **stress test**. Tugs (at most 16 of 42 busy) and boatmen are never binding, so all three strategies
leave them at the engine's default.

### 2.2 What can be changed

| Domain | Levers (VTS_API §4–5) | Fixed |
|---|---|---|
| Routing | Twin locks Zandvliet/Berendrecht and Boudewijn/Van Cauwelaert (all ships); lock complex per dock system for sea-going ships (right bank: Zandvliet–Berendrecht or Boudewijn–Van Cauwelaert; left bank: Kieldrecht or Kallo) via `avoid_locks` / `set_avoid_locks`; the three sea exits; anchorage order; berth in a zone and quay position (tier 3); speed (3 kn to the ship's maximum); right of way (`set_rank`); one-way, no-meet or closed stretches (tier 3); time (clearance, `arrival_delay` ≤ 48 h) | The path on the mesh (lanes); the lock lever covers only the twins and complexes, so the canal locks **Kreekrak, Hansweert and Terneuzen are not choices**; the pilot station |
| Resources | Clearance order and timing (this decides who gets pilots, boats and quay); which pilots and tugs; chamber; lock priority 1–4 | Pool sizes; pilot-boat use (follows clearance); bookings logic |
| Locks | `keep_lock_open` (at most 30 min against the default), `choose_chamber`, `lock_priority` | Lockage times, packing, random holds, ULCV exclusive use |

### 2.3 What a strategy may know

Only `view`: ships in the area and what they asked, resources, the exact tide forecast, the weather now. **No
announced arrivals** (the reading's VTS 3 works with 12 h and 6 h notices) and no departure-ready estimates. A
plan can therefore only cover ships already in the area, unless the API is extended (§5.6).

---

## 3. Shared building blocks (build once, use in all three)

| Block | What it does | How it is checked |
|---|---|---|
| **B1 Lock-wait estimator** | Expected entry time for a ship reaching lock L, side s, at time t, per chamber: time to the next opening at that side, the ships queued ahead that pack before it (chamber size is now in `view.locks()`), one cycle T_c per lockage missed. T_c per chamber: median `closing → open` from a baseline run's `events.csv` | Predicted against actual waits on a baseline run's events; target median absolute error < 20 min at ×1.25 |
| **B2 ETA estimator** | Minutes to the next lock, pilot change or berth: `remaining_m` / speed of the leg, or `view.travel_minutes` on the ship's route (cached per voyage) | Same, against `lock_queue` / `mooring` event times |
| **B3 Resource forecast** | Free river and dock pilots and free pilot boats over the next 2 h, from counts now and the zones' job times (sea 150 + 120 min, river 180 + 90, dock 60 + 30, boat 30) | Against the time series of a baseline run |
| **B4 Fuel oracle** | Fuel per minute of a ship sailing at v or waiting, from the emissions module's own functions (`admiralty_kw`, `bolt_kw`, auxiliaries by phase, SFC at load) on the ship's public attributes | The **same model decides and evaluates**: no strategy can win by exploiting a different fuel model |
| **B5 Disruption wrapper** | Wraps any strategy, delegates every decision to it, and injects the same scheduled restriction in every run (a lock's approach `closed` for 6 h, a regulated stretch `closed` for 4 h). Disruptions without engine changes, identical for all strategies | One run per disruption against the same seed undisturbed |
| **B6 Metrics** | `vts_strategies_feasible.md` §4, plus fuel by activity from the emissions summary, lock passage times against the AIS, resilience metrics (§7) | Unit tests on small hand-made files |

B1–B3 are the riskiest part of all three strategies: a rule, plan or game built on wrong predictions is wrong.
Validating them first de-risks everything after.

---

## 4. Strategy 1: local look-ahead control ("VTS 1, done well")

**Idea.** Keep the loose coupling that makes VTS 1 flexible and robust, and add the foresight it lacks, from
what can be seen now and in the next hour. Every resource decides on its own with a simple, state-dependent rule.
There is no plan and no reservation beyond what the engine already makes. `class LocalLookahead(Baseline)`,
`levers = ("clearance", "anchorage", "speed", "lock_route", "lock_chamber", "lock_priority", "lockage")`.

### 4.1 Routing

- **Twin lock and complex by expected delay.** Before a ship's voyage (in `on_request` for ships without a pilot,
  in `on_tick` before `clear` for pilot ships), for each alternative compute `D = B1 wait + extra travel`; the
  extra travel comes from a table per (origin zone, destination zone, lock) measured on a baseline run. Call
  `set_avoid_locks` for the best one when it beats the drawn default by more than 15 min (hysteresis, so ships do
  not oscillate). Size limits stay with the engine (Berendrecht for B ≥ 43 m). Target: the Van Cauwelaert /
  Boudewijn imbalance.
- **Wait at sea or anchor, by expected wait.** For an arrival that is not cleared, estimate its wait from its hold
  reason: `tide` → the next window by scanning `tide_ok`; `destination` → scanning `terminal_free` forward in
  30-min steps; `pilot` → B3. Under 2 h → `wait_at_sea`; otherwise a sea anchorage first (the default). This
  keeps river anchorages free (the 58 "anchorage full" under stress).

### 4.2 Resource allocation

- **Clearance by a priority index.** Within the baseline's classes (distress, tide-dependent, others), order by
  `index = a·waited_h + b·urgency − c·pilot_hours`. Here *urgency* is a container ship's lateness against its berth
  window, and *pilot_hours* is the pilot time the voyage asks for. The last term is shortest-job-first: when
  pilots are short, it is the one way a reordering lowers *total* waiting instead of moving it. With `b = c = 0`
  the order is the baseline's.
- **Small reserves.** When free river pilots ≤ 2 or free boats ≤ 1, and `view.high_waters()` shows a window within
  90 min that a waiting tide-dependent ship needs, defer other non-urgent ships by one round. Ships on a tide
  cannot wait; most others can.
- Tugs, berths and quay: engine defaults (not binding, or tier 3).

### 4.3 Lock operation

- **Wait only for a ship that is really coming** (`keep_lock_open`): the rule of `vts_strategies_feasible.md` §3.
  Keep a chamber open iff, for some ship j queued on its side within h = 30 min (ETA from B2), `w_j · T_c >
  U_in · eta_j`, where U_in is the cost per minute of the ships inside and on the far side. Never hold a lockage
  with a tide-dependent ship or an ULCV in it.
- **Fill when busy.** When the queue on a side, including ships within h, holds more than one chamber-load, do not
  close below full while a queued ship that fits is sailing in. Batch-service queues are best run by such
  thresholds (Deb & Serfozo 1973): full lockages when busy raise capacity, quick lockages when quiet cut waiting.
- **Earliest-entry chamber** (`choose_chamber`, at Terneuzen, Kreekrak and Hansweert): the chamber with the
  earliest B1 entry for this ship; ties go to the default fill rule.
- **Priority**: the default, with 1 ("ordered ahead") for a ship whose tide window would close before its expected
  entry.

### 4.4 Speed and fuel

- **JIT to locks.** A ship sailing to a lock whose B1 wait exceeds 20 min gets `set_speed` to arrive about 10 min
  before its expected entry. The floor is max(0.6 × planning speed, 4 kn): low-load fuel use rises
  (SFC_ME(ℓ), MODEL.md §17.1), so slower is not always cheaper. The order is lifted (`clear_speed`) once the ship
  is called or in the lock. In the model an inland craft lying still burns nothing, so all its saving is in
  sailing slower, which Bolt's shallow-water resistance makes large.

### 4.5 What it should change, and what could go wrong

- *Hypotheses*: (H1) balancing halves the Van Cauwelaert excess; (H2) look-ahead with fill raises ships per
  lockage at busy locks and cuts idle waits at quiet ones (17–24 % empty lockages at Hansweert and Terneuzen); (H3)
  JIT cuts inland sailing fuel near locks without longer passages; (H4) reserves keep tide-dependent ships in their
  windows under stress.
- *Risks*: myopia (a pilot freed for a ship that then waits at a lock); balancing herds ships onto the lock that
  then fills (hence hysteresis and a fresh estimate each round); a speed order lingering after the lock, up to one
  round of 15 min.
- *Acceptance*: all switches off gives the baseline's `summary.json` on one seed; each component is run alone
  first (one lever at a time, VTS_API §11); no class's p95 waiting worse by more than 10 %; no rise in
  `vts.rejected`.

---

## 5. Strategy 2: rolling-horizon chain planning ("VTS 3, with buffers")

**Idea.** Plan ahead like the reading's VTS 3: every ship gets a chain of time slots across the resources it will
use, so services are synchronised before the ship moves. Then guard against VTS 3's weakness, stiffness, with
buffers, a frozen near-term plan and a degraded mode. `class ChainPlanner(Baseline)`, tier 3: the S1 levers plus
`berth`, `quay_position` and `restriction`. A tier-2 variant (no berth, quay or restriction) is run as well.

### 5.1 The plan

For each pilot ship in the area or held at sea, and each inland craft within reach of a lock, a chain of slots:

`clearance t0 → pilot zone z1 [t0, t1] (+ pilot boat at t0 if boarding at sea) → lock L, chamber c, lockage k at t2
→ pilot zone z2 … → quay stretch [s0, s0 + loa] × [t3, t4], or berth, or exit`

| Resource | Capacity model |
|---|---|
| Pilots per zone | Count per 15-min bin; each job holds a pilot for the zone's time on board plus return (as the engine books, MODEL.md §9) |
| Pilot boats | 8; 30 min per boarding or landing |
| Lock chambers | A timeline of lockages per chamber: side, start, members (packed with the chamber size), duration from the lock's entry, gate, levelling (water levels from `view.water_level`) and exit times |
| Quay | Time × quay metre per container terminal, on top of `view.terminal_free`; berths per zone |
| Tide | `view.tide_ok(ship, route, start)` for the planned start; the arrival windows at CP stay with the engine |
| Regulated stretches | Timing that avoids banned meetings (ULCV and gas tankers, Sardijngeul) |

### 5.2 Building it

Every round, insert new or changed ships; every hour, re-plan everything. Ships are taken in priority order
(distress; tide-dependent by window end; container ships by berth time; the others by earliest possible start).
For each ship, scan start times in 15-min steps up to the horizon (H = 6 h) for the first chain that fits every
table *with buffers* (lock 10 min, pilot 15 min, quay 30 min), then reserve it. This is sequential slot reservation
in space and time, like cooperative path planning with a reservation table. It is cheap (about 10⁵ table look-ups
per full re-plan) and explainable.

### 5.3 Carrying it out

| Plan item | Order |
|---|---|
| Start t0 | `clear` at t0 (if the engine's checks pass), else `recheck` at t0 |
| Arrival at sea | `arrival_delay` to the planned entry: entry windows for every sea-going class (A2 of the earlier proposal); with fuel accounted on the approach leg (§9, P4) |
| Slack before a slot | `set_speed` to arrive at the slot minus its buffer (same floor as S1) |
| Lock slot | `set_avoid_locks` (planned lock), `choose_chamber` (planned chamber), `keep_lock_open` for a planned member arriving within 30 min, closing once the planned members are in |
| Quay, berth | `choose_quay_position`, `choose_berth` (planned); tier 3 |
| Long planned wait | sea anchorage; short: `wait_at_sea` |
| Deep-draught window (variant) | `restrict(one_way)` on Pas van Borssele / Nauw van Bath around high water for an inbound convoy; tested separately because it can cost outbound traffic |

### 5.4 Robustness: answering the reading's warning

- The next 30 min of the plan are frozen; later slots move only when a gain exceeds a threshold.
- A ship that misses its slot is re-inserted at its next feasible slot without bumping others of lower priority.
- **Degraded mode**: if more than 30 % of the slots in the last hour were missed (a disruption, the engine's random
  holds), switch to S1's rules for 2 h, then re-plan. This is the buffering capacity the reading finds missing in
  VTS 3.

### 5.5 What it should change, and what could go wrong

- *Hypotheses*: (H5) the container lateness tail shrinks (×1.25: 15 % more than 12 h late) through quay planning
  and synchronised pilots and boats; (H6) fewer `destination` and `pilot` holds; (H7) deep-draught ships keep their
  windows; (H8) JIT along the plan saves fuel at sea and on the river.
- *Risks*: the plan's travel times differ from the engine's (encounters, random lock holds, speed spread), and the
  buffers must absorb this; plans churn; compute (budget ≤ 2 s per full re-plan); without announcements the horizon
  only covers ships already in the area (voyages of 2–6 h), still enough for locks, pilots and quay.
- *Acceptance*: no over-booked bin in any plan; slot adherence reported (share of slots met within their buffer);
  the degraded mode switches on in the disruption runs and off afterwards; with the planner returning defaults,
  the baseline's run.

### 5.6 Variant with announced arrivals (needs an API extension)

`view.announced(horizon_min)`: ships due within the horizon with noisy ETAs, a notice 12 h ahead (σ = 60 min) and
a confirmation 6 h ahead (σ = 20 min), the horizons of the reading's VTS 3 (noise assumed); departures with a
ready estimate ±30 min (assumed). The generator draws arrivals step by step (`Generator.arrivals(t0, dt)`), so the
engine would pre-draw H hours ahead. This must be checked to keep common random numbers (the same ships in every
strategy). Results with and without the variant are reported apart: the gap is the value of information, not of
the algorithm.

---

## 6. Strategy 3: equilibrium guidance ("PULSE at the port level")

**Idea.** The VTS does not impose an optimum (S2) or follow fixed rules (S1). Each round it computes advice that is
an approximate **pure Nash equilibrium** of a game among the ships whose next decisions interact. Each ship weighs
its own fuel and lateness against the delay it causes and suffers at shared resources. Such advice is
**self-enforcing**: no ship gains by deviating on its own. That matters for a VTS whose mandate is advisory (the
reading's VTS 1 cannot enforce a denial). The VTS's policy lever is how much of its externality each ship's payoff
includes. `class EquilibriumGuidance(Baseline)`, tier 2: the same levers as S1.

### 6.1 The game, every 15-min round

- **Players**: pilot ships waiting for clearance, departures included; ships within reach of a lock (inland and
  sea-going); arrivals at the edge, only with the approach-leg fuel accounted (§9, P4).
- **Strategies** (m ≤ 9, as in PULSE): start {now, next round, in 45 min} × speed factor {1.0, 0.85, 0.7}. At a
  twin-lock or complex branch: {A, B} × {1.0, 0.85}. At a multi-chamber lock: the chambers it fits.
- **Internal preference** u_o: from B4 (fuel of the voyage at that speed plus fuel while waiting) and the value of
  time × lateness against the ship's berth window or tide window. Values of time per class are assumed parameters
  (in tonnes of fuel-equivalent an hour), varied ×0.5 and ×2.
- **Externalities** u_s, one asymmetric m × m matrix per pair of ships that share a resource within the horizon (a
  sparse graph):
  - *same lock side*: if both make the same lockage and pack together, no cost; if not, the one later in the lock's
    order waits one cycle T_c (from B1);
  - *same pilot zone or boat slot* when B3 forecasts fewer than 2 free: the later one waits for the next return;
  - *same quay stretch*: overlap delays the later one;
  - *banned meeting* on a regulated stretch: the second to enter waits.
- **Payoff**: u = k₂·u_o − k₁·u_s, normalised to [0, 1] (PULSE eq. 9); k₁ = k₂ = 0.5 to start.

### 6.2 Solving and acting

PULSE's random-edge replicator dynamics: uniform initial mixed strategies, T = 1 000 edge updates (each pair's game
updates both players), then each player's strategy with the most mass. Then a **regret check** against the full
polymatrix payoff: a player who gains more than ε = 0.02 by deviating gets a local best-response pass. A player
still not settled falls back to S1's decision. Building the game (≈ 200 edges × 81 entries of cheap arithmetic)
and solving it take well under a second per round in numpy.

Acting: start now → `clear`; later → `recheck`; speed → `set_speed`; branch → `set_avoid_locks`; chamber → the
`choose_chamber` hook; lockage → `keep_lock_open` while a player whose equilibrium includes that lockage is coming.

### 6.3 The mechanism: what the VTS chooses

Each ship's payoff adds λ × (the delay its choice imposes on others), a non-monetary toll. It plays the part of the
Vickrey bottleneck toll of the earlier arrival-time proposal (A).

- λ = 0: the **selfish equilibrium**, what the ships would settle on alone with the same information.
- λ = 1: the externalities are fully internalised. Every ship then scores a choice by the total cost it causes,
  so the game becomes close to one of common interest, whose best equilibrium is the round's social optimum. The
  dynamics may still stop at a local optimum, so λ = 1 is a near-optimal reference, not a proven optimum.
- Reported: the **price of anarchy** SC(λ = 0) / SC(λ = 1) per round and per run, and the **regret** of the
  applied advice under the ships' own selfish payoffs: how much a ship would gain by ignoring it. Varying λ traces
  the trade-off between efficiency and self-enforcement. That curve is the design result.

### 6.4 What it should change, and what could go wrong

- *Hypotheses*: (H9) better lockage composition and pilot timing than S1 at the same levers, because choices are
  coordinated across ships rather than taken one by one; (H10) an explicit fuel–time trade-off per ship; (H11) a
  measurable price of anarchy at ×1.25 and ×1.75. That says how much a port gains by moving from advice to
  traffic organisation.
- *Risks*: the payoffs are cheap predictions, and the engine may not follow them (hence B1–B3 validated first);
  guidance games are not guaranteed potential games and PULSE warns of early time-outs (hence the regret check and
  fallback); a sparse graph is a new use of PULSE (hence unit tests); values of time drive the results (hence the
  sensitivity runs).
- *Acceptance*: the solver finds a PNE in ≥ 95 % of random small games (n ≤ 4, m ≤ 4) checked by brute force; on a
  two-ship, one-lockage game it returns the known equilibrium; λ = 1 lowers the social cost against λ = 0 on
  synthetic congestion games; ε and the price of anarchy are written per round.

---

## 7. Evaluation, shared by all three

- **Scenarios**: base (×1.0), **loaded (×1.25, the main case)**, stress (×1.75).
- **Disruptions**, through B5 and on the loaded scenario: D1 Berendrecht's approach closed for 6 h on day 13;
  D2 Pas van Borssele closed for 4 h. Each is compared with the same seed undisturbed (paired).
- **Runs**: `--days 18 --warmup 11`, evaluation seeds `2001–2003` (development seeds `1001…`),
  `replicate.py --workers 3`, chained one after another.
- **Metrics**: waiting by class (mean, p95); container berth delay (mean, share > 2 h and > 12 h); lock passage
  times per lock against the AIS; ships per lockage and empty lockages; pilot and boat saturation; anchorage
  overflow (`silent`); fuel and CO₂, total and by activity, plus the approach leg; fairness by class against the
  baseline; refused orders.
- **Resilience** (from the reading's lens): during and after a disruption, the peak excess queue, the excess
  ship-hours, and the **recovery time** until the queue is within 10 % of the undisturbed run.
- **Per strategy**: S2's slot adherence and time in degraded mode; S3's regret and price of anarchy.
- **Budget**: about 70–75 min per scenario for 3 seeds. Three scenarios plus two disruptions is about 6 h per
  strategy, so about 25 h for the baseline plus three strategies, before parameter sweeps.

---

## 8. Recommendation and order

1. **B1–B6 first** (3–4 days), with the estimators validated on a baseline run. Every strategy rests on them.
2. **S1** (~1 week). Most likely to show gains quickly, at the locks under load; least risk.
3. **S3** (~2 weeks). It reuses S1's estimators and fallback. Its comparison with S1 at the same levers is the
   clearest research result (rules against equilibrium, and the price of anarchy).
4. **S2** last, reduced first: locks, pilots and boats at tier 2, then quay at tier 3, then announcements. It is
   only worth the build if S1 and S3 leave clear headroom, most likely in the container lateness tail.

How the earlier proposals fit:

- The lock look-ahead (L1/L2) is S1's lock operation.
- Plan-keyed clearance (A1) and entry windows (A2) are S2's start times and arrival delays.
- The arrival-time game and its non-monetary toll (A) are S3's mechanism (λ).
- The evolved priority rule becomes an optional tuning of S1's index weights (a small CMA-ES), after S1 works.
  Its gate still applies to S1's clearance component: if reordering does not matter, the index stays at the
  baseline's order.

---

## 9. Prerequisites and open items

- **P1 Merge `origin/main`** (the emissions module, MODEL.md §17.1, `tests/test_emissions.py`) before any run.
  The working copy has uncommitted changes, so commit or stash them first.
- **P2 Baseline check** against the model before the API (VTS_API §10): still open.
- **P3 Speed-exponent sensitivity**: `emissions.admiralty_kw` fixes the exponent at 3. Make it a constant (default 3,
  same results), so rankings can be re-checked at 2.5 and 3.5 (VERDE: 1.5–4.8 across types).
- **P4 Fuel of the approach leg** for ships held at sea (`arrival_delay`): the module does not count it (MODEL.md
  §17.1). Without it, holding ships outside the area takes their fuel out of the books (S2, S3).
- **P5 Container speeds**: the model's container ships sail faster than the AIS's (river 14.6 against 12.3 kn,
  +37 % fuel; PINNED.md). A strategy that slows them would harvest that error. Report fuel with and without
  container ships' sailing.
- **P6 Disruption wrapper** (B5): no engine change.
- **P7 Announcements API** (S2's variant only), with a check that pre-drawing keeps common random numbers.
- **P8 (optional) Warm-up snapshot** for faster development runs (`vts_strategies_feasible.md`, P0.5).

## 10. References

The five papers in this folder:

- Praetorius, G., Hollnagel, E., Dahlman, J. (2015). *Modelling Vessel Traffic Service to understand resilience in
  everyday operations.* Reliability Engineering and System Safety 141, 10–21.
- Guo, B., Liang, Q., Tvete, H. A., Brinks, H., Vanem, E. (2022). *Combined machine learning and physics-based
  models for estimating fuel consumption of cargo ships.* Ocean Engineering 255, 111435.
- Kim, Y.-R., Steen, S., Kramel, D., Muri, H., Strømman, A. H. (2023). *Modelling of ship resistance and power
  consumption for the global fleet: The MariTEAM model.* Ocean Engineering 281, 114758.
- Grgičević, L. (2024). *Multi-Agent Maritime Traffic Simulator.* Modeling, Identification and Control 45(4),
  127–136.
- Grgičević, L., Coates, E. M. (2026). *PULSE: an algorithm for multi-agent centralised high-density maritime
  traffic management based on guidance games.* Journal of Marine Science and Technology 31, 182–205.

Others cited (from memory, to verify):

- Deb, R. K., Serfozo, R. F. (1973). *Optimal control of batch service queues.* Advances in Applied Probability
  5(2), 340–361.
- Silver, D. (2005). *Cooperative pathfinding.* AIIDE 2005.
- Rosenthal, R. W. (1973). *A class of games possessing pure-strategy Nash equilibria.* International Journal of
  Game Theory 2, 65–67.
- Passchyn et al. (2016) and Verstichel et al. (2014): see `strategie_vts_A_i_L.md`.
