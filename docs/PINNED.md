# Pinned for later

Things set aside on 10 November 2026, with what each one waits for.

## Experiments

- **Which experiments to run.** Several different ones are in mind; they are chosen after the model is finished
  and validated. The planning VTS and the selfish baseline of PLAN.md §8 belong here.

## Container handling

- **Crane model.** Crane rates are a placeholder: a fixed rate per crane, no shift pattern, no breakdowns, no
  crane-buffer blocking. The container handling part will be expanded.
- **Call sizes.** A container ship is at the berth for its scheduled stay whatever cranes it gets; the moves
  recorded are crane-hours, not box counts (MODEL.md §15.4). Replace with real call sizes, and a stay that depends
  on the cranes, when the handling model is expanded.
- **Arrival rate scenarios.** `--containers weeks` (a schedule of whole real weeks) replaces the fitted mode for
  normal runs. The fitted mode (`nhpp`) stays only because it can scale the arrival rate; it draws calls one by
  one, so calls at a terminal overlap more than a planned schedule lets them. A rate factor for weeks mode is
  still to do.

## Schedule delay

- **Delay sample.** Re-fitted on 12 November 2026 with a one-to-one match within ±84 h: 55 calls, mean 29 h,
  standard deviation 32 h (38 calls, 36 h and 26 h three days of AIS earlier: it still moves). The delay is real (MODEL.md §3), but the sample is small, and the second schedule
  file lies after the AIS record so far. Re-fit when the AIS record covers it. Still open: whether delays at a
  terminal go together (too few calls per terminal to tell), and why the schedule runs a day and a half early.

## Traffic data

- **AIS record.** Only live data can be collected, so the record grows by waiting. Re-fit when it is longer:
  the weekly pattern, rare classes and routes, and a part held out for validation all need it.
- **Hold-out split.** Fitting on the first weeks and validating on the rest is skipped for now, for the same
  reason.

## Locks

- **Lock outages and maintenance.** Not modelled. A natural scenario later.
- **Lock times.** The Antwerp locks use data/equipment/locks.csv with the operating time set half-way between its
  two readings (operation time, passage time), on the AIS passage times (MODEL.md §14, §19). Open: confirm at the
  source which it is; Kattendijk's 45 min is long for so small a lock; a sea-going ship's entry and exit times
  (12 and 8 min) are still assumed; the Terneuzen new lock is still assumed (ask North Sea Port).

## Pilots

- **Pool sizes.** Still sized from the AIS peak. Public figures found: about 340 Flemish pilots in four corps
  (Flows, October 2025), a rota of 6 days on call and 5 off, about 900 hours on the bridge a year
  (Beroepsvereniging van Loodsen). No split by corps or zone, and no count of the Dutch pilots working the
  Scheldt or of the Brabo dock pilots. Ask DAB Loodswezen, the Dutch Loodswezen (region Scheldemonden) and Brabo
  for pilots on duty per zone.

## Validation gaps (MODEL.md §19)

- **Lock queues.** Time to pass Terneuzen, Hansweert and Boudewijn–Van Cauwelaert is 30 to 90 % above the AIS, all
  of it waiting in the queue. Needs the chamber assignment rules (Terneuzen: which ships use which of the three
  chambers) and the cycle of the Boudewijn and Van Cauwelaert chambers; ask Rijkswaterstaat / North Sea Port and
  the harbour master.
- **Sea-going voyages into and between the docks** are short (Kallo, Boudewijn–Van Cauwelaert, river beyond
  Deurganckdok). Fit moves between berths within one dock zone (now merged into one call).
- **Jams in the docks** in some replications near Boudewijn–Van Cauwelaert (release valves 3 to 14 per 1,000).
- **Container ships' further calls** between zones, and stops of ships at the river anchorages, are not modelled.
- **One speed per class**: sailing-time 90th percentiles 12 to 17 % short. A drawn speed per ship would widen them.

