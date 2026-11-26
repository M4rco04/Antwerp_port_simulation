# Antwerp Port Simulation — Plan

**Focus:** container ships in full detail. All other traffic (bulk/general cargo, tankers, inland barges, passenger) is modelled in less detail, as stochastic background traffic fitted from the AIS data. Background traffic uses the same resources as container ships (river, locks, anchorages, pilots, tugs).

References to "regs §N" point to `port_regulations_agent_rules.md`.

---

## 0. Engine and time model

- **Time-stepped agent simulation, with a fixed step Δt = 5 min.** Every step runs in this order:
  1. update the environment (tide `h(t)`, current, weather)
  2. generate new arrivals
  3. VTS planning (the full re-plan runs every 3 steps = 15 min; in between only updates)
  4. resource assignment (pilots, tugs, locks, berths)
  5. ship movement on the mesh, in two phases: proposals → conflict resolution (§5.3)
  6. conflict checks (cell occupancy, encounters)
  7. logging
- **The step matches the AIS snapshot interval (5 min).** Simulated states can be compared snapshot by snapshot with `data/ais/`.
- **Processes shorter than one step** (closing lock gates, a pilot boarding, the last metres of mooring) are kept as countdown timers in minutes on the agent. They end in the step where the timer reaches ≤ 0, so no time is lost to rounding.
- **Time horizon:** simulate 2–4 weeks (4032–8064 steps), matching the schedule window (`data/schedules/2026_Oct20-Nov22.csv`). Discard the first 2–3 days as warm-up.
- Pilots, tugs, berths and lock chambers are resources with a state and queues. Each step, a resource is either assigned or kept busy.

---

## 1. Two-level traffic model

### Level 1 — Container ships (full agents)
- Arrivals: replay of the schedule CSV, or a non-homogeneous Poisson process (NHPP) fitted to it.
- Attribute chain: TEU → LOA, beam, draught → call size → number of STS cranes → handling time.
- Berth allocation by quay length and crane density (`alokacja_przestrzenna_w_terminalach.md`).
- Tidal windows at the terminals: Deurganckdok (MPET, Antwerp Gateway), Noordzee, Europa.
- ULCV rules (≥ 350 m): 3 tugs on arrival and 2 on departure, a fallback berth, wind limits (regs §8.11, §9).
- Full VTS planning.
- **All the main outputs come from this level.**

### Level 2 — Background traffic (simplified agents)
These ships go through the same VTS and use the same river, locks, anchorages, pilots and tugs. They have **no terminal model**: time at the berth is a random dwell time.

| Class | Arrivals | Attributes | Destination | Berth time | Uses |
|---|---|---|---|---|---|
| Bulk / general cargo | NHPP λ(hour) from AIS | empirical bootstrap (LOA, B, T) | dock zone behind the locks | lognormal from AIS | pilot, lock, sometimes a tug |
| Tanker | NHPP from AIS | empirical + dangerous goods (DG) flag | petrochemical zone (tanker berths only) | lognormal | pilot, tug if > 120 m, lock, DG anchorage |
| Inland barge | NHPP, higher rate | empirical | lock / Albert Canal / through-traffic | lognormal or pass-through | river and lock capacity only (no pilot) |
| Passenger / cruise | low rate | empirical | city quays | fixed time | pilot, wind limits (regs §9) |
| Through-traffic Terneuzen/Ghent | NHPP from AIS | empirical | sink at Terneuzen | — | Western Scheldt only |

- **Empirical bootstrap:** draw whole observed ships (LOA, B, T together), so the correlations between dimensions are kept without being modelled.
- **Left out:** service and special vessels (AIS type 30s/50s: tugs, pilot boats, dredgers). Our own pilot and tug resources replace them. Dredgers could later be added as obstructions on edges. Zeebrugge traffic shares only the pilots, so it is left out too.

---

## 2. AIS processing pipeline

### Data facts (snapshot 2026-10-29 13:08Z, 752 ships; 742 snapshots so far)
| AIS group | Count | Use |
|---|---|---|
| Cargo (70–79) | 209 | containers, bulk/general cargo **and** inland barges all fall here |
| Tanker (80–89) | 141 | background traffic, with a DG flag |
| Special (30s) + service (50s) | 210 | not traffic; left out |
| Passenger (60s) | 30 | background traffic, minor |
| Unknown / other | 144 | classify by dimensions, or drop |

Problems to solve:
1. **AIS does not say which ships carry containers.** Types 70–79 cover all cargo ships. Identify containers by matching the vessel name against the schedule CSV. For ships not in the schedule, use a classifier based on beam, LOA and destination.
2. **About two thirds of the "cargo" ships are inland barges** (139 of 209 have LOA ≤ 135 m; e.g. draught 0.2 m, destination DUISBURG). They load the locks and the river, but need no pilot or tug.
3. **The AIS area also covers Zeebrugge, Vlissingen and Terneuzen.** Each ship needs a destination class: Antwerp / through-traffic to Terneuzen–Ghent / Zeebrugge.

### Steps
1. **Tracks per MMSI** from the 5-minute snapshots, with duplicates removed and gaps filled in.
2. **Events from each track:**
   - entering the area (crossing the sea boundary line)
   - anchored (`nav_status` 1, or speed < 0.5 kn inside an anchorage polygon)
   - passing a lock
   - at a berth (speed < 0.5 kn inside a polygon from `slots_cords` GeoJSON)
   - departure
3. **Classification:** container (matched to the schedule) / bulk / tanker / inland / passenger / service (dropped), plus a destination zone.
4. **Fitted outputs:**
   - λ_class(hour of day) for arrivals
   - empirical attribute tables
   - lognormal dwell times
   - anchorage waiting times (used for validation)
   - speed per edge for each class (feeds VTS routing)

**Data limit:** 4 days is enough for size distributions and hourly patterns, but **not for weekly patterns**. That needs 4+ weeks, so keep the collector running. Scale overall volumes to the annual call statistics of Port of Antwerp-Bruges.

---

## 3. Ship generation

- **One source node:** the Wandelaar/Steenbank pilot station. There are no separate entry nodes. Through-traffic gets its own source and sink where needed.
- **Containers:** schedule replay (validation mode) or an NHPP λ(hour, weekday) fitted to the schedule.
- **Background traffic:** NHPP per class, attributes bootstrapped from AIS (§2).
- **Derived flags** (regs §2):
  - `needs_pilot` (LOA > 80 m; inland vessels exempt)
  - `needs_tug` and how many (tanker > 120 m, gas tanker always, ULCV)
  - `marginal`: needs a GNA permit (LOA ≥ 300 m, B ≥ 45 m, T ≥ 12.0/12.5 m, …)
  - `ULCV` (LOA ≥ 350 m or B ≥ 51 m)
  - `tide_dependent` (T > 13.10 m)
  - `oversized` (thresholds depend on the zone)
  - `dangerous_goods`

---

## 4. Arrival decision: anchorage or river

The VTS sends a ship **straight up the river** only if all of these hold:
- a pilot is available
- the tidal window is open, and the window at the start is ≥ 60 min (regs §8)
- the weather gates are passed (regs §9)
- the berth or lock will be free at the ETA

**Virtual arrival (scenario switch `virtual_arrival: on/off`).** With it on, the VTS sends a required time of arrival (RTA) at the pilot station to container ships that are still at sea. The ship lowers its speed so that it arrives just in time for its tidal window or berth window, and doesn't wait at anchor.
- The ship enters the model about 12–24 h before its ETA, at a virtual "approach" node with a distance to the pilot station.
- Its speed is limited to `[v_min, v_service]` (e.g. 10–18 kn). If the required delay is larger than `v_min` allows, the remainder is spent at anchor as usual.
- **Comparison:** anchorage waiting time and total time in port, with virtual arrival vs without.

Otherwise the ship goes to an **anchorage**, chosen by type (regs §11):
- ships with dangerous cargo that must show signals → Wielingen Noord
- SRW Annex 1 §1–2 cargo → Schouwenbank / Westhinder
- T ≥ 14 m and tide-dependent → Wielingen-Zuid
- others → Vlissingen Roads, or a sea anchorage

**Each anchorage has a priority queue**, keyed on `(priority class, pilot request time)`:
1. ships in distress
2. tide- or current-dependent ships
3. ships ordered ahead by the authority
4. FCFS (first come, first served)

Limits: anchorage capacity (number of ships) and a maximum stay of 24 h. Breaching either raises an event and the case is logged.

---

## 5. River model

### 5.1 Mesh
- **The graph is an undirected mesh of cells.** It follows the fairway (curvilinear: one axis along the fairway centreline, the other across it), not a N–S grid. It covers only navigable water: the fairway polygon from `data/charts/scheldt_navigation.gpkg`, plus the anchorage polygons, the lock approaches and the docks.
- **Cell size:**
  | Area | Along the fairway | Across the fairway |
  |---|---|---|
  | River and sea approach | **100 m** | **20 m** |
  | Port (docks, Deurganckdok, lock approaches, terminal fronts) | **25 m** (parameter) | **10 m** (parameter) |
  | Transition zone | cell sizes graded over 2–3 rows | |
- **Rough size:** about 100 km of fairway × about 500 m wide → about 25 lanes × 1000 rows ≈ **25k cells on the river**, plus the port mesh (about 20–50k cells, depending on the docks covered). Using a sparse adjacency structure (CSR) keeps the step in Python fast.
- **Neighbours:** 8 (along, across, diagonal). The transitions between the river mesh and the denser port mesh are explicit edges.
- **Lock, berth and anchorage nodes** are special cells, or groups of cells, with a resource attached.
- `port_graph.pkl` stays as the **coarse centreline graph** for route planning (§8). Each mesh cell keeps the id of its coarse edge.

### 5.2 Cell attributes
- depth relative to LAT (mean of `data/charts/scheldt_depth_LAT_wgs84.tif` over the cell)
- zone (sea / Western Scheldt / below Doel–Lillo / above it / dock)
- lane index (distance from the centreline, port/starboard side)
- speed limit
- encounter restrictions (regs §6)
- fairway / outside the fairway (small ships keep out of the fairway, regs §2)

### 5.3 Ships on the mesh
- **A ship's footprint covers several cells.** On the river that's ⌈LOA/100⌉ × ⌈B/20⌉ (e.g. a 400 × 60 m ULCV = 4 × 3 cells). In the port it's ⌈LOA/25⌉ × ⌈B/10⌉.
- **Movement per step:** the distance is `v_sog · Δt`. For example, 13 kn ≈ 2 km per step ≈ 20 river cells. A ship moves along the cell path from its route. Every cell it passes through during the step (its swept path) is checked for conflicts, not only its end position.
- **Conflicts:**
  - Two ships can't occupy the same cell.
  - Meeting and overtaking need a free side lane (keep to starboard, COLREG).
  - Oversized ships block the lanes needed for passing in segments with encounter restrictions. This gives the effect of one-way stretches without making the graph directed.
  - If the path is blocked, the ship slows down or waits. A ship that has to wait produces an event for the VTS.
- **Movement within a step is updated synchronously, in two phases.** Updating ships one after another would bias the results: ships updated first would always get the free cells.
  1. **Proposals:** every ship computes its intended swept path for the step from the same state at the start of the step, i.e. the positions at time t.
  2. **Conflict resolution:** where proposed paths overlap (shared cells, or a ship crossing a cell another one is entering), the higher-priority ship gets the cells. Priority is ranked by:
     1. a ship not under command or in distress
     2. an oversized ship in a restricted segment
     3. VTS plan rank
     4. a random tie-break (seeded)

     The losing ship shortens its move to the last conflict-free cell, or changes lane if a side lane is free. Resolve iteratively until there are no conflicts (usually 1–3 passes).
  3. All accepted moves are applied at once, giving the positions at time t + Δt.
- **Speed** comes from the class's planned speed (regs §8.5), corrected for current and the cell's speed limit. In the port it's much slower (manoeuvring, tugs).
- **Tide:** a harmonic model `h(t) = Σ A_i cos(ω_i t + φ_i)` with M2 (12.42 h), S2 and the phase lag along the river. Fit it to tide-gauge data (Vlissingen, Prosperpolder, Antwerp).
  - `h(t)` is computed every step for every tide zone. The phase lag is interpolated along the river; there are about 10–20 zones, not one per cell.
  - A cell is passable when `depth_LAT + h(t) − T ≥ UKC`, where UKC is the required under-keel clearance. The check uses a passability mask per step (only for the draught classes in use).
  - A voyage's tidal window is the intersection of those intervals along the route, using the ship's own speed. It's planned on the coarse graph and checked on the mesh.
- **Tidal current:** changes speed over ground in each cell: `v_sog = v_planned ± c(t)`. Planned speeds come from regs §8.5 (e.g. container ≤ 14.5 m: 15 kn at sea / 13 kn on the river inbound).
- **Weather:** a Markov chain of hourly states (Bft class × visibility class), with transitions estimated from KNMI or Belgian historical data. Gates follow regs §9, for example:
  - ULCV with wind > 5 Bft at the locks → no permit
  - visibility < 1000 m → marginal ships don't start
  - IMO2 gas tankers need visibility ≥ 1000/2000 m

---

## 6. Pilots and tugs

- **Pilots:** a resource pool split into zones: sea/Western Scheldt → river → docks.
  - Pilot changes at Vlissingen and at the lock.
  - Each pilot is unavailable for the voyage time plus a return time.
  - Two river pilots for LOA ≥ 340 m or B ≥ 51 m, and for LOA ≥ 300 m or B ≥ 45 m going to or from the locks (regs §8.8).
  - Optional ordering rules: order ≥ 6 h ahead; the order is cancelled if the ship is not ready 1 h after the pilot boards (regs §3).
- **Tugs:** lightweight agents with a position (base) and a state (`free`, `transit`, `assist`).
  - Required number from the flags (regs §2, §8.11).
  - Assigned at buoy 35 for arrivals, ≥ 1 h before departure from behind the locks.
  - Start as a pool with travel times. That captures delays from repositioning without full agent behaviour.
- **Fleet sizes are parameters.** The repo has no source for them yet, so run a sensitivity analysis.

---

## 7. Locks, terminals and berths

- **Tidal terminals (no lock):** Deurganckdok (MPET, Antwerp Gateway), Noordzee and Europa.
  - **Most container traffic never goes through a lock.** Only the berthing windows are checked (regs §8.10), e.g. Noordzee S901/S903 for ships > 300 m: rising tide up to HW + 1 h only.
  - Deurganckdok: ships > 210 m moor head-out (regs §10.6).
- **Lock type A, "tidal gate":** open to through traffic when |Δh| < ε (around high tide). Otherwise it works as type B.
- **Lock type B, level-changing** (Berendrecht, Zandvliet, Kieldrecht, Boudewijn, Van Cauwelaert, Kallo, Royers):
  - Cycle: `entry → closing → level change (time ∝ |Δh|) → opening → exit`.
  - **Chamber capacity:** 2D packing (LOA × beam) with greedy first-fit and turn numbers. The biggest ship goes at the front.
  - **Each chamber has a queue**, sorted by the VTS by priority and by how well ships fill the chamber.
  - B ≥ 43 m → Berendrecht preferred. Container ship ≥ 350 m → empty chamber, available from CP (regs §8.9).
  - **Mostly loaded by background traffic** (bulk, tankers, barges behind the locks).
- **Berth allocation:** quay length ≥ Σ(LOA + gap), plus the crane density limit (`alokacja_przestrzenna_w_terminalach.md`). Tankers only at tanker berths. The larger ship goes against the quay.
- **Mooring time:**
  `t_moor = t_base + k·LOA + t_wait(boatmen) + t_wait(tugs)`
  Calibrate `t_base` and `k` from AIS (the time between speed < 0.5 kn and the ship stopping at the berth).
- **Container handling time:** `call_size / (n_STS · 37 moves/h)`, plus the STS buffer blocking model (buffer capacity 4, delay ~ N(240 s, 30 s); `sprzet_ladunkowy.md` §3–4).
- **Background traffic at the berth:** a lognormal dwell time from AIS, with no handling model.
- **Departure** mirrors arrival: unmooring → river or lock → sea.

---

## 8. VTS and routing

- **Two-level routing:**
  - **Strategic:** time-dependent shortest paths using **A*** on the coarse centreline graph (`port_graph.pkl`), with edge times that change with tide, current and congestion.
    - **Heuristic:** Euclidean distance to the goal, `h(n) = ‖n − goal‖₂`. The edge cost is time, so the heuristic is turned into time: `h(n) = ‖n − goal‖₂ / v_max`. Here `v_max` is the ship's highest possible speed over ground (planned speed + the strongest favourable current). That keeps the heuristic admissible: it never overestimates the remaining time, so A* still finds the optimal path.
    - Distances are computed in a metric projection (UTM 31N, EPSG:32631), not in lat/lon degrees.
    - **Space-time reservations (cooperative A*):** the VTS keeps a table `reservations[edge][time slot]`, with a slot length of one step (5 min). Each planned route reserves the edges and slots it will occupy. The capacity of a slot depends on the edge: e.g. one oversized ship per segment, or no meetings in segments with encounter restrictions (regs §6). A* searches in (node, time) and treats full slots as impassable; waiting at a node (anchorage, lock approach) is allowed as a move. Ships are planned in VTS priority order, so ships planned later work around the reservations of earlier ones. This means most conflicts are avoided at the planning stage, and the mesh (§5.3) only handles local deviations.
    - **Route cache:** there are few start–destination pairs (pilot station / anchorages → about 10–20 terminals, locks and sinks). The node sequence of a route is cached per (start, destination, draught class). A* is rerun only when:
      - an edge on the route is closed (blockage, weather gate)
      - the tide makes part of the route impassable for that draught class
      - the reservations make waiting on the cached route more costly than a detour by a set margin
      Otherwise only the timing is recomputed against the reservations. Edge speeds per class come from the AIS statistics. The VTS works at this level.
  - **Tactical:** choosing lanes and cells on the mesh within the coarse edge (keep to starboard, overtaking, avoiding blocked cells). This is a local search over a few rows ahead, not A* across the whole mesh for every ship.
- **The VTS is a central planner on a rolling horizon.** Every 3 steps (15 min of simulated time) it plans the next 6–12 h (72–144 steps) for **all** traffic:
  - It assigns each ship a start time, a route, a pilot, tugs and a lock slot.
  - **Objective:** minimise Σ w_i · (waiting time + delay), with priority weights w_i. Container ships may be weighted higher, depending on the scenario.
  - **Constraints:** tidal windows, edge capacity and encounters (the reservation table), chamber capacity, berth availability, weather gates.
  - **Berth windows are given, not decided by the VTS.** Container terminals assign berths in advance; the schedule CSV already gives arrival, departure and terminal. The VTS takes `[berth_start, berth_end]` as a fixed input and plans the voyage to arrive within the window (the ship arrives no earlier than `berth_start − mooring buffer`). It does not reassign berths. Only when a ship misses its window because of a delay does a terminal-side rule (not the VTS) pick the next free slot on the same quay, or a fallback berth (regs §8.11). Background traffic has no fixed windows; its berths are assigned on arrival (§7).
  - **Solver:** start with a priority heuristic, then a MILP on a time-expanded graph (OR-Tools / PuLP).
- **Game theory:**
  - A central planner that optimises the total is socially optimal by definition. The game-theory result comes from comparing it with uncoordinated behaviour.
  - **Baseline:** each ship picks its own best start and route (a Nash equilibrium via best-response iteration), or plain FCFS.
  - **Price of Anarchy** = cost(selfish) / cost(VTS), measured **for container ships and for the whole system separately**.
  - Optional: VCG or slot auctions, so that ships report their real ETA and priority truthfully.

---

## 9. Outputs and validation

**KPIs** (container ships are the main ones):
- time in port, split into anchorage / river / lock / berth / handling
- anchorage waiting time
- utilisation of pilots, tugs, locks, berths and STS cranes
- queue lengths over time
- share of ships delayed by tide or weather
- Price of Anarchy

**Validation:**
- containers: time in port vs `time_in_port.pdf`, productivity vs `terminal_performance.pdf`
- background traffic: AIS distributions (number of ships at anchor, ships per hour through the locks, dwell times)
- the whole system: number of ships at anchor and on the river vs the AIS snapshots (about 720–750 ships in the area)

**Visualisation:** animation on the graph (matplotlib), plus a queue timeline.

**Scenarios:** storm, a lock closed, +20% traffic, fewer pilots or tugs, more ULCVs, **virtual arrival on vs off** (§4).

---

## 10. Milestones

| # | Milestone | Done when |
|---|---|---|
| 1 | Mesh (100×20 m river, denser in the port) + depth per cell + tide + UKC mask | the mesh covers the fairway with no gaps; the tidal window for a 15 m draught ship matches regs §8 |
| 2 | AIS pipeline: tracks → classification → fitted distributions | class counts and dwell-time histograms produced |
| 3 | Generator: containers from the schedule + background traffic from the AIS fits | arrival histograms match the CSV and AIS |
| 4 | 5-min step loop + movement on the mesh, no resource constraints | every ship completes its loop; no cell conflicts |
| 5 | Pilots, tugs, anchorages with priorities (shared by both levels) | queues appear |
| 6 | Container terminals in detail (berths, STS, buffers) | handling times match `sprzet_ladunkowy.md` §3 |
| 7 | Locks A/B with packing, mixed traffic | a lock cycle works for a mix of ships |
| 8 | Weather (Markov) + gates | ULCVs wait out wind |
| 9 | VTS heuristic with reservation table + route cache + fixed berth windows → MILP + selfish baseline | Price of Anarchy measured; no conflicts at the planning stage |
| 9b | Virtual arrival scenario | waiting time and time in port compared, with vs without |
| 10 | Calibration, validation, scenarios | report |

**New dependencies:** `numpy`, `scipy` (sparse adjacency), `pandas`, `rasterio`, `geopandas` (fairway polygons, building the mesh), and later `ortools`.

---

## Open questions
- Pilot and tug fleet sizes: sources are needed, otherwise they stay sensitivity parameters.
- Is the full MILP VTS required, or is the heuristic + Price of Anarchy comparison enough?
- How long to collect AIS data before fitting the final distributions (target ≥ 4 weeks)?
- Port mesh resolution: 25 × 10 m is the starting value. Check whether it is fine enough for berth manoeuvres and packing ships into lock chambers.
