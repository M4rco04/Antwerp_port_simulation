# Validation of 0011_round3-barges-after-ship

AIS record 2026-10-26 01:00 to 2026-11-12 01:28 UTC, 4581 snapshots, 15 whole days. Model: mean of 5 replications. ± is a 95 % interval (the record's from its day-to-day spread).
A number agrees when the difference is within twice its standard error or within the tolerance.

- emergent: 62 of 66 agree
- calibrated: 31 of 35 agree
- input: 12 of 12 agree

## Arrivals

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| bulk and general cargo ships entering, a day | I | 29.8 ± 2.7 | 29.2 ± 2.0 | -2 % | agrees |
| container ships entering, a day | I | 12.7 ± 1.7 | 12.5 ± 0.5 | -2 % | agrees |
| inland cargo craft entering, a day | I | 140 ± 6 | 139 ± 2 | -1 % | agrees |
| inland tankers entering, a day | I | 91.2 ± 5.3 | 91.3 ± 1.6 | +0 % | agrees |
| passenger ships entering, a day | I | 5.06 ± 1.12 | 4.88 ± 0.26 | -3 % | agrees |
| tankers entering, a day | I | 18.5 ± 2.1 | 18.6 ± 0.2 | +1 % | agrees |

## River traffic

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| km 8, off Vlissingen: inland, passages a day | E | 12.7 ± 1.4 | 11.8 ± 0.6 | -7 % | agrees |
| km 8, off Vlissingen: sea-going, passages a day | E | 105 ± 7 | 107 ± 3 | +1 % | agrees |
| km 32, Terneuzen to Hansweert: inland, passages a day | E | 179 ± 21 | 157 ± 3 | -12 % | agrees |
| km 32, Terneuzen to Hansweert: sea-going, passages a day | E | 80.9 ± 3.1 | 76.7 ± 1.1 | -5 % | agrees |
| km 48, Hansweert to Bath: inland, passages a day | E | 92.0 ± 11.5 | 92.0 ± 1.1 | +0 % | agrees |
| km 48, Hansweert to Bath: sea-going, passages a day | E | 80.5 ± 3.4 | 76.8 ± 1.2 | -5 % | agrees |
| km 62, Bath to the Zandvliet locks: inland, passages a day | E | 91.4 ± 10.9 | 91.9 ± 1.1 | +1 % | agrees |
| km 62, Bath to the Zandvliet locks: sea-going, passages a day | E | 80.7 ± 2.9 | 76.8 ± 1.2 | -5 % | agrees |
| km 68, Zandvliet to Deurganckdok: inland, passages a day | E | 132 ± 13 | 118 ± 3 | -11 % | agrees |
| km 68, Zandvliet to Deurganckdok: sea-going, passages a day | E | 45.5 ± 3.5 | 43.4 ± 0.7 | -5 % | agrees |
| km 72, Deurganckdok to Boudewijn: inland, passages a day | E | 103 ± 9 | 92.8 ± 2.4 | -10 % | agrees |
| km 72, Deurganckdok to Boudewijn: sea-going, passages a day | E | 22.0 ± 3.9 | 20.2 ± 0.9 | -8 % | agrees |
| km 80, Kallo to Antwerp: inland, passages a day | E | 51.7 ± 9.1 | 48.8 ± 1.5 | -6 % | agrees |
| km 80, Kallo to Antwerp: sea-going, passages a day | E | 3.67 ± 1.31 | 3.84 ± 0.31 | +5 % | agrees |
| km 88, above Antwerp: inland, passages a day | E | 46.4 ± 9.1 | 44.0 ± 1.4 | -5 % | agrees |
| km 88, above Antwerp: sea-going, passages a day | E | 2.07 ± 1.28 | 2.24 ± 0.26 | +8 % | agrees |
| sea, 3.10°E (Wandelaar to Wielingen): sea-going, passages a day | E | 78.9 ± 4.8 | 74.8 ± 3.0 | -5 % | agrees |
| sea-going ships calling at Antwerp (the port's statistics, 2020 and 2021), a day | E | 38.1 ± 1.6 | 38.0 ± 1.1 | -0 % | agrees |

## Sailing times

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| sea-going, km 8 to km 62, median, h | C | 2.67 ± 0.07 | 2.68 ± 0.03 | +1 % | agrees |
| sea-going, km 8 to km 62, 90th percentile, h | E | 3.50 ± 0.15 | 3.28 ± 0.04 | -6 % | agrees |
| sea-going, km 62 to km 8, median, h | C | 2.50 ± 0.08 | 2.52 ± 0.03 | +1 % | agrees |
| sea-going, km 62 to km 8, 90th percentile, h | E | 3.25 ± 0.08 | 3.10 ± 0.06 | -5 % | agrees |
| inland, km 32 to km 48, median, h | E | 1.17 ± 0.01 | 1.17 | +0 % | agrees |
| inland, km 32 to km 48, 90th percentile, h | E | 1.67 ± 0.08 | 1.58 | -5 % | agrees |
| inland, km 48 to km 32, median, h | E | 1.17 ± 0.03 | 1.17 | +0 % | agrees |
| inland, km 48 to km 32, 90th percentile, h | E | 1.58 ± 0.08 | 1.55 ± 0.04 | -2 % | agrees |
| sea-going, sea to km 8, median, h | C | 1.83 ± 0.05 | 1.83 | -0 % | agrees |
| sea-going, sea to km 8, 90th percentile, h | E | 2.42 ± 0.11 | 2.17 | -10 % | differs |
| sea-going, km 8 to sea, median, h | C | 1.67 ± 0.03 | 1.67 | +0 % | agrees |
| sea-going, km 8 to sea, 90th percentile, h | E | 2.20 ± 0.09 | 1.98 ± 0.03 | -10 % | agrees |

## Ships under way

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| dock: inland, ships | E | 27.0 ± 2.2 | 26.6 ± 0.4 | -2 % | agrees |
| dock: sea-going, ships | E | 2.76 ± 0.17 | 3.21 ± 0.12 | +16 % | differs |
| river: inland, ships | E | 25.5 ± 2.9 | 24.5 ± 0.7 | -4 % | agrees |
| river: sea-going, ships | E | 13.0 ± 0.5 | 12.2 ± 0.7 | -6 % | agrees |
| sea: inland, ships | E | 0.65 ± 0.08 | 0.82 ± 0.06 | +25 % | agrees |
| sea: sea-going, ships | E | 10.0 ± 0.6 | 10.5 ± 0.3 | +5 % | agrees |

## Piloted ships under way

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| dock, mean, ships | E | 3.20 ± 0.22 | 3.15 ± 0.12 | -1 % | agrees |
| dock, 95th percentile, ships | E | 6.93 ± 0.49 | 6.60 ± 0.48 | -5 % | agrees |
| river, mean, ships | E | 13.4 ± 0.6 | 12.1 ± 0.7 | -9 % | agrees |
| river, 95th percentile, ships | E | 19.9 ± 1.1 | 18.8 ± 0.7 | -5 % | agrees |
| sea, mean, ships | E | 11.2 ± 0.6 | 12.2 ± 0.4 | +9 % | agrees |
| sea, 95th percentile, ships | E | 16.7 ± 0.9 | 18.8 ± 1.1 | +13 % | agrees |

## Locks

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| Boudewijn-Van Cauwelaert: inland passing, a day | E | 91.3 ± 6.3 | 102 ± 2 | +12 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going passing, a day | E | 9.87 ± 1.67 | 8.84 ± 0.82 | -10 % | agrees |
| Hansweert: inland passing, a day | E | 98.7 ± 9.6 | 99.7 ± 2.5 | +1 % | agrees |
| Hansweert: sea-going passing, a day | E | 0.47 ± 0.32 | 0.08 ± 0.07 | -82 % | differs |
| Kallo: inland passing, a day | E | 23.3 ± 2.2 | 25.0 ± 2.0 | +7 % | agrees |
| Kallo: sea-going passing, a day | E | 5.47 ± 1.35 | 6.47 ± 0.78 | +18 % | agrees |
| Kieldrecht: inland passing, a day | E | 25.4 ± 4.2 | 28.0 ± 1.6 | +10 % | agrees |
| Kieldrecht: sea-going passing, a day | E | 10.0 ± 0.9 | 8.76 ± 0.99 | -12 % | agrees |
| Kreekrak: inland passing, a day | E | 174 ± 11 | 166 ± 3 | -4 % | agrees |
| Kreekrak: sea-going passing, a day | E | 0.40 ± 0.42 | 0.05 ± 0.07 | -88 % | agrees |
| Royers-Kattendijk: inland passing, a day | E | 0.40 ± 0.57 | 0.15 ± 0.11 | -62 % | agrees |
| Royers-Kattendijk: sea-going passing, a day | E | 0.00 | 0.12 ± 0.10 | +nan % | differs |
| Terneuzen: inland passing, a day | E | 130 ± 16 | 123 ± 3 | -5 % | agrees |
| Terneuzen: sea-going passing, a day | E | 23.5 ± 2.9 | 22.0 ± 1.6 | -6 % | agrees |
| Zandvliet-Berendrecht: inland passing, a day | E | 71.1 ± 10.0 | 76.4 ± 2.2 | +7 % | agrees |
| Zandvliet-Berendrecht: sea-going passing, a day | E | 37.1 ± 1.8 | 34.6 ± 1.4 | -7 % | agrees |
| Boudewijn-Van Cauwelaert: inland, time to pass, median, h | C | 1.00 ± 0.01 | 1.10 ± 0.03 | +10 % | agrees |
| Boudewijn-Van Cauwelaert: inland, time to pass, 90th percentile, h | C | 1.74 ± 0.10 | 1.86 ± 0.11 | +7 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going, time to pass, median, h | C | 1.35 ± 0.10 | 1.32 ± 0.03 | -2 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going, time to pass, 90th percentile, h | C | 1.93 ± 0.23 | 1.73 ± 0.10 | -11 % | agrees |
| Hansweert: inland, time to pass, median, h | C | 0.60 ± 0.01 | 0.67 ± 0.01 | +13 % | agrees |
| Hansweert: inland, time to pass, 90th percentile, h | C | 1.50 ± 0.11 | 1.51 ± 0.06 | +1 % | agrees |
| Kallo: inland, time to pass, median, h | C | 0.84 ± 0.07 | 1.00 | +19 % | agrees |
| Kallo: inland, time to pass, 90th percentile, h | C | 1.81 ± 0.37 | 1.98 ± 0.16 | +9 % | agrees |
| Kallo: sea-going, time to pass, median, h | C | 1.25 ± 0.10 | 1.25 ± 0.03 | +0 % | agrees |
| Kallo: sea-going, time to pass, 90th percentile, h | C | 2.02 ± 1.03 | 1.83 ± 0.24 | -9 % | agrees |
| Kieldrecht: inland, time to pass, median, h | C | 0.92 ± 0.05 | 1.00 | +9 % | agrees |
| Kieldrecht: inland, time to pass, 90th percentile, h | C | 1.86 ± 0.27 | 2.09 ± 0.14 | +12 % | agrees |
| Kieldrecht: sea-going, time to pass, median, h | C | 1.42 ± 0.06 | 1.49 ± 0.02 | +5 % | agrees |
| Kieldrecht: sea-going, time to pass, 90th percentile, h | C | 1.93 ± 0.14 | 2.02 ± 0.13 | +4 % | agrees |
| Kreekrak: inland, time to pass, median, h | C | 0.75 ± 0.01 | 0.77 ± 0.01 | +3 % | agrees |
| Kreekrak: inland, time to pass, 90th percentile, h | C | 1.44 ± 0.07 | 1.38 ± 0.03 | -4 % | agrees |
| Terneuzen: inland, time to pass, median, h | C | 0.87 ± 0.05 | 0.88 ± 0.03 | +1 % | agrees |
| Terneuzen: inland, time to pass, 90th percentile, h | C | 1.79 ± 0.08 | 1.84 ± 0.09 | +3 % | agrees |
| Terneuzen: sea-going, time to pass, median, h | C | 1.00 ± 0.02 | 0.97 ± 0.03 | -3 % | agrees |
| Terneuzen: sea-going, time to pass, 90th percentile, h | C | 1.33 ± 0.05 | 1.52 ± 0.06 | +14 % | agrees |
| Zandvliet-Berendrecht: inland, time to pass, median, h | C | 1.17 ± 0.04 | 1.32 ± 0.03 | +13 % | agrees |
| Zandvliet-Berendrecht: inland, time to pass, 90th percentile, h | C | 2.17 ± 0.12 | 2.69 ± 0.10 | +24 % | differs |
| Zandvliet-Berendrecht: sea-going, time to pass, median, h | C | 1.75 ± 0.03 | 1.80 ± 0.03 | +3 % | agrees |
| Zandvliet-Berendrecht: sea-going, time to pass, 90th percentile, h | C | 2.25 ± 0.09 | 2.64 ± 0.08 | +18 % | agrees |
| Hansweert: commercial passages, Rijkswaterstaat's count, a day | C | 113 ± nan | 100 ± 3 | -11 % | differs |
| Kreekrak: commercial passages, Rijkswaterstaat's count, a day | C | 189 ± nan | 170 ± 3 | -10 % | differs |
| Terneuzen: commercial passages, Rijkswaterstaat's count, a day | C | 126 ± nan | 147 ± 3 | +17 % | differs |

## Ships in the area

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| bulk and general cargo ships at anchor, ships | C | 5.62 ± 0.72 | 5.81 ± 1.07 | +3 % | agrees |
| bulk and general cargo ships at a berth, ships | I | 55.7 ± 3.7 | 60.0 ± 3.5 | +8 % | agrees |
| bulk and general cargo ships in the area, ships | E | 77.4 ± 4.3 | 81.2 ± 4.6 | +5 % | agrees |
| container ships at anchor, ships | E | 2.06 ± 0.43 | 2.28 ± 0.39 | +11 % | agrees |
| container ships at a berth, ships | I | 16.2 ± 1.4 | 17.3 ± 0.9 | +6 % | agrees |
| container ships in the area, ships | E | 25.9 ± 1.7 | 28.5 ± 1.0 | +10 % | agrees |
| inland cargo craft at anchor, ships | E | 1.07 ± 0.25 | 1.23 ± 0.09 | +14 % | agrees |
| inland cargo craft at a berth, ships | C | 161 ± 7 | 164 ± 9 | +2 % | agrees |
| inland cargo craft in the area, ships | E | 220 ± 7 | 212 ± 10 | -4 % | agrees |
| inland tankers at anchor, ships | E | 0.87 ± 0.32 | 0.79 ± 0.14 | -9 % | agrees |
| inland tankers at a berth, ships | C | 156 ± 14 | 164 ± 4 | +5 % | agrees |
| inland tankers in the area, ships | E | 197 ± 14 | 197 ± 4 | -0 % | agrees |
| tankers at anchor, ships | C | 9.64 ± 0.74 | 10.0 ± 1.9 | +4 % | agrees |
| tankers at a berth, ships | I | 42.4 ± 1.9 | 41.2 ± 2.7 | -3 % | agrees |
| tankers in the area, ships | E | 67.4 ± 2.1 | 63.5 ± 4.3 | -6 % | agrees |

## Container ships

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| share that anchors before berthing | E | 0.12 ± 0.05 | 0.14 ± 0.02 | +15 % | agrees |
| at the four terminals, ships | E | 12.4 ± 0.8 | 12.9 ± 0.6 | +4 % | agrees |
| berthing against the schedule, mean, h | I | 28.9 ± 8.6 | 30.6 ± 1.2 | +6 % | agrees |
| berthing against the schedule, standard deviation, h | I | 32.4 ± 7.7 | 30.4 ± 1.1 | -6 % | agrees |
| share berthing over 12 h after their planned time | E |  | 0.11 ± 0.04 |  |  |
| 3.10°E to the berth, median, h | E | 4.92 ± 0.12 | 5.03 ± 0.04 | +2 % | agrees |
| 3.10°E to the berth, 90th percentile, h | E | 5.82 ± 9.43 | 6.04 ± 0.11 | +4 % | agrees |
| time at the berth, median, h | I | 24.9 ± 2.4 | 24.3 ± 1.2 | -3 % | agrees |
