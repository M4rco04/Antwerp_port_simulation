# Validation of 0021_loss-fixes

AIS record 2026-11-13 00:00 to 2026-11-15 18:15 UTC, 796 snapshots, 3 whole days. Model: mean of 5 replications. ± is a 95 % interval (the record's from its day-to-day spread).
A number agrees when the difference is within twice its standard error or within the tolerance.

- emergent: 64 of 79 agree
- calibrated: 30 of 38 agree
- input: 3 of 5 agree

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
| km 8, off Vlissingen: inland, passages a day | E | 10.1 ± 3.0 | 11.2 ± 1.8 | +11 % | agrees |
| km 8, off Vlissingen: sea-going, passages a day | E | 107 ± 22 | 102 ± 3 | -5 % | agrees |
| km 32, Terneuzen to Hansweert: inland, passages a day | E | 160 ± 51 | 157 ± 4 | -2 % | agrees |
| km 32, Terneuzen to Hansweert: sea-going, passages a day | E | 82.1 ± 15.8 | 72.6 ± 3.0 | -12 % | agrees |
| km 48, Hansweert to Bath: inland, passages a day | E | 85.5 ± 27.5 | 93.0 ± 4.4 | +9 % | agrees |
| km 48, Hansweert to Bath: sea-going, passages a day | E | 81.3 ± 17.6 | 73.5 ± 3.3 | -10 % | agrees |
| km 62, Bath to the Zandvliet locks: inland, passages a day | E | 85.8 ± 28.9 | 93.5 ± 4.6 | +9 % | agrees |
| km 62, Bath to the Zandvliet locks: sea-going, passages a day | E | 82.6 ± 17.9 | 73.3 ± 3.7 | -11 % | agrees |
| km 68, Zandvliet to Deurganckdok: inland, passages a day | E | 125 ± 36 | 115 ± 9 | -8 % | agrees |
| km 68, Zandvliet to Deurganckdok: sea-going, passages a day | E | 47.9 ± 7.0 | 40.5 ± 3.4 | -15 % | agrees |
| km 72, Deurganckdok to Boudewijn: inland, passages a day | E | 99.2 ± 41.9 | 86.3 ± 7.5 | -13 % | agrees |
| km 72, Deurganckdok to Boudewijn: sea-going, passages a day | E | 22.7 ± 6.4 | 21.5 ± 2.3 | -5 % | agrees |
| km 80, Kallo to Antwerp: inland, passages a day | E | 38.5 ± 24.2 | 41.6 ± 5.6 | +8 % | agrees |
| km 80, Kallo to Antwerp: sea-going, passages a day | E | 1.98 ± 2.23 | 4.71 ± 1.27 | +138 % | differs |
| km 88, above Antwerp: inland, passages a day | E | 35.4 ± 25.1 | 37.2 ± 5.1 | +5 % | agrees |
| km 88, above Antwerp: sea-going, passages a day | E | 1.54 ± 1.55 | 3.12 ± 1.22 | +102 % | agrees |
| sea, 3.10°E (Wandelaar to Wielingen): sea-going, passages a day | E | 83.5 ± 7.8 | 70.5 ± 4.2 | -16 % | differs |
| sea-going ships calling at Antwerp (the port's statistics, 2020 and 2021), a day | E | 38.1 ± 1.6 | 34.8 ± 3.4 | -9 % | agrees |

## Sailing times

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| sea-going, km 8 to km 62, median, h | C | 2.58 ± 0.17 | 2.70 ± 0.07 | +5 % | agrees |
| sea-going, km 8 to km 62, 90th percentile, h | E | 3.46 ± 0.27 | 3.22 ± 0.10 | -7 % | agrees |
| sea-going, km 62 to km 8, median, h | C | 2.50 ± 0.11 | 2.52 ± 0.07 | +1 % | agrees |
| sea-going, km 62 to km 8, 90th percentile, h | E | 3.08 ± 0.19 | 3.21 ± 0.25 | +4 % | agrees |
| inland, km 32 to km 48, median, h | E | 1.08 ± 0.10 | 1.15 ± 0.03 | +6 % | agrees |
| inland, km 32 to km 48, 90th percentile, h | E | 1.58 ± 0.12 | 1.53 ± 0.07 | -3 % | agrees |
| inland, km 48 to km 32, median, h | E | 1.08 ± 0.09 | 1.20 ± 0.04 | +11 % | differs |
| inland, km 48 to km 32, 90th percentile, h | E | 1.52 ± 0.22 | 1.55 ± 0.11 | +2 % | agrees |
| sea-going, sea to km 8, median, h | C | 1.83 ± 0.13 | 1.88 ± 0.07 | +3 % | agrees |
| sea-going, sea to km 8, 90th percentile, h | E | 2.17 ± 0.11 | 2.55 ± 0.75 | +18 % | agrees |
| sea-going, km 8 to sea, median, h | C | 1.75 ± 0.09 | 1.69 ± 0.03 | -3 % | agrees |
| sea-going, km 8 to sea, 90th percentile, h | E | 2.58 ± 0.38 | 1.98 ± 0.03 | -23 % | differs |

## Ships under way

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| dock: inland, ships | E | 23.1 ± 4.9 | 26.7 ± 0.8 | +16 % | agrees |
| dock: sea-going, ships | E | 2.58 ± 0.79 | 3.36 ± 0.13 | +31 % | agrees |
| river: inland, ships | E | 20.5 ± 6.4 | 24.2 ± 1.4 | +18 % | agrees |
| river: sea-going, ships | E | 12.5 ± 2.2 | 11.4 ± 0.5 | -9 % | agrees |
| sea: inland, ships | E | 0.43 ± 0.27 | 0.79 ± 0.15 | +83 % | differs |
| sea: sea-going, ships | E | 9.81 ± 1.75 | 10.2 ± 0.8 | +4 % | agrees |

## Piloted ships under way

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| dock, mean, ships | E | 2.86 ± 0.69 | 3.34 ± 0.13 | +17 % | agrees |
| dock, 95th percentile, ships | E | 6.33 ± 1.31 | 6.80 ± 0.39 | +7 % | agrees |
| river, mean, ships | E | 12.8 ± 2.2 | 11.3 ± 0.4 | -11 % | agrees |
| river, 95th percentile, ships | E | 19.1 ± 1.9 | 18.6 ± 1.3 | -2 % | agrees |
| sea, mean, ships | E | 10.8 ± 1.8 | 11.7 ± 0.9 | +8 % | agrees |
| sea, 95th percentile, ships | E | 16.0 ± 3.9 | 18.9 ± 3.3 | +18 % | agrees |

## Locks

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| Boudewijn-Van Cauwelaert: inland passing, a day | E | 84.3 ± 19.8 | 92.7 ± 6.0 | +10 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going passing, a day | E | 9.40 ± 1.71 | 10.1 ± 2.1 | +7 % | agrees |
| Hansweert: inland passing, a day | E | 88.1 ± 29.5 | 100 ± 7 | +14 % | agrees |
| Hansweert: sea-going passing, a day | E | 2.10 ± 1.87 | 0.22 ± 0.17 | -90 % | agrees |
| Kallo: inland passing, a day | E | 11.8 ± 2.1 | 21.6 ± 3.8 | +82 % | differs |
| Kallo: sea-going passing, a day | E | 3.21 ± 0.80 | 5.87 ± 1.64 | +83 % | differs |
| Kieldrecht: inland passing, a day | E | 23.1 ± 7.8 | 28.3 ± 3.0 | +22 % | agrees |
| Kieldrecht: sea-going passing, a day | E | 9.29 ± 3.67 | 8.98 ± 1.51 | -3 % | agrees |
| Kreekrak: inland passing, a day | E | 175 ± 28 | 171 ± 6 | -2 % | agrees |
| Kreekrak: sea-going passing, a day | E | 0.33 ± 0.65 | 0.00 | -100 % | agrees |
| Royers-Kattendijk: inland passing, a day | E | 1.10 ± 1.15 | 0.43 ± 0.57 | -61 % | agrees |
| Royers-Kattendijk: sea-going passing, a day | E | 0.00 | 0.14 ± 0.28 | +nan % | agrees |
| Terneuzen: inland passing, a day | E | 104 ± 31 | 126 ± 5 | +21 % | agrees |
| Terneuzen: sea-going passing, a day | E | 21.7 ± 5.1 | 21.9 ± 1.6 | +1 % | agrees |
| Zandvliet-Berendrecht: inland passing, a day | E | 53.1 ± 10.7 | 78.8 ± 3.0 | +48 % | differs |
| Zandvliet-Berendrecht: sea-going passing, a day | E | 35.8 ± 15.3 | 37.1 ± 1.7 | +3 % | agrees |
| Boudewijn-Van Cauwelaert: inland, time to pass, median, h | C | 1.08 ± 0.06 | 1.07 ± 0.06 | -1 % | agrees |
| Boudewijn-Van Cauwelaert: inland, time to pass, 90th percentile, h | C | 1.92 ± 0.36 | 1.78 ± 0.20 | -7 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going, time to pass, median, h | C | 1.43 ± 0.15 | 1.30 ± 0.09 | -9 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going, time to pass, 90th percentile, h | C | 1.93 ± 0.23 | 1.63 ± 0.15 | -16 % | agrees |
| Hansweert: inland, time to pass, median, h | C | 0.54 ± 0.04 | 0.72 ± 0.04 | +34 % | differs |
| Hansweert: inland, time to pass, 90th percentile, h | C | 0.83 ± 0.08 | 1.18 ± 0.03 | +41 % | differs |
| Kallo: inland, time to pass, median, h | C | 0.97 ± 0.22 | 0.94 ± 0.12 | -3 % | agrees |
| Kallo: inland, time to pass, 90th percentile, h | C | 2.16 ± 1.29 | 1.70 ± 0.15 | -21 % | agrees |
| Kallo: sea-going, time to pass, median, h | C | 1.04 ± 0.14 | 1.18 ± 0.01 | +13 % | agrees |
| Kallo: sea-going, time to pass, 90th percentile, h | C | 1.14 ± 0.14 | 1.90 ± 0.20 | +67 % | differs |
| Kieldrecht: inland, time to pass, median, h | C | 0.83 ± 0.24 | 1.03 ± 0.14 | +23 % | agrees |
| Kieldrecht: inland, time to pass, 90th percentile, h | C | 2.23 ± 1.05 | 2.24 ± 0.40 | +0 % | agrees |
| Kieldrecht: sea-going, time to pass, median, h | C | 1.27 ± 0.13 | 1.32 ± 0.15 | +3 % | agrees |
| Kieldrecht: sea-going, time to pass, 90th percentile, h | C | 1.99 ± 0.36 | 2.03 ± 0.54 | +2 % | agrees |
| Kreekrak: inland, time to pass, median, h | C | 0.75 ± 0.04 | 0.66 ± 0.02 | -12 % | agrees |
| Kreekrak: inland, time to pass, 90th percentile, h | C | 1.19 ± 0.08 | 1.30 ± 0.07 | +9 % | agrees |
| Terneuzen: inland, time to pass, median, h | C | 0.86 ± 0.06 | 0.76 ± 0.00 | -12 % | agrees |
| Terneuzen: inland, time to pass, 90th percentile, h | C | 1.75 ± 0.28 | 1.64 ± 0.12 | -6 % | agrees |
| Terneuzen: sea-going, time to pass, median, h | C | 1.02 ± 0.06 | 0.91 ± 0.01 | -11 % | agrees |
| Terneuzen: sea-going, time to pass, 90th percentile, h | C | 1.27 ± 0.07 | 1.50 ± 0.13 | +18 % | agrees |
| Zandvliet-Berendrecht: inland, time to pass, median, h | C | 1.09 ± 0.09 | 1.24 ± 0.07 | +14 % | agrees |
| Zandvliet-Berendrecht: inland, time to pass, 90th percentile, h | C | 2.25 ± 0.47 | 2.64 ± 0.19 | +17 % | agrees |
| Zandvliet-Berendrecht: sea-going, time to pass, median, h | C | 1.75 ± 0.06 | 1.67 ± 0.08 | -5 % | agrees |
| Zandvliet-Berendrecht: sea-going, time to pass, 90th percentile, h | C | 2.17 ± 0.18 | 2.53 ± 0.17 | +17 % | agrees |
| Boudewijn-Van Cauwelaert: inland, time to pass with the approaches (3 km either side), median, h | E | 1.58 ± 0.10 | 1.51 ± 0.05 | -5 % | agrees |
| Boudewijn-Van Cauwelaert: inland, time to pass with the approaches (3 km either side), 90th percentile, h | E | 2.27 ± 0.24 | 2.43 ± 0.18 | +7 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going, time to pass with the approaches (3 km either side), median, h | E | 1.72 ± 0.30 | 1.64 ± 0.09 | -5 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going, time to pass with the approaches (3 km either side), 90th percentile, h | E | 2.45 ± 0.72 | 1.99 ± 0.11 | -19 % | agrees |
| Hansweert: inland, time to pass with the approaches (3 km either side), median, h | E | 0.90 ± 0.04 | 1.21 ± 0.04 | +33 % | differs |
| Hansweert: inland, time to pass with the approaches (3 km either side), 90th percentile, h | E | 1.25 ± 0.12 | 1.64 ± 0.03 | +31 % | differs |
| Kallo: inland, time to pass with the approaches (3 km either side), median, h | E | 1.38 ± 0.43 | 1.39 ± 0.09 | +0 % | agrees |
| Kallo: inland, time to pass with the approaches (3 km either side), 90th percentile, h | E | 1.78 ± 0.99 | 2.09 ± 0.15 | +17 % | agrees |
| Kallo: sea-going, time to pass with the approaches (3 km either side), median, h | E |  | 1.84 ± 0.15 |  |  |
| Kallo: sea-going, time to pass with the approaches (3 km either side), 90th percentile, h | E |  | 2.27 ± 0.14 |  |  |
| Terneuzen: inland, time to pass with the approaches (3 km either side), median, h | E | 1.34 ± 0.08 | 1.39 ± 0.05 | +4 % | agrees |
| Terneuzen: inland, time to pass with the approaches (3 km either side), 90th percentile, h | E | 2.45 ± 0.24 | 2.48 ± 0.13 | +1 % | agrees |
| Terneuzen: sea-going, time to pass with the approaches (3 km either side), median, h | E | 1.42 ± 0.09 | 1.35 ± 0.03 | -5 % | agrees |
| Terneuzen: sea-going, time to pass with the approaches (3 km either side), 90th percentile, h | E | 1.71 ± 0.11 | 2.00 ± 0.18 | +17 % | agrees |
| Zandvliet-Berendrecht: inland, time to pass with the approaches (3 km either side), median, h | E | 1.51 ± 0.14 | 2.07 ± 0.10 | +36 % | differs |
| Zandvliet-Berendrecht: inland, time to pass with the approaches (3 km either side), 90th percentile, h | E | 2.82 ± 0.73 | 3.69 ± 0.09 | +31 % | differs |
| Zandvliet-Berendrecht: sea-going, time to pass with the approaches (3 km either side), median, h | E | 2.08 ± 0.11 | 2.11 ± 0.04 | +1 % | agrees |
| Zandvliet-Berendrecht: sea-going, time to pass with the approaches (3 km either side), 90th percentile, h | E | 2.67 ± 0.13 | 3.02 ± 0.10 | +13 % | agrees |
| Hansweert: commercial passages, Rijkswaterstaat's count, a day | C | 113 ± nan | 101 ± 2 | -11 % | differs |
| Kreekrak: commercial passages, Rijkswaterstaat's count, a day | C | 189 ± nan | 171 ± 4 | -9 % | agrees |
| Terneuzen: commercial passages, Rijkswaterstaat's count, a day | C | 126 ± nan | 147 ± 2 | +17 % | differs |

## Ships in the area

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| bulk and general cargo ships at anchor, ships | C | 4.66 ± 1.41 | 3.85 ± 1.22 | -17 % | agrees |
| bulk and general cargo ships at a berth, ships | I | 45.6 ± 5.9 | 61.0 ± 2.3 | +34 % | differs |
| bulk and general cargo ships in the area, ships | E | 64.1 ± 9.8 | 80.3 ± 2.5 | +25 % | differs |
| container ships at anchor, ships | E | 1.32 ± 0.52 | 1.87 ± 0.32 | +42 % | agrees |
| container ships at a berth, ships | I | 14.4 ± 1.5 | 11.8 ± 1.6 | -18 % | differs |
| container ships in the area, ships | E | 22.7 ± 3.0 | 19.6 ± 1.7 | -14 % | agrees |
| inland cargo craft at anchor, ships | C | 0.21 ± 0.39 | 1.17 ± 0.25 | +453 % | differs |
| inland cargo craft at a berth, ships | C | 156 ± 7 | 157 ± 11 | +0 % | agrees |
| inland cargo craft in the area, ships | E | 205 ± 26 | 204 ± 13 | -1 % | agrees |
| inland tankers at anchor, ships | C | 1.04 ± 0.38 | 0.74 ± 0.19 | -28 % | agrees |
| inland tankers at a berth, ships | C | 127 ± 5 | 158 ± 11 | +24 % | differs |
| inland tankers in the area, ships | E | 169 ± 11 | 190 ± 11 | +13 % | agrees |
| tankers at anchor, ships | C | 6.22 ± 1.02 | 9.42 ± 2.16 | +51 % | differs |
| tankers at a berth, ships | I | 37.8 ± 5.0 | 42.0 ± 4.6 | +11 % | agrees |
| tankers in the area, ships | E | 61.8 ± 9.9 | 65.0 ± 4.8 | +5 % | agrees |

## Container ships

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| share that anchors before berthing | C | 0.13 ± 0.12 | 0.12 ± 0.08 | -7 % | agrees |
| at the four terminals, ships | E | 12.6 ± 1.2 | 9.38 ± 1.16 | -26 % | differs |
| berthing against the schedule, mean, h | C |  | 21.3 ± 9.9 |  |  |
| berthing against the schedule, standard deviation, h | I |  | 32.7 ± 7.2 |  |  |
| share berthing over 12 h after their planned time | E |  | 0.02 ± 0.03 |  |  |
| 3.10°E to the berth, median, h | E | 5.33 ± 44.03 | 4.99 ± 0.14 | -6 % | agrees |
| 3.10°E to the berth, 90th percentile, h | E | 412 ± 161 | 6.17 ± 0.86 | -98 % | differs |
| time at the berth, median, h | I | 19.8 ± 6.6 | 17.0 ± nan | -14 % | agrees |
