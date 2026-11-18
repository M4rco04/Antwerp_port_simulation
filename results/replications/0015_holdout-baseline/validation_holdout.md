# Validation of 0015_holdout-baseline

AIS record 2026-11-13 00:00 to 2026-11-15 18:15 UTC, 796 snapshots, 3 whole days. Model: mean of 5 replications. ± is a 95 % interval (the record's from its day-to-day spread).
A number agrees when the difference is within twice its standard error or within the tolerance.

- emergent: 54 of 79 agree
- calibrated: 26 of 38 agree
- input: 2 of 5 agree

## Arrivals

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| bulk and general cargo ships entering, a day | I |  | 28.5 ± 2.8 |  |  |
| container ships entering, a day | I | 8.29 ± 3.40 | 8.33 ± 1.51 | +0 % | agrees |
| inland cargo craft entering, a day | I |  | 143 ± 5 |  |  |
| inland tankers entering, a day | I |  | 94.8 ± 7.1 |  |  |
| passenger ships entering, a day | I |  | 5.14 ± 0.61 |  |  |
| tankers entering, a day | I |  | 18.9 ± 2.4 |  |  |

## River traffic

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| km 8, off Vlissingen: inland, passages a day | E | 10.1 ± 3.0 | 11.4 ± 2.1 | +13 % | agrees |
| km 8, off Vlissingen: sea-going, passages a day | E | 107 ± 22 | 104 ± 4 | -2 % | agrees |
| km 32, Terneuzen to Hansweert: inland, passages a day | E | 160 ± 51 | 154 ± 6 | -4 % | agrees |
| km 32, Terneuzen to Hansweert: sea-going, passages a day | E | 82.1 ± 15.8 | 75.2 ± 5.5 | -8 % | agrees |
| km 48, Hansweert to Bath: inland, passages a day | E | 85.5 ± 27.5 | 92.7 ± 5.3 | +9 % | agrees |
| km 48, Hansweert to Bath: sea-going, passages a day | E | 81.3 ± 17.6 | 75.4 ± 5.4 | -7 % | agrees |
| km 62, Bath to the Zandvliet locks: inland, passages a day | E | 85.8 ± 28.9 | 94.2 ± 5.3 | +10 % | agrees |
| km 62, Bath to the Zandvliet locks: sea-going, passages a day | E | 82.6 ± 17.9 | 75.1 ± 5.3 | -9 % | agrees |
| km 68, Zandvliet to Deurganckdok: inland, passages a day | E | 125 ± 36 | 116 ± 10 | -7 % | agrees |
| km 68, Zandvliet to Deurganckdok: sea-going, passages a day | E | 47.9 ± 7.0 | 39.8 ± 3.7 | -17 % | agrees |
| km 72, Deurganckdok to Boudewijn: inland, passages a day | E | 99.2 ± 41.9 | 90.6 ± 7.6 | -9 % | agrees |
| km 72, Deurganckdok to Boudewijn: sea-going, passages a day | E | 22.7 ± 6.4 | 20.9 ± 2.7 | -8 % | agrees |
| km 80, Kallo to Antwerp: inland, passages a day | E | 38.5 ± 24.2 | 45.9 ± 6.2 | +19 % | agrees |
| km 80, Kallo to Antwerp: sea-going, passages a day | E | 1.98 ± 2.23 | 4.27 ± 0.35 | +116 % | agrees |
| km 88, above Antwerp: inland, passages a day | E | 35.4 ± 25.1 | 41.0 ± 5.5 | +16 % | agrees |
| km 88, above Antwerp: sea-going, passages a day | E | 1.54 ± 1.55 | 2.83 ± 0.47 | +83 % | agrees |
| sea, 3.10°E (Wandelaar to Wielingen): sea-going, passages a day | E | 83.5 ± 7.8 | 72.7 ± 5.2 | -13 % | agrees |
| sea-going ships calling at Antwerp (the port's statistics, 2020 and 2021), a day | E | 38.1 ± 1.6 | 36.6 ± 2.1 | -4 % | agrees |

## Sailing times

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| sea-going, km 8 to km 62, median, h | C | 2.58 ± 0.17 | 2.71 ± 0.04 | +5 % | agrees |
| sea-going, km 8 to km 62, 90th percentile, h | E | 3.46 ± 0.27 | 3.23 ± 0.07 | -7 % | agrees |
| sea-going, km 62 to km 8, median, h | C | 2.50 ± 0.11 | 2.50 ± 0.05 | +0 % | agrees |
| sea-going, km 62 to km 8, 90th percentile, h | E | 3.08 ± 0.19 | 3.26 ± 0.49 | +6 % | agrees |
| inland, km 32 to km 48, median, h | E | 1.08 ± 0.10 | 1.17 | +8 % | agrees |
| inland, km 32 to km 48, 90th percentile, h | E | 1.58 ± 0.12 | 1.56 ± 0.17 | -1 % | agrees |
| inland, km 48 to km 32, median, h | E | 1.08 ± 0.09 | 1.22 ± 0.04 | +12 % | differs |
| inland, km 48 to km 32, 90th percentile, h | E | 1.52 ± 0.22 | 1.58 ± 0.16 | +4 % | agrees |
| sea-going, sea to km 8, median, h | C | 1.83 ± 0.13 | 1.87 ± 0.04 | +2 % | agrees |
| sea-going, sea to km 8, 90th percentile, h | E | 2.17 ± 0.11 | 2.35 ± 0.36 | +8 % | agrees |
| sea-going, km 8 to sea, median, h | C | 1.75 ± 0.09 | 1.70 ± 0.04 | -3 % | agrees |
| sea-going, km 8 to sea, 90th percentile, h | E | 2.58 ± 0.38 | 1.97 ± 0.06 | -24 % | differs |

## Ships under way

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| dock: inland, ships | E | 23.1 ± 4.9 | 0.00 | -100 % | differs |
| dock: sea-going, ships | E | 2.58 ± 0.79 | 0.00 | -100 % | differs |
| river: inland, ships | E | 20.5 ± 6.4 | 0.00 | -100 % | differs |
| river: sea-going, ships | E | 12.5 ± 2.2 | 0.00 | -100 % | differs |
| sea: inland, ships | E | 0.43 ± 0.27 | 0.00 | -100 % | differs |
| sea: sea-going, ships | E | 9.81 ± 1.75 | 0.00 | -100 % | differs |

## Piloted ships under way

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| dock, mean, ships | E | 2.86 ± 0.69 | 0.00 | -100 % | differs |
| dock, 95th percentile, ships | E | 6.33 ± 1.31 | 0.00 | -100 % | differs |
| river, mean, ships | E | 12.8 ± 2.2 | 0.00 | -100 % | differs |
| river, 95th percentile, ships | E | 19.1 ± 1.9 | 0.00 | -100 % | differs |
| sea, mean, ships | E | 10.8 ± 1.8 | 0.00 | -100 % | differs |
| sea, 95th percentile, ships | E | 16.0 ± 3.9 | 0.00 | -100 % | differs |

## Locks

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| Boudewijn-Van Cauwelaert: inland passing, a day | E | 84.3 ± 19.8 | 95.9 ± 6.6 | +14 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going passing, a day | E | 9.40 ± 1.71 | 9.56 ± 1.90 | +2 % | agrees |
| Hansweert: inland passing, a day | E | 88.1 ± 29.5 | 100 ± 4 | +14 % | agrees |
| Hansweert: sea-going passing, a day | E | 2.10 ± 1.87 | 0.00 | -100 % | differs |
| Kallo: inland passing, a day | E | 11.8 ± 2.1 | 23.6 ± 4.5 | +100 % | differs |
| Kallo: sea-going passing, a day | E | 3.21 ± 0.80 | 5.65 ± 1.94 | +76 % | differs |
| Kieldrecht: inland passing, a day | E | 23.1 ± 7.8 | 28.8 ± 3.0 | +25 % | agrees |
| Kieldrecht: sea-going passing, a day | E | 9.29 ± 3.67 | 8.69 ± 0.90 | -6 % | agrees |
| Kreekrak: inland passing, a day | E | 175 ± 28 | 170 ± 7 | -3 % | agrees |
| Kreekrak: sea-going passing, a day | E | 0.33 ± 0.65 | 0.00 | -100 % | agrees |
| Royers-Kattendijk: inland passing, a day | E | 1.10 ± 1.15 | 0.22 ± 0.28 | -80 % | agrees |
| Royers-Kattendijk: sea-going passing, a day | E | 0.00 | 0.07 ± 0.14 | +nan % | agrees |
| Terneuzen: inland passing, a day | E | 104 ± 31 | 124 ± 4 | +19 % | agrees |
| Terneuzen: sea-going passing, a day | E | 21.7 ± 5.1 | 20.4 ± 2.8 | -6 % | agrees |
| Zandvliet-Berendrecht: inland passing, a day | E | 53.1 ± 10.7 | 72.4 ± 1.4 | +36 % | differs |
| Zandvliet-Berendrecht: sea-going passing, a day | E | 35.8 ± 15.3 | 36.2 ± 3.5 | +1 % | agrees |
| Boudewijn-Van Cauwelaert: inland, time to pass, median, h | C | 1.08 ± 0.06 | 1.07 ± 0.02 | -1 % | agrees |
| Boudewijn-Van Cauwelaert: inland, time to pass, 90th percentile, h | C | 1.92 ± 0.36 | 1.72 ± 0.08 | -10 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going, time to pass, median, h | C | 1.43 ± 0.15 | 1.35 ± 0.07 | -6 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going, time to pass, 90th percentile, h | C | 1.93 ± 0.23 | 1.79 ± 0.17 | -7 % | agrees |
| Hansweert: inland, time to pass, median, h | C | 0.54 ± 0.04 | 0.71 ± 0.03 | +32 % | differs |
| Hansweert: inland, time to pass, 90th percentile, h | C | 0.83 ± 0.08 | 1.53 ± 0.11 | +83 % | differs |
| Kallo: inland, time to pass, median, h | C | 0.97 ± 0.22 | 0.97 ± 0.11 | +0 % | agrees |
| Kallo: inland, time to pass, 90th percentile, h | C | 2.16 ± 1.29 | 1.91 ± 0.34 | -12 % | agrees |
| Kallo: sea-going, time to pass, median, h | C | 1.04 ± 0.14 | 1.26 ± 0.15 | +21 % | differs |
| Kallo: sea-going, time to pass, 90th percentile, h | C | 1.14 ± 0.14 | 2.20 ± 0.98 | +92 % | differs |
| Kieldrecht: inland, time to pass, median, h | C | 0.83 ± 0.24 | 0.98 ± 0.11 | +18 % | agrees |
| Kieldrecht: inland, time to pass, 90th percentile, h | C | 2.23 ± 1.05 | 2.13 ± 0.25 | -4 % | agrees |
| Kieldrecht: sea-going, time to pass, median, h | C | 1.27 ± 0.13 | 1.50 ± 0.08 | +18 % | agrees |
| Kieldrecht: sea-going, time to pass, 90th percentile, h | C | 1.99 ± 0.36 | 2.01 ± 0.35 | +1 % | agrees |
| Kreekrak: inland, time to pass, median, h | C | 0.75 ± 0.04 | 0.76 ± 0.01 | +2 % | agrees |
| Kreekrak: inland, time to pass, 90th percentile, h | C | 1.19 ± 0.08 | 1.40 ± 0.11 | +17 % | agrees |
| Terneuzen: inland, time to pass, median, h | C | 0.86 ± 0.06 | 0.86 ± 0.00 | -0 % | agrees |
| Terneuzen: inland, time to pass, 90th percentile, h | C | 1.75 ± 0.28 | 1.68 ± 0.13 | -4 % | agrees |
| Terneuzen: sea-going, time to pass, median, h | C | 1.02 ± 0.06 | 0.96 ± 0.04 | -6 % | agrees |
| Terneuzen: sea-going, time to pass, 90th percentile, h | C | 1.27 ± 0.07 | 1.55 ± 0.14 | +22 % | differs |
| Zandvliet-Berendrecht: inland, time to pass, median, h | C | 1.09 ± 0.09 | 1.37 ± 0.07 | +25 % | differs |
| Zandvliet-Berendrecht: inland, time to pass, 90th percentile, h | C | 2.25 ± 0.47 | 2.73 ± 0.14 | +21 % | agrees |
| Zandvliet-Berendrecht: sea-going, time to pass, median, h | C | 1.75 ± 0.06 | 1.79 ± 0.04 | +2 % | agrees |
| Zandvliet-Berendrecht: sea-going, time to pass, 90th percentile, h | C | 2.17 ± 0.18 | 2.61 ± 0.06 | +20 % | differs |
| Boudewijn-Van Cauwelaert: inland, time to pass with the approaches (3 km either side), median, h | E | 1.58 ± 0.10 | 1.48 ± 0.03 | -6 % | agrees |
| Boudewijn-Van Cauwelaert: inland, time to pass with the approaches (3 km either side), 90th percentile, h | E | 2.27 ± 0.24 | 2.28 ± 0.19 | +1 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going, time to pass with the approaches (3 km either side), median, h | E | 1.72 ± 0.30 | 1.61 ± 0.06 | -6 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going, time to pass with the approaches (3 km either side), 90th percentile, h | E | 2.45 ± 0.72 | 2.10 ± 0.15 | -14 % | agrees |
| Hansweert: inland, time to pass with the approaches (3 km either side), median, h | E | 0.90 ± 0.04 | 1.08 ± 0.04 | +19 % | agrees |
| Hansweert: inland, time to pass with the approaches (3 km either side), 90th percentile, h | E | 1.25 ± 0.12 | 2.05 ± 0.12 | +63 % | differs |
| Kallo: inland, time to pass with the approaches (3 km either side), median, h | E | 1.38 ± 0.43 | 1.44 ± 0.12 | +4 % | agrees |
| Kallo: inland, time to pass with the approaches (3 km either side), 90th percentile, h | E | 1.78 ± 0.99 | 2.20 ± 0.19 | +24 % | agrees |
| Kallo: sea-going, time to pass with the approaches (3 km either side), median, h | E |  | 1.90 ± 0.14 |  |  |
| Kallo: sea-going, time to pass with the approaches (3 km either side), 90th percentile, h | E |  | 2.18 ± 0.25 |  |  |
| Terneuzen: inland, time to pass with the approaches (3 km either side), median, h | E | 1.34 ± 0.08 | 1.44 ± 0.03 | +8 % | agrees |
| Terneuzen: inland, time to pass with the approaches (3 km either side), 90th percentile, h | E | 2.45 ± 0.24 | 2.44 ± 0.07 | -1 % | agrees |
| Terneuzen: sea-going, time to pass with the approaches (3 km either side), median, h | E | 1.42 ± 0.09 | 1.33 ± 0.05 | -7 % | agrees |
| Terneuzen: sea-going, time to pass with the approaches (3 km either side), 90th percentile, h | E | 1.71 ± 0.11 | 1.94 ± 0.17 | +13 % | agrees |
| Zandvliet-Berendrecht: inland, time to pass with the approaches (3 km either side), median, h | E | 1.51 ± 0.14 | 2.06 ± 0.08 | +36 % | differs |
| Zandvliet-Berendrecht: inland, time to pass with the approaches (3 km either side), 90th percentile, h | E | 2.82 ± 0.73 | 3.74 ± 0.18 | +33 % | differs |
| Zandvliet-Berendrecht: sea-going, time to pass with the approaches (3 km either side), median, h | E | 2.08 ± 0.11 | 2.17 ± 0.05 | +4 % | agrees |
| Zandvliet-Berendrecht: sea-going, time to pass with the approaches (3 km either side), 90th percentile, h | E | 2.67 ± 0.13 | 3.07 ± 0.13 | +15 % | agrees |
| Hansweert: commercial passages, Rijkswaterstaat's count, a day | C | 113 ± nan | 101 ± 2 | -11 % | differs |
| Kreekrak: commercial passages, Rijkswaterstaat's count, a day | C | 189 ± nan | 171 ± 3 | -10 % | agrees |
| Terneuzen: commercial passages, Rijkswaterstaat's count, a day | C | 126 ± nan | 148 ± 3 | +17 % | differs |

## Ships in the area

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| bulk and general cargo ships at anchor, ships | C | 4.66 ± 1.41 | 5.12 ± 0.98 | +10 % | agrees |
| bulk and general cargo ships at a berth, ships | I | 45.6 ± 5.9 | 61.1 ± 3.9 | +34 % | differs |
| bulk and general cargo ships in the area, ships | E | 64.1 ± 9.8 | 83.1 ± 4.3 | +30 % | differs |
| container ships at anchor, ships | E | 1.32 ± 0.52 | 1.85 ± 0.29 | +40 % | agrees |
| container ships at a berth, ships | I | 14.4 ± 1.5 | 12.0 ± 1.2 | -17 % | differs |
| container ships in the area, ships | E | 22.7 ± 3.0 | 20.1 ± 1.3 | -12 % | agrees |
| inland cargo craft at anchor, ships | C | 0.21 ± 0.39 | 0.98 ± 0.21 | +364 % | differs |
| inland cargo craft at a berth, ships | C | 156 ± 7 | 161 ± 4 | +3 % | agrees |
| inland cargo craft in the area, ships | E | 205 ± 26 | 208 ± 4 | +1 % | agrees |
| inland tankers at anchor, ships | C | 1.04 ± 0.38 | 0.74 ± 0.29 | -29 % | agrees |
| inland tankers at a berth, ships | C | 127 ± 5 | 165 ± 6 | +30 % | differs |
| inland tankers in the area, ships | E | 169 ± 11 | 198 ± 7 | +17 % | differs |
| tankers at anchor, ships | C | 6.22 ± 1.02 | 10.5 ± 2.5 | +69 % | differs |
| tankers at a berth, ships | I | 37.8 ± 5.0 | 46.2 ± 6.2 | +22 % | differs |
| tankers in the area, ships | E | 61.8 ± 9.9 | 70.0 ± 9.2 | +13 % | agrees |

## Container ships

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| share that anchors before berthing | C | 0.13 ± 0.12 | 0.12 ± 0.08 | -7 % | agrees |
| at the four terminals, ships | E | 12.6 ± 1.2 | 9.54 ± 0.92 | -24 % | differs |
| berthing against the schedule, mean, h | C |  | 21.5 ± 10.1 |  |  |
| berthing against the schedule, standard deviation, h | I |  | 33.0 ± 6.9 |  |  |
| share berthing over 12 h after their planned time | E |  | 0.03 ± 0.03 |  |  |
| 3.10°E to the berth, median, h | E | 5.33 ± 44.03 | 5.02 ± 0.11 | -6 % | agrees |
| 3.10°E to the berth, 90th percentile, h | E | 412 ± 161 | 5.96 ± 0.71 | -99 % | differs |
| time at the berth, median, h | I | 19.8 ± 6.6 | 17.2 ± nan | -13 % | agrees |
