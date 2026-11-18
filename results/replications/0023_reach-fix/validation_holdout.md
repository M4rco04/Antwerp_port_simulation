# Validation of 0023_reach-fix

AIS record 2026-11-13 00:00 to 2026-11-15 18:15 UTC, 796 snapshots, 3 whole days. Model: mean of 5 replications. ± is a 95 % interval (the record's from its day-to-day spread).
A number agrees when the difference is within twice its standard error or within the tolerance.

- emergent: 62 of 79 agree
- calibrated: 30 of 38 agree
- input: 3 of 5 agree

## Arrivals

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| bulk and general cargo ships entering, a day | I |  | 28.5 ± 2.8 |  |  |
| container ships entering, a day | I | 8.29 ± 3.40 | 8.40 ± 1.41 | +1 % | agrees |
| inland cargo craft entering, a day | I |  | 143 ± 5 |  |  |
| inland tankers entering, a day | I |  | 94.8 ± 7.1 |  |  |
| passenger ships entering, a day | I |  | 5.14 ± 0.61 |  |  |
| tankers entering, a day | I |  | 18.9 ± 2.4 |  |  |

## River traffic

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| km 8, off Vlissingen: inland, passages a day | E | 10.1 ± 3.0 | 8.62 ± 1.41 | -14 % | agrees |
| km 8, off Vlissingen: sea-going, passages a day | E | 107 ± 22 | 98.5 ± 4.8 | -8 % | agrees |
| km 32, Terneuzen to Hansweert: inland, passages a day | E | 160 ± 51 | 155 ± 2 | -3 % | agrees |
| km 32, Terneuzen to Hansweert: sea-going, passages a day | E | 82.1 ± 15.8 | 69.6 ± 3.8 | -15 % | agrees |
| km 48, Hansweert to Bath: inland, passages a day | E | 85.5 ± 27.5 | 91.6 ± 2.9 | +7 % | agrees |
| km 48, Hansweert to Bath: sea-going, passages a day | E | 81.3 ± 17.6 | 69.9 ± 4.2 | -14 % | agrees |
| km 62, Bath to the Zandvliet locks: inland, passages a day | E | 85.8 ± 28.9 | 91.2 ± 3.2 | +6 % | agrees |
| km 62, Bath to the Zandvliet locks: sea-going, passages a day | E | 82.6 ± 17.9 | 70.1 ± 4.3 | -15 % | agrees |
| km 68, Zandvliet to Deurganckdok: inland, passages a day | E | 125 ± 36 | 115 ± 2 | -8 % | agrees |
| km 68, Zandvliet to Deurganckdok: sea-going, passages a day | E | 47.9 ± 7.0 | 38.1 ± 3.2 | -20 % | differs |
| km 72, Deurganckdok to Boudewijn: inland, passages a day | E | 99.2 ± 41.9 | 88.8 ± 4.6 | -10 % | agrees |
| km 72, Deurganckdok to Boudewijn: sea-going, passages a day | E | 22.7 ± 6.4 | 20.7 ± 1.8 | -9 % | agrees |
| km 80, Kallo to Antwerp: inland, passages a day | E | 38.5 ± 24.2 | 43.5 ± 4.7 | +13 % | agrees |
| km 80, Kallo to Antwerp: sea-going, passages a day | E | 1.98 ± 2.23 | 4.64 ± 0.85 | +134 % | differs |
| km 88, above Antwerp: inland, passages a day | E | 35.4 ± 25.1 | 39.1 ± 5.5 | +11 % | agrees |
| km 88, above Antwerp: sea-going, passages a day | E | 1.54 ± 1.55 | 2.61 ± 0.76 | +69 % | agrees |
| sea, 3.10°E (Wandelaar to Wielingen): sea-going, passages a day | E | 83.5 ± 7.8 | 67.2 ± 4.1 | -19 % | differs |
| sea-going ships calling at Antwerp (the port's statistics, 2020 and 2021), a day | E | 38.1 ± 1.6 | 35.6 ± 2.3 | -6 % | agrees |

## Sailing times

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| sea-going, km 8 to km 62, median, h | C | 2.58 ± 0.17 | 2.72 ± 0.04 | +5 % | agrees |
| sea-going, km 8 to km 62, 90th percentile, h | E | 3.46 ± 0.27 | 3.31 ± 0.07 | -4 % | agrees |
| sea-going, km 62 to km 8, median, h | C | 2.50 ± 0.11 | 2.57 ± 0.06 | +3 % | agrees |
| sea-going, km 62 to km 8, 90th percentile, h | E | 3.08 ± 0.19 | 3.13 ± 0.15 | +2 % | agrees |
| inland, km 32 to km 48, median, h | E | 1.08 ± 0.10 | 1.17 | +8 % | agrees |
| inland, km 32 to km 48, 90th percentile, h | E | 1.58 ± 0.12 | 1.51 ± 0.10 | -5 % | agrees |
| inland, km 48 to km 32, median, h | E | 1.08 ± 0.09 | 1.20 ± 0.04 | +11 % | differs |
| inland, km 48 to km 32, 90th percentile, h | E | 1.52 ± 0.22 | 1.63 ± 0.18 | +8 % | agrees |
| sea-going, sea to km 8, median, h | C | 1.83 ± 0.13 | 1.88 ± 0.07 | +3 % | agrees |
| sea-going, sea to km 8, 90th percentile, h | E | 2.17 ± 0.11 | 2.49 ± 0.68 | +15 % | agrees |
| sea-going, km 8 to sea, median, h | C | 1.75 ± 0.09 | 1.68 ± 0.03 | -4 % | agrees |
| sea-going, km 8 to sea, 90th percentile, h | E | 2.58 ± 0.38 | 1.97 ± 0.06 | -24 % | differs |

## Ships under way

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| dock: inland, ships | E | 23.1 ± 4.9 | 27.1 ± 0.9 | +17 % | agrees |
| dock: sea-going, ships | E | 2.58 ± 0.79 | 3.10 ± 0.30 | +20 % | agrees |
| river: inland, ships | E | 20.5 ± 6.4 | 23.8 ± 0.4 | +16 % | agrees |
| river: sea-going, ships | E | 12.5 ± 2.2 | 11.0 ± 0.8 | -12 % | agrees |
| sea: inland, ships | E | 0.43 ± 0.27 | 0.39 ± 0.08 | -9 % | agrees |
| sea: sea-going, ships | E | 9.81 ± 1.75 | 9.73 ± 0.74 | -1 % | agrees |

## Piloted ships under way

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| dock, mean, ships | E | 2.86 ± 0.69 | 3.07 ± 0.28 | +7 % | agrees |
| dock, 95th percentile, ships | E | 6.33 ± 1.31 | 6.20 ± 0.73 | -2 % | agrees |
| river, mean, ships | E | 12.8 ± 2.2 | 11.0 ± 0.8 | -14 % | agrees |
| river, 95th percentile, ships | E | 19.1 ± 1.9 | 16.6 ± 2.5 | -13 % | agrees |
| sea, mean, ships | E | 10.8 ± 1.8 | 11.2 ± 0.8 | +4 % | agrees |
| sea, 95th percentile, ships | E | 16.0 ± 3.9 | 17.6 ± 2.0 | +10 % | agrees |

## Locks

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| Boudewijn-Van Cauwelaert: inland passing, a day | E | 84.3 ± 19.8 | 96.3 ± 2.4 | +14 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going passing, a day | E | 9.40 ± 1.71 | 10.6 ± 1.9 | +13 % | agrees |
| Hansweert: inland passing, a day | E | 88.1 ± 29.5 | 101 ± 3 | +14 % | agrees |
| Hansweert: sea-going passing, a day | E | 2.10 ± 1.87 | 0.00 | -100 % | differs |
| Kallo: inland passing, a day | E | 11.8 ± 2.1 | 27.0 ± 2.9 | +128 % | differs |
| Kallo: sea-going passing, a day | E | 3.21 ± 0.80 | 4.93 ± 1.11 | +54 % | differs |
| Kieldrecht: inland passing, a day | E | 23.1 ± 7.8 | 28.9 ± 2.6 | +25 % | agrees |
| Kieldrecht: sea-going passing, a day | E | 9.29 ± 3.67 | 7.39 ± 0.99 | -20 % | agrees |
| Kreekrak: inland passing, a day | E | 175 ± 28 | 173 ± 10 | -1 % | agrees |
| Kreekrak: sea-going passing, a day | E | 0.33 ± 0.65 | 0.00 | -100 % | agrees |
| Royers-Kattendijk: inland passing, a day | E | 1.10 ± 1.15 | 0.14 ± 0.28 | -87 % | agrees |
| Royers-Kattendijk: sea-going passing, a day | E | 0.00 | 0.22 ± 0.28 | +nan % | agrees |
| Terneuzen: inland passing, a day | E | 104 ± 31 | 123 ± 4 | +17 % | agrees |
| Terneuzen: sea-going passing, a day | E | 21.7 ± 5.1 | 20.6 ± 2.3 | -5 % | agrees |
| Zandvliet-Berendrecht: inland passing, a day | E | 53.1 ± 10.7 | 74.8 ± 6.2 | +41 % | differs |
| Zandvliet-Berendrecht: sea-going passing, a day | E | 35.8 ± 15.3 | 33.5 ± 3.4 | -6 % | agrees |
| Boudewijn-Van Cauwelaert: inland, time to pass, median, h | C | 1.08 ± 0.06 | 1.10 ± 0.03 | +2 % | agrees |
| Boudewijn-Van Cauwelaert: inland, time to pass, 90th percentile, h | C | 1.92 ± 0.36 | 1.83 ± 0.19 | -4 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going, time to pass, median, h | C | 1.43 ± 0.15 | 1.23 ± 0.09 | -14 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going, time to pass, 90th percentile, h | C | 1.93 ± 0.23 | 1.54 ± 0.12 | -20 % | differs |
| Hansweert: inland, time to pass, median, h | C | 0.54 ± 0.04 | 0.74 ± 0.02 | +37 % | differs |
| Hansweert: inland, time to pass, 90th percentile, h | C | 0.83 ± 0.08 | 1.18 ± 0.02 | +42 % | differs |
| Kallo: inland, time to pass, median, h | C | 0.97 ± 0.22 | 0.97 ± 0.07 | -0 % | agrees |
| Kallo: inland, time to pass, 90th percentile, h | C | 2.16 ± 1.29 | 1.89 ± 0.17 | -12 % | agrees |
| Kallo: sea-going, time to pass, median, h | C | 1.04 ± 0.14 | 1.22 ± nan | +17 % | agrees |
| Kallo: sea-going, time to pass, 90th percentile, h | C | 1.14 ± 0.14 | 1.36 ± nan | +19 % | agrees |
| Kieldrecht: inland, time to pass, median, h | C | 0.83 ± 0.24 | 0.89 ± 0.07 | +6 % | agrees |
| Kieldrecht: inland, time to pass, 90th percentile, h | C | 2.23 ± 1.05 | 2.04 ± 0.32 | -9 % | agrees |
| Kieldrecht: sea-going, time to pass, median, h | C | 1.27 ± 0.13 | 1.34 ± 0.10 | +5 % | agrees |
| Kieldrecht: sea-going, time to pass, 90th percentile, h | C | 1.99 ± 0.36 | 1.81 ± 0.31 | -9 % | agrees |
| Kreekrak: inland, time to pass, median, h | C | 0.75 ± 0.04 | 0.68 ± 0.03 | -9 % | agrees |
| Kreekrak: inland, time to pass, 90th percentile, h | C | 1.19 ± 0.08 | 1.36 ± 0.12 | +14 % | agrees |
| Terneuzen: inland, time to pass, median, h | C | 0.86 ± 0.06 | 0.76 ± 0.01 | -12 % | agrees |
| Terneuzen: inland, time to pass, 90th percentile, h | C | 1.75 ± 0.28 | 1.62 ± 0.22 | -7 % | agrees |
| Terneuzen: sea-going, time to pass, median, h | C | 1.02 ± 0.06 | 0.90 ± 0.05 | -12 % | agrees |
| Terneuzen: sea-going, time to pass, 90th percentile, h | C | 1.27 ± 0.07 | 1.37 ± 0.20 | +8 % | agrees |
| Zandvliet-Berendrecht: inland, time to pass, median, h | C | 1.09 ± 0.09 | 1.22 ± 0.08 | +12 % | agrees |
| Zandvliet-Berendrecht: inland, time to pass, 90th percentile, h | C | 2.25 ± 0.47 | 2.46 ± 0.26 | +9 % | agrees |
| Zandvliet-Berendrecht: sea-going, time to pass, median, h | C | 1.75 ± 0.06 | 1.66 ± 0.06 | -5 % | agrees |
| Zandvliet-Berendrecht: sea-going, time to pass, 90th percentile, h | C | 2.17 ± 0.18 | 2.48 ± 0.19 | +14 % | agrees |
| Boudewijn-Van Cauwelaert: inland, time to pass with the approaches (3 km either side), median, h | E | 1.58 ± 0.10 | 1.50 ± 0.06 | -5 % | agrees |
| Boudewijn-Van Cauwelaert: inland, time to pass with the approaches (3 km either side), 90th percentile, h | E | 2.27 ± 0.24 | 2.41 ± 0.23 | +6 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going, time to pass with the approaches (3 km either side), median, h | E | 1.72 ± 0.30 | 1.63 ± 0.09 | -6 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going, time to pass with the approaches (3 km either side), 90th percentile, h | E | 2.45 ± 0.72 | 1.95 ± 0.14 | -20 % | agrees |
| Hansweert: inland, time to pass with the approaches (3 km either side), median, h | E | 0.90 ± 0.04 | 1.18 ± 0.01 | +31 % | differs |
| Hansweert: inland, time to pass with the approaches (3 km either side), 90th percentile, h | E | 1.25 ± 0.12 | 1.64 ± 0.03 | +30 % | differs |
| Kallo: inland, time to pass with the approaches (3 km either side), median, h | E | 1.38 ± 0.43 | 1.53 ± 0.11 | +11 % | agrees |
| Kallo: inland, time to pass with the approaches (3 km either side), 90th percentile, h | E | 1.78 ± 0.99 | 2.44 ± 0.30 | +37 % | agrees |
| Kallo: sea-going, time to pass with the approaches (3 km either side), median, h | E |  | 1.90 ± 0.13 |  |  |
| Kallo: sea-going, time to pass with the approaches (3 km either side), 90th percentile, h | E |  | 2.48 ± 0.26 |  |  |
| Terneuzen: inland, time to pass with the approaches (3 km either side), median, h | E | 1.34 ± 0.08 | 1.47 ± 0.04 | +10 % | agrees |
| Terneuzen: inland, time to pass with the approaches (3 km either side), 90th percentile, h | E | 2.45 ± 0.24 | 2.56 ± 0.19 | +4 % | agrees |
| Terneuzen: sea-going, time to pass with the approaches (3 km either side), median, h | E | 1.42 ± 0.09 | 1.32 ± 0.05 | -7 % | agrees |
| Terneuzen: sea-going, time to pass with the approaches (3 km either side), 90th percentile, h | E | 1.71 ± 0.11 | 1.91 ± 0.13 | +12 % | agrees |
| Zandvliet-Berendrecht: inland, time to pass with the approaches (3 km either side), median, h | E | 1.51 ± 0.14 | 1.98 ± 0.12 | +31 % | differs |
| Zandvliet-Berendrecht: inland, time to pass with the approaches (3 km either side), 90th percentile, h | E | 2.82 ± 0.73 | 3.72 ± 0.38 | +32 % | differs |
| Zandvliet-Berendrecht: sea-going, time to pass with the approaches (3 km either side), median, h | E | 2.08 ± 0.11 | 2.08 ± 0.03 | -0 % | agrees |
| Zandvliet-Berendrecht: sea-going, time to pass with the approaches (3 km either side), 90th percentile, h | E | 2.67 ± 0.13 | 2.91 ± 0.10 | +9 % | agrees |
| Hansweert: commercial passages, Rijkswaterstaat's count, a day | C | 113 ± nan | 102 ± 3 | -10 % | agrees |
| Kreekrak: commercial passages, Rijkswaterstaat's count, a day | C | 189 ± nan | 173 ± 2 | -9 % | agrees |
| Terneuzen: commercial passages, Rijkswaterstaat's count, a day | C | 126 ± nan | 147 ± 2 | +17 % | differs |

## Ships in the area

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| bulk and general cargo ships at anchor, ships | C | 4.66 ± 1.41 | 4.00 ± 1.87 | -14 % | agrees |
| bulk and general cargo ships at a berth, ships | I | 45.6 ± 5.9 | 56.5 ± 2.6 | +24 % | differs |
| bulk and general cargo ships in the area, ships | E | 64.1 ± 9.8 | 75.0 ± 3.4 | +17 % | differs |
| container ships at anchor, ships | E | 1.32 ± 0.52 | 1.85 ± 0.39 | +40 % | agrees |
| container ships at a berth, ships | I | 14.4 ± 1.5 | 11.9 ± 1.6 | -18 % | differs |
| container ships in the area, ships | E | 22.7 ± 3.0 | 19.6 ± 2.0 | -14 % | agrees |
| inland cargo craft at anchor, ships | C | 0.21 ± 0.39 | 1.30 ± 0.33 | +515 % | differs |
| inland cargo craft at a berth, ships | C | 156 ± 7 | 161 ± 5 | +3 % | agrees |
| inland cargo craft in the area, ships | E | 205 ± 26 | 207 ± 6 | +1 % | agrees |
| inland tankers at anchor, ships | C | 1.04 ± 0.38 | 0.55 ± 0.16 | -47 % | differs |
| inland tankers at a berth, ships | C | 127 ± 5 | 163 ± 7 | +28 % | differs |
| inland tankers in the area, ships | E | 169 ± 11 | 196 ± 8 | +16 % | differs |
| tankers at anchor, ships | C | 6.22 ± 1.02 | 11.2 ± 3.0 | +80 % | differs |
| tankers at a berth, ships | I | 37.8 ± 5.0 | 42.0 ± 4.6 | +11 % | agrees |
| tankers in the area, ships | E | 61.8 ± 9.9 | 65.6 ± 8.3 | +6 % | agrees |

## Container ships

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| share that anchors before berthing | C | 0.13 ± 0.12 | 0.12 ± 0.08 | -9 % | agrees |
| at the four terminals, ships | E | 12.6 ± 1.2 | 9.36 ± 1.09 | -26 % | differs |
| berthing against the schedule, mean, h | C |  | 21.9 ± 10.1 |  |  |
| berthing against the schedule, standard deviation, h | I |  | 32.2 ± 7.2 |  |  |
| share berthing over 12 h after their planned time | E |  | 0.04 ± 0.03 |  |  |
| 3.10°E to the berth, median, h | E | 5.33 ± 44.03 | 5.06 ± 0.10 | -5 % | agrees |
| 3.10°E to the berth, 90th percentile, h | E | 412 ± 161 | 6.36 ± 0.84 | -98 % | differs |
| time at the berth, median, h | I | 19.8 ± 6.6 | 17.2 ± nan | -13 % | agrees |
