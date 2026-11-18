# Validation of 0030_weekday

AIS record 2026-11-13 00:00 to 2026-11-15 18:15 UTC, 796 snapshots, 3 whole days. Model: mean of 5 replications. ± is a 95 % interval (the record's from its day-to-day spread).
A number agrees when the difference is within twice its standard error or within the tolerance.

- emergent: 62 of 79 agree
- calibrated: 31 of 38 agree
- input: 2 of 4 agree

## Arrivals

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| bulk and general cargo ships entering, a day | I |  | 30.2 ± 2.6 |  |  |
| container ships entering, a day | I | 8.29 ± 3.40 | 8.40 ± 1.41 | +1 % | agrees |
| inland cargo craft entering, a day | I |  | 116 ± 6 |  |  |
| inland tankers entering, a day | I |  | 95.3 ± 3.6 |  |  |
| passenger ships entering, a day | I |  | 4.56 ± 1.48 |  |  |
| tankers entering, a day | I |  | 18.9 ± 1.3 |  |  |

## River traffic

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| km 8, off Vlissingen: inland, passages a day | E | 10.1 ± 3.0 | 13.7 ± 2.9 | +36 % | agrees |
| km 8, off Vlissingen: sea-going, passages a day | E | 107 ± 22 | 101 ± 8 | -5 % | agrees |
| km 32, Terneuzen to Hansweert: inland, passages a day | E | 160 ± 51 | 148 ± 10 | -8 % | agrees |
| km 32, Terneuzen to Hansweert: sea-going, passages a day | E | 82.1 ± 15.8 | 70.2 ± 5.9 | -14 % | agrees |
| km 48, Hansweert to Bath: inland, passages a day | E | 85.5 ± 27.5 | 89.0 ± 6.2 | +4 % | agrees |
| km 48, Hansweert to Bath: sea-going, passages a day | E | 81.3 ± 17.6 | 70.0 ± 6.5 | -14 % | agrees |
| km 62, Bath to the Zandvliet locks: inland, passages a day | E | 85.8 ± 28.9 | 89.0 ± 6.5 | +4 % | agrees |
| km 62, Bath to the Zandvliet locks: sea-going, passages a day | E | 82.6 ± 17.9 | 69.9 ± 6.5 | -15 % | agrees |
| km 68, Zandvliet to Deurganckdok: inland, passages a day | E | 125 ± 36 | 110 ± 6 | -12 % | agrees |
| km 68, Zandvliet to Deurganckdok: sea-going, passages a day | E | 47.9 ± 7.0 | 38.0 ± 3.7 | -21 % | differs |
| km 72, Deurganckdok to Boudewijn: inland, passages a day | E | 99.2 ± 41.9 | 85.1 ± 3.3 | -14 % | agrees |
| km 72, Deurganckdok to Boudewijn: sea-going, passages a day | E | 22.7 ± 6.4 | 19.3 ± 1.5 | -15 % | agrees |
| km 80, Kallo to Antwerp: inland, passages a day | E | 38.5 ± 24.2 | 45.3 ± 3.9 | +18 % | agrees |
| km 80, Kallo to Antwerp: sea-going, passages a day | E | 1.98 ± 2.23 | 4.71 ± 1.27 | +138 % | differs |
| km 88, above Antwerp: inland, passages a day | E | 35.4 ± 25.1 | 41.4 ± 3.5 | +17 % | agrees |
| km 88, above Antwerp: sea-going, passages a day | E | 1.54 ± 1.55 | 2.83 ± 1.13 | +83 % | agrees |
| sea, 3.10°E (Wandelaar to Wielingen): sea-going, passages a day | E | 83.5 ± 7.8 | 69.5 ± 8.5 | -17 % | differs |
| sea-going ships calling at Antwerp (the port's statistics, 2020 and 2021), a day | E | 38.1 ± 1.6 | 33.8 ± 3.6 | -11 % | differs |

## Sailing times

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| sea-going, km 8 to km 62, median, h | C | 2.58 ± 0.17 | 2.68 ± 0.06 | +4 % | agrees |
| sea-going, km 8 to km 62, 90th percentile, h | E | 3.46 ± 0.27 | 3.30 ± 0.28 | -4 % | agrees |
| sea-going, km 62 to km 8, median, h | C | 2.50 ± 0.11 | 2.55 ± 0.08 | +2 % | agrees |
| sea-going, km 62 to km 8, 90th percentile, h | E | 3.08 ± 0.19 | 3.12 ± 0.15 | +1 % | agrees |
| inland, km 32 to km 48, median, h | E | 1.08 ± 0.10 | 1.15 ± 0.03 | +6 % | agrees |
| inland, km 32 to km 48, 90th percentile, h | E | 1.58 ± 0.12 | 1.53 ± 0.10 | -3 % | agrees |
| inland, km 48 to km 32, median, h | E | 1.08 ± 0.09 | 1.23 ± 0.03 | +13 % | differs |
| inland, km 48 to km 32, 90th percentile, h | E | 1.52 ± 0.22 | 1.65 ± 0.25 | +9 % | agrees |
| sea-going, sea to km 8, median, h | C | 1.83 ± 0.13 | 1.85 ± 0.03 | +1 % | agrees |
| sea-going, sea to km 8, 90th percentile, h | E | 2.17 ± 0.11 | 2.50 ± 0.70 | +15 % | agrees |
| sea-going, km 8 to sea, median, h | C | 1.75 ± 0.09 | 1.68 ± 0.03 | -4 % | agrees |
| sea-going, km 8 to sea, 90th percentile, h | E | 2.58 ± 0.38 | 2.00 ± 0.05 | -23 % | differs |

## Ships under way

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| dock: inland, ships | E | 23.1 ± 4.9 | 25.5 ± 1.4 | +10 % | agrees |
| dock: sea-going, ships | E | 2.58 ± 0.79 | 3.23 ± 0.31 | +25 % | agrees |
| river: inland, ships | E | 20.5 ± 6.4 | 23.5 ± 1.6 | +15 % | agrees |
| river: sea-going, ships | E | 12.5 ± 2.2 | 11.5 ± 1.4 | -8 % | agrees |
| sea: inland, ships | E | 0.43 ± 0.27 | 0.43 ± 0.20 | +1 % | agrees |
| sea: sea-going, ships | E | 9.81 ± 1.75 | 10.2 ± 1.0 | +4 % | agrees |

## Piloted ships under way

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| dock, mean, ships | E | 2.86 ± 0.69 | 3.21 ± 0.30 | +12 % | agrees |
| dock, 95th percentile, ships | E | 6.33 ± 1.31 | 6.60 ± 0.48 | +4 % | agrees |
| river, mean, ships | E | 12.8 ± 2.2 | 11.5 ± 1.4 | -10 % | agrees |
| river, 95th percentile, ships | E | 19.1 ± 1.9 | 17.2 ± 2.0 | -10 % | agrees |
| sea, mean, ships | E | 10.8 ± 1.8 | 11.8 ± 1.2 | +9 % | agrees |
| sea, 95th percentile, ships | E | 16.0 ± 3.9 | 19.4 ± 4.2 | +21 % | agrees |

## Locks

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| Boudewijn-Van Cauwelaert: inland passing, a day | E | 84.3 ± 19.8 | 96.7 ± 5.0 | +15 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going passing, a day | E | 9.40 ± 1.71 | 9.71 ± 1.09 | +3 % | agrees |
| Hansweert: inland passing, a day | E | 88.1 ± 29.5 | 99.9 ± 7.6 | +13 % | agrees |
| Hansweert: sea-going passing, a day | E | 2.10 ± 1.87 | 0.07 ± 0.14 | -97 % | differs |
| Kallo: inland passing, a day | E | 11.8 ± 2.1 | 23.1 ± 2.7 | +95 % | differs |
| Kallo: sea-going passing, a day | E | 3.21 ± 0.80 | 5.58 ± 1.89 | +74 % | differs |
| Kieldrecht: inland passing, a day | E | 23.1 ± 7.8 | 27.2 ± 2.3 | +17 % | agrees |
| Kieldrecht: sea-going passing, a day | E | 9.29 ± 3.67 | 8.33 ± 2.06 | -10 % | agrees |
| Kreekrak: inland passing, a day | E | 175 ± 28 | 161 ± 9 | -8 % | agrees |
| Kreekrak: sea-going passing, a day | E | 0.33 ± 0.65 | 0.36 ± 0.32 | +9 % | agrees |
| Royers-Kattendijk: inland passing, a day | E | 1.10 ± 1.15 | 0.36 ± 0.55 | -67 % | agrees |
| Royers-Kattendijk: sea-going passing, a day | E | 0.00 | 0.29 ± 0.35 | +nan % | agrees |
| Terneuzen: inland passing, a day | E | 104 ± 31 | 116 ± 5 | +11 % | agrees |
| Terneuzen: sea-going passing, a day | E | 21.7 ± 5.1 | 22.7 ± 1.7 | +5 % | agrees |
| Zandvliet-Berendrecht: inland passing, a day | E | 53.1 ± 10.7 | 78.5 ± 2.1 | +48 % | differs |
| Zandvliet-Berendrecht: sea-going passing, a day | E | 35.8 ± 15.3 | 33.8 ± 4.5 | -6 % | agrees |
| Boudewijn-Van Cauwelaert: inland, time to pass, median, h | C | 1.08 ± 0.06 | 1.09 ± 0.01 | +1 % | agrees |
| Boudewijn-Van Cauwelaert: inland, time to pass, 90th percentile, h | C | 1.92 ± 0.36 | 1.72 ± 0.07 | -11 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going, time to pass, median, h | C | 1.43 ± 0.15 | 1.27 ± 0.06 | -11 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going, time to pass, 90th percentile, h | C | 1.93 ± 0.23 | 1.76 ± 0.10 | -9 % | agrees |
| Hansweert: inland, time to pass, median, h | C | 0.54 ± 0.04 | 0.73 ± 0.03 | +36 % | differs |
| Hansweert: inland, time to pass, 90th percentile, h | C | 0.83 ± 0.08 | 1.17 ± 0.10 | +40 % | differs |
| Kallo: inland, time to pass, median, h | C | 0.97 ± 0.22 | 0.94 ± 0.13 | -3 % | agrees |
| Kallo: inland, time to pass, 90th percentile, h | C | 2.16 ± 1.29 | 1.91 ± 0.30 | -11 % | agrees |
| Kallo: sea-going, time to pass, median, h | C | 1.04 ± 0.14 | 1.15 ± 0.07 | +11 % | agrees |
| Kallo: sea-going, time to pass, 90th percentile, h | C | 1.14 ± 0.14 | 1.62 ± 0.33 | +41 % | differs |
| Kieldrecht: inland, time to pass, median, h | C | 0.83 ± 0.24 | 0.98 ± 0.12 | +18 % | agrees |
| Kieldrecht: inland, time to pass, 90th percentile, h | C | 2.23 ± 1.05 | 2.33 ± 0.44 | +5 % | agrees |
| Kieldrecht: sea-going, time to pass, median, h | C | 1.27 ± 0.13 | 1.28 ± 0.17 | +1 % | agrees |
| Kieldrecht: sea-going, time to pass, 90th percentile, h | C | 1.99 ± 0.36 | 1.84 ± 0.30 | -7 % | agrees |
| Kreekrak: inland, time to pass, median, h | C | 0.75 ± 0.04 | 0.66 ± 0.03 | -12 % | agrees |
| Kreekrak: inland, time to pass, 90th percentile, h | C | 1.19 ± 0.08 | 1.30 ± 0.15 | +9 % | agrees |
| Terneuzen: inland, time to pass, median, h | C | 0.86 ± 0.06 | 0.77 ± 0.01 | -11 % | agrees |
| Terneuzen: inland, time to pass, 90th percentile, h | C | 1.75 ± 0.28 | 1.78 ± 0.30 | +1 % | agrees |
| Terneuzen: sea-going, time to pass, median, h | C | 1.02 ± 0.06 | 0.85 ± 0.06 | -17 % | agrees |
| Terneuzen: sea-going, time to pass, 90th percentile, h | C | 1.27 ± 0.07 | 1.40 ± 0.18 | +11 % | agrees |
| Zandvliet-Berendrecht: inland, time to pass, median, h | C | 1.09 ± 0.09 | 1.17 ± 0.10 | +7 % | agrees |
| Zandvliet-Berendrecht: inland, time to pass, 90th percentile, h | C | 2.25 ± 0.47 | 2.47 ± 0.26 | +10 % | agrees |
| Zandvliet-Berendrecht: sea-going, time to pass, median, h | C | 1.75 ± 0.06 | 1.69 ± 0.08 | -3 % | agrees |
| Zandvliet-Berendrecht: sea-going, time to pass, 90th percentile, h | C | 2.17 ± 0.18 | 2.55 ± 0.21 | +18 % | agrees |
| Boudewijn-Van Cauwelaert: inland, time to pass with the approaches (3 km either side), median, h | E | 1.58 ± 0.10 | 1.50 ± 0.05 | -5 % | agrees |
| Boudewijn-Van Cauwelaert: inland, time to pass with the approaches (3 km either side), 90th percentile, h | E | 2.27 ± 0.24 | 2.36 ± 0.10 | +4 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going, time to pass with the approaches (3 km either side), median, h | E | 1.72 ± 0.30 | 1.68 ± 0.04 | -3 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going, time to pass with the approaches (3 km either side), 90th percentile, h | E | 2.45 ± 0.72 | 1.95 ± 0.13 | -20 % | agrees |
| Hansweert: inland, time to pass with the approaches (3 km either side), median, h | E | 0.90 ± 0.04 | 1.19 ± 0.01 | +31 % | differs |
| Hansweert: inland, time to pass with the approaches (3 km either side), 90th percentile, h | E | 1.25 ± 0.12 | 1.62 ± 0.06 | +29 % | differs |
| Kallo: inland, time to pass with the approaches (3 km either side), median, h | E | 1.38 ± 0.43 | 1.41 ± 0.13 | +2 % | agrees |
| Kallo: inland, time to pass with the approaches (3 km either side), 90th percentile, h | E | 1.78 ± 0.99 | 2.34 ± 0.41 | +31 % | agrees |
| Kallo: sea-going, time to pass with the approaches (3 km either side), median, h | E |  | 1.81 ± 0.08 |  |  |
| Kallo: sea-going, time to pass with the approaches (3 km either side), 90th percentile, h | E |  | 2.34 ± 0.07 |  |  |
| Terneuzen: inland, time to pass with the approaches (3 km either side), median, h | E | 1.34 ± 0.08 | 1.42 ± 0.05 | +6 % | agrees |
| Terneuzen: inland, time to pass with the approaches (3 km either side), 90th percentile, h | E | 2.45 ± 0.24 | 2.49 ± 0.19 | +2 % | agrees |
| Terneuzen: sea-going, time to pass with the approaches (3 km either side), median, h | E | 1.42 ± 0.09 | 1.27 ± 0.10 | -11 % | agrees |
| Terneuzen: sea-going, time to pass with the approaches (3 km either side), 90th percentile, h | E | 1.71 ± 0.11 | 1.92 ± 0.12 | +12 % | agrees |
| Zandvliet-Berendrecht: inland, time to pass with the approaches (3 km either side), median, h | E | 1.51 ± 0.14 | 1.96 ± 0.11 | +29 % | differs |
| Zandvliet-Berendrecht: inland, time to pass with the approaches (3 km either side), 90th percentile, h | E | 2.82 ± 0.73 | 3.54 ± 0.24 | +26 % | agrees |
| Zandvliet-Berendrecht: sea-going, time to pass with the approaches (3 km either side), median, h | E | 2.08 ± 0.11 | 2.13 ± 0.07 | +2 % | agrees |
| Zandvliet-Berendrecht: sea-going, time to pass with the approaches (3 km either side), 90th percentile, h | E | 2.67 ± 0.13 | 2.97 ± 0.15 | +11 % | agrees |
| Hansweert: commercial passages, Rijkswaterstaat's count, a day | C | 113 ± nan | 103 ± 3 | -9 % | agrees |
| Kreekrak: commercial passages, Rijkswaterstaat's count, a day | C | 189 ± nan | 172 ± 6 | -9 % | agrees |
| Terneuzen: commercial passages, Rijkswaterstaat's count, a day | C | 126 ± nan | 147 ± 6 | +16 % | differs |

## Ships in the area

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| bulk and general cargo ships at anchor, ships | C | 4.66 ± 1.41 | 3.74 ± 1.43 | -20 % | agrees |
| bulk and general cargo ships at a berth, ships | I | 45.6 ± 5.9 | 64.7 ± 3.1 | +42 % | differs |
| bulk and general cargo ships in the area, ships | E | 64.1 ± 9.8 | 84.4 ± 4.6 | +32 % | differs |
| container ships at anchor, ships | E | 1.32 ± 0.52 | 1.84 ± 0.33 | +40 % | agrees |
| container ships at a berth, ships | I | 14.4 ± 1.5 | 11.9 ± 1.7 | -17 % | differs |
| container ships in the area, ships | E | 22.7 ± 3.0 | 20.1 ± 2.9 | -11 % | agrees |
| inland cargo craft at anchor, ships | C | 0.21 ± 0.39 | 1.01 ± 0.32 | +377 % | differs |
| inland cargo craft at a berth, ships | C | 156 ± 7 | 167 ± 7 | +7 % | agrees |
| inland cargo craft in the area, ships | E | 205 ± 26 | 210 ± 10 | +3 % | agrees |
| inland tankers at anchor, ships | C | 1.04 ± 0.38 | 0.92 ± 0.21 | -11 % | agrees |
| inland tankers at a berth, ships | C | 127 ± 5 | 166 ± 8 | +31 % | differs |
| inland tankers in the area, ships | E | 169 ± 11 | 199 ± 8 | +18 % | differs |
| tankers at anchor, ships | C | 6.22 ± 1.02 | 11.9 ± 2.0 | +92 % | differs |
| tankers at a berth, ships | I | 37.8 ± 5.0 | 41.9 ± 4.9 | +11 % | agrees |
| tankers in the area, ships | E | 61.8 ± 9.9 | 66.4 ± 7.8 | +7 % | agrees |

## Container ships

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| share that anchors before berthing | C | 0.13 ± 0.12 | 0.12 ± 0.08 | -9 % | agrees |
| at the four terminals, ships | E | 12.6 ± 1.2 | 9.48 ± 1.30 | -25 % | differs |
| berthing against the schedule, mean, h | C |  | 22.1 ± 10.7 |  |  |
| berthing against the schedule, standard deviation, h | I |  | 33.2 ± 7.0 |  |  |
| share berthing over 12 h after their planned time | E |  | 0.04 ± 0.03 |  |  |
| 3.10°E to the berth, median, h | E | 5.33 ± 44.03 | 4.99 ± 0.21 | -6 % | agrees |
| 3.10°E to the berth, 90th percentile, h | E | 412 ± 161 | 6.01 ± 0.80 | -99 % | differs |
