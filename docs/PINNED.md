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
- **Weekly pattern of inland traffic.** Measured in the AIS (17 November 2026): at weekends a quarter to two fifths
  fewer inland passages at Hansweert, Terneuzen, Zandvliet-Berendrecht, Kieldrecht and on the river (none at
  Kreekrak and Kallo). The model runs every day at the mean, so held-out days that are mostly weekend (13-15
  November) show too many inland craft. Fit a weekday factor on the inland arrivals; it also sets when the lock
  queues form, which matters for the experiments. Hold out whole weeks.
- **Hold-out split.** Done in part (17 November 2026): the model is fitted on 26 October to 12 November and
  measured again on 13 to 15 November, three whole days (MODEL.md §19). Three days are too few for a score of
  their own; they were used to test calibrated values. Extend the held-out days as the record grows, and do not
  re-fit on them.

## Locks

- **Lock outages and maintenance.** Not modelled. A natural scenario later.
- **Lock times.** The Antwerp locks use data/equipment/locks.csv with the operating time set half-way between its
  two readings (operation time, passage time), on the AIS passage times (MODEL.md §14, §19); at Boudewijn and Van
  Cauwelaert the AIS reads it as the passage time. Open: confirm at the
  source which it is; Kattendijk's 45 min is long for so small a lock; a sea-going ship's entry and exit times
  (12 and 8 min) are still assumed; the Terneuzen new lock is still assumed (ask North Sea Port).

- **Hansweert passage time.** With the published 15 min an inland craft takes 44 min to pass where the AIS has
  36 (MODEL.md §14, §19). Not the wait of 3 min for a second craft: without it at every lock (a test, four
  seeds) Hansweert is still 12 % slow and Kreekrak and Terneuzen become 21 % and 14 % fast, so it is kept.
  The excess lies within 400 m of the lock (40 against 26 min; from 400 m to 3 km the model is right). In the
  AIS Hansweert's lockage is 5 min shorter than Kreekrak's, the model's 4 min longer (15 against 11 min
  published, 2001). Open: (1) ask Rijkswaterstaat for Hansweert's operating time now; (2) a wait for a second
  craft only when one is coming (needs how far ahead a lock keeper looks); (3) the parts of a lock passage that
  fall on 5-minute steps or at one place (the craft drawn at the gate from half its sail-in; the sail-in at
  3.6 kn over the whole 1,200 m where the AIS speed is that of the last 600 m) put all three canal locks 5 to
  14 min over within 400 m.
- **Vlissingen town share.** Back at the AIS share, 0.094 (it was 0.036, calibrated): 12.2 inland passages a day
  off Vlissingen against 12.7 (`0028_vlissingen-ais`, five seeds).
- **Two inland craft abreast** at a berth (`ALONGSIDE_PER_BERTH`) is assumed. Not reached at today's traffic;
  find a source before runs with more traffic.

## Scenarios

- **Scenario switches** (traffic factors and the like) are left for later; the fitted container mode can scale
  its rate, the weeks and replay modes cannot yet (above).
- **Read the `silent` block first** in any run with more traffic (MODEL.md §17): calls dropped or left out,
  destinations drawn again, waits for a berth, anchorages full, and where stuck ships were let past (most at
  km 20–25 off Terneuzen; no VTS hold was added there).

## Pilots

- **Pool sizes.** Still sized from the AIS peak. Public figures found: about 340 Flemish pilots in four corps
  (Flows, October 2025), a rota of 6 days on call and 5 off, about 900 hours on the bridge a year
  (Beroepsvereniging van Loodsen). No split by corps or zone, and no count of the Dutch pilots working the
  Scheldt or of the Brabo dock pilots. Ask DAB Loodswezen, the Dutch Loodswezen (region Scheldemonden) and Brabo
  for pilots on duty per zone.

## Validation gaps (MODEL.md §19)

As of 17 November 2026, the baseline after the fifth round (`0029_baseline`: 125 of 135 numbers agree on the fitted
days, emergent 78 of 85, calibrated 36 of 39, input 11 of 11; 98 of 121 on the three days held out). Every calibrated
value holds on the days held out or is not shown either way there (MODEL.md §19). The fourth round
(`0011_round3-barges-after-ship`) had 105 of 113; the fifth took calibration out and did not aim at the score.
The figures in the items below are the fourth round's unless they name the fifth.

- **Fifth round, new or changed.** Hansweert's inland median +24 % and its 90th percentile −22 % (Locks, above);
  bulk carriers at anchor 3.9 against 5.6 since the factor on their anchor stay was taken out (the stops at the
  river anchorages are not modelled); inland craft under way at sea 0.38 against 0.66; Kallo's sea-going median
  with the approaches 1.83 against 1.50 h; Kieldrecht's inland 90th percentile with the approaches 2.2 against
  4.3 h. On the days held out: inland craft through Kallo 24.8 a day against 11.8 and through
  Zandvliet–Berendrecht 75.6 against 53.1, tankers at anchor 11.1 against 6.2, inland tankers at berths 168
  against 127. Leads for when the record is longer.

- **Zandvliet–Berendrecht's 90th percentiles.** Inland craft 2.69 h against 2.17 h, sea-going ships 2.64 h against
  2.25 h, with both medians right (1.32 against 1.17 h, 1.80 against 1.75 h). The slow inland passages wait an hour
  to be called: the chambers' capacity at the busy hours. The time a sea-going ship takes to come in (30 min,
  calibrated) trades the two: at 18 min the inland craft are right and the sea-going ships 15 % fast. Needs the
  lock planning of the 500 m locks (lockages for inland craft alone, how barges are fitted around a sea-going ship).
- **Lock holds are calibrated, not observed.** Probability per lock (Kallo 0.25, Kieldrecht 0.16, Terneuzen 0.08,
  Kreekrak 0.06, Boudewijn and Van Cauwelaert 0.05) and a mean of 35 min, set on the 90th percentiles of the
  passage times. Those of Hansweert (0.20) and of Zandvliet and Berendrecht (0.10) did not hold on the days held
  out and were taken out; the others are not yet tested one by one. Ask the lock operators for stoppages.
- **Lock times set on the AIS, not on a source.** Van Cauwelaert 20 min
  (locks.csv: 45 min as a passage time), the time a sea-going ship takes to come in (Zandvliet and Berendrecht 30,
  Kieldrecht 26, Boudewijn and Van Cauwelaert 20, Kallo 14 min). Confirm at the source.
- **Sea-going ships under way in the docks** 3.21 against 2.76 (+16 %), with the piloted ones under way in the docks
  right (3.15 against 3.20). Probably the last of the approach to a berth counted both as sailing and in the
  mooring time for the unpiloted small ships; not changed.
- **Small sea-going ships on the canals** (Hansweert 0.08 a day against 0.47, Kreekrak 0.05 against 0.40, Royers
  0.12 against 0): a few ships a week, coasters to and from the Rhine that the fit puts on other routes.
- **Canal scaling per canal.** One factor for three canals leaves km 32 (−12 %), km 68 and km 72 (−10 %) short of
  inland craft.
- **Rijkswaterstaat's lock counts** (2017, 2018) and the AIS (2026) differ: Terneuzen 126 against 153 passages a day
  in the AIS, Kreekrak 189 against 174, Hansweert 113 against 99. The model follows the AIS (147, 170, 100) and so
  "differs" on all three. A newer count would settle it.
- **Container ships in the area** +10 % (28.6 against 25.9) with the ships at berths and at anchor right: time
  under way between the sea and the berth; the virtual arrival is planned at the class's speed.
- **Rebuild of the cached graph.** The place "terneuzen" was moved in the cached graph by hand to where
  places.CALL_PLACES now puts it; the next rebuild gives the same.
