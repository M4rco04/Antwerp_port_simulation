# Validation of 0004_calibration-2

AIS record 2026-10-26 01:00 to 2026-11-12 01:28 UTC, 4581 snapshots, 15 whole days. Model: mean of 5 replications. ± is a 95 % interval (the record's from its day-to-day spread).
A number agrees when the difference is within twice its standard error or within the tolerance.

- emergent: 50 of 66 agree
- calibrated: 25 of 35 agree
- input: 11 of 12 agree

## Arrivals

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| bulk and general cargo ships entering, a day | I | 29.8 ± 2.7 | 29.4 ± 1.9 | -1 % | agrees |
| container ships entering, a day | I | 11.8 ± 1.6 | 10.5 ± 0.3 | -11 % | agrees |
| inland cargo craft entering, a day | I | 145 ± 7 | 145 ± 4 | +0 % | agrees |
| inland tankers entering, a day | I | 95.3 ± 5.5 | 95.0 ± 2.7 | -0 % | agrees |
| passenger ships entering, a day | I | 5.06 ± 1.12 | 4.75 ± 0.25 | -6 % | agrees |
| tankers entering, a day | I | 18.5 ± 2.1 | 19.1 ± 0.9 | +3 % | agrees |

## River traffic

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| km 8, off Vlissingen: inland, passages a day | E | 12.7 ± 1.4 | 10.2 ± 0.4 | -20 % | agrees |
| km 8, off Vlissingen: sea-going, passages a day | E | 106 ± 7 | 101 ± 3 | -5 % | agrees |
| km 32, Terneuzen to Hansweert: inland, passages a day | E | 179 ± 21 | 172 ± 6 | -4 % | agrees |
| km 32, Terneuzen to Hansweert: sea-going, passages a day | E | 80.9 ± 3.1 | 73.6 ± 2.7 | -9 % | agrees |
| km 48, Hansweert to Bath: inland, passages a day | E | 92.0 ± 11.5 | 102 ± 4 | +11 % | agrees |
| km 48, Hansweert to Bath: sea-going, passages a day | E | 80.5 ± 3.4 | 73.5 ± 2.7 | -9 % | agrees |
| km 62, Bath to the Zandvliet locks: inland, passages a day | E | 91.4 ± 10.9 | 102 ± 4 | +12 % | agrees |
| km 62, Bath to the Zandvliet locks: sea-going, passages a day | E | 80.8 ± 2.9 | 73.5 ± 2.8 | -9 % | agrees |
| km 68, Zandvliet to Deurganckdok: inland, passages a day | E | 132 ± 13 | 129 ± 6 | -3 % | agrees |
| km 68, Zandvliet to Deurganckdok: sea-going, passages a day | E | 46.1 ± 3.4 | 40.0 ± 1.5 | -13 % | agrees |
| km 72, Deurganckdok to Boudewijn: inland, passages a day | E | 103 ± 9 | 126 ± 5 | +22 % | agrees |
| km 72, Deurganckdok to Boudewijn: sea-going, passages a day | E | 22.9 ± 3.9 | 17.4 ± 1.4 | -24 % | differs |
| km 80, Kallo to Antwerp: inland, passages a day | E | 51.7 ± 9.1 | 65.1 ± 1.9 | +26 % | differs |
| km 80, Kallo to Antwerp: sea-going, passages a day | E | 5.20 ± 1.47 | 2.51 ± 0.34 | -52 % | differs |
| km 88, above Antwerp: inland, passages a day | E | 46.4 ± 9.1 | 53.9 ± 1.6 | +16 % | agrees |
| km 88, above Antwerp: sea-going, passages a day | E | 2.73 ± 1.30 | 1.38 ± 0.33 | -49 % | agrees |
| sea, 3.10°E (Wandelaar to Wielingen): sea-going, passages a day | E | 78.9 ± 4.8 | 71.5 ± 2.2 | -9 % | agrees |
| sea-going ships calling at Antwerp (the port's statistics, 2020 and 2021), a day | E | 38.1 ± 1.6 | 36.7 ± 1.4 | -4 % | agrees |

## Sailing times

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| sea-going, km 8 to km 62, median, h | C | 2.67 ± 0.08 | 2.72 ± 0.04 | +2 % | agrees |
| sea-going, km 8 to km 62, 90th percentile, h | E | 3.50 ± 0.15 | 3.26 ± 0.07 | -7 % | agrees |
| sea-going, km 62 to km 8, median, h | C | 2.50 ± 0.08 | 2.65 ± 0.03 | +6 % | agrees |
| sea-going, km 62 to km 8, 90th percentile, h | E | 3.25 ± 0.08 | 3.17 ± 0.05 | -3 % | agrees |
| inland, km 32 to km 48, median, h | E | 1.17 ± 0.01 | 1.18 ± 0.03 | +1 % | agrees |
| inland, km 32 to km 48, 90th percentile, h | E | 1.67 ± 0.08 | 1.57 ± 0.06 | -6 % | agrees |
| inland, km 48 to km 32, median, h | E | 1.17 ± 0.03 | 1.30 ± 0.04 | +11 % | differs |
| inland, km 48 to km 32, 90th percentile, h | E | 1.58 ± 0.08 | 1.75 | +11 % | differs |
| sea-going, sea to km 8, median, h | C | 1.83 ± 0.05 | 1.83 | -0 % | agrees |
| sea-going, sea to km 8, 90th percentile, h | E | 2.42 ± 0.11 | 2.18 ± 0.03 | -10 % | agrees |
| sea-going, km 8 to sea, median, h | C | 1.67 ± 0.02 | 1.68 ± 0.03 | +1 % | agrees |
| sea-going, km 8 to sea, 90th percentile, h | E | 2.20 ± 0.09 | 1.99 ± 0.03 | -10 % | agrees |

## Ships under way

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| dock: inland, ships | E | 27.0 ± 2.2 | 36.7 ± 1.2 | +36 % | differs |
| dock: sea-going, ships | E | 2.84 ± 0.18 | 3.68 ± 0.97 | +29 % | agrees |
| river: inland, ships | E | 25.5 ± 2.9 | 30.3 ± 1.9 | +19 % | agrees |
| river: sea-going, ships | E | 13.2 ± 0.5 | 11.6 ± 0.5 | -12 % | agrees |
| sea: inland, ships | E | 0.65 ± 0.08 | 0.79 ± 0.06 | +20 % | agrees |
| sea: sea-going, ships | E | 10.1 ± 0.6 | 9.98 ± 0.38 | -1 % | agrees |

## Piloted ships under way

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| dock, mean, ships | E | 3.20 ± 0.22 | 3.64 ± 0.98 | +14 % | agrees |
| dock, 95th percentile, ships | E | 6.93 ± 0.49 | 7.20 ± 1.44 | +4 % | agrees |
| river, mean, ships | E | 13.4 ± 0.6 | 11.5 ± 0.5 | -14 % | agrees |
| river, 95th percentile, ships | E | 19.9 ± 1.1 | 17.4 ± 0.8 | -13 % | agrees |
| sea, mean, ships | E | 11.2 ± 0.6 | 11.5 ± 0.4 | +3 % | agrees |
| sea, 95th percentile, ships | E | 16.7 ± 0.9 | 17.4 ± 1.0 | +4 % | agrees |

## Locks

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| Boudewijn-Van Cauwelaert: inland passing, a day | E | 93.5 ± 6.8 | 116 ± 3 | +24 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going passing, a day | E | 10.8 ± 2.2 | 9.86 ± 0.78 | -9 % | agrees |
| Hansweert: inland passing, a day | E | 103 ± 9 | 111 ± 4 | +8 % | agrees |
| Hansweert: sea-going passing, a day | E | 0.47 ± 0.32 | 0.08 ± 0.07 | -84 % | differs |
| Kallo: inland passing, a day | E | 23.3 ± 2.2 | 27.2 ± 1.5 | +16 % | agrees |
| Kallo: sea-going passing, a day | E | 5.53 ± 1.36 | 3.86 ± 0.68 | -30 % | differs |
| Kieldrecht: inland passing, a day | E | 25.4 ± 4.2 | 37.5 ± 1.9 | +48 % | differs |
| Kieldrecht: sea-going passing, a day | E | 11.0 ± 1.0 | 9.03 ± 1.21 | -18 % | differs |
| Kreekrak: inland passing, a day | E | 186 ± 13 | 173 ± 4 | -7 % | agrees |
| Kreekrak: sea-going passing, a day | E | 0.40 ± 0.42 | 0.03 ± 0.04 | -92 % | agrees |
| Royers-Kattendijk: inland passing, a day | E | 0.40 ± 0.57 | 0.68 ± 0.33 | +69 % | agrees |
| Royers-Kattendijk: sea-going passing, a day | E | 0.00 | 0.20 ± 0.08 | +nan % | differs |
| Terneuzen: inland passing, a day | E | 133 ± 16 | 129 ± 5 | -3 % | agrees |
| Terneuzen: sea-going passing, a day | E | 26.9 ± 4.1 | 18.5 ± 1.5 | -31 % | differs |
| Zandvliet-Berendrecht: inland passing, a day | E | 71.1 ± 10.0 | 86.5 ± 1.9 | +22 % | agrees |
| Zandvliet-Berendrecht: sea-going passing, a day | E | 40.1 ± 2.5 | 33.3 ± 1.8 | -17 % | differs |
| Boudewijn-Van Cauwelaert: inland, time to pass, median, h | C | 1.08 ± 0.08 | 1.42 ± 0.05 | +31 % | differs |
| Boudewijn-Van Cauwelaert: inland, time to pass, 90th percentile, h | C | 1.88 ± 0.16 | 2.41 ± 0.14 | +28 % | differs |
| Boudewijn-Van Cauwelaert: sea-going, time to pass, median, h | C | 1.33 ± 0.15 | 1.36 ± 0.07 | +2 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going, time to pass, 90th percentile, h | C | 1.92 ± 0.40 | 2.11 ± 0.13 | +10 % | agrees |
| Hansweert: inland, time to pass, median, h | C | 0.67 ± 0.03 | 0.82 ± 0.03 | +22 % | differs |
| Hansweert: inland, time to pass, 90th percentile, h | C | 1.58 ± 0.22 | 1.32 ± 0.03 | -17 % | agrees |
| Kallo: inland, time to pass, median, h | C | 0.92 ± 0.13 | 1.07 ± 0.03 | +16 % | agrees |
| Kallo: inland, time to pass, 90th percentile, h | C | 2.14 ± 0.63 | 1.53 ± 0.07 | -28 % | agrees |
| Kallo: sea-going, time to pass, median, h | C | 1.25 ± 0.11 | 1.19 ± 0.15 | -5 % | agrees |
| Kallo: sea-going, time to pass, 90th percentile, h | C | 1.92 ± 1.12 | 1.60 ± 0.18 | -16 % | agrees |
| Kieldrecht: inland, time to pass, median, h | C | 1.00 ± 0.11 | 1.15 ± 0.03 | +15 % | agrees |
| Kieldrecht: inland, time to pass, 90th percentile, h | C | 1.84 ± 0.38 | 2.77 ± 0.30 | +50 % | differs |
| Kieldrecht: sea-going, time to pass, median, h | C | 1.42 ± 0.08 | 1.38 ± 0.07 | -2 % | agrees |
| Kieldrecht: sea-going, time to pass, 90th percentile, h | C | 1.87 ± 0.26 | 1.89 ± 0.14 | +1 % | agrees |
| Kreekrak: inland, time to pass, median, h | C | 0.83 ± 0.07 | 0.80 ± 0.04 | -4 % | agrees |
| Kreekrak: inland, time to pass, 90th percentile, h | C | 1.58 ± 0.11 | 1.17 | -26 % | differs |
| Terneuzen: inland, time to pass, median, h | C | 0.92 ± 0.01 | 1.25 ± 0.09 | +36 % | differs |
| Terneuzen: inland, time to pass, 90th percentile, h | C | 1.83 ± 0.11 | 3.36 ± 0.16 | +83 % | differs |
| Terneuzen: sea-going, time to pass, median, h | C | 1.00 ± 0.07 | 1.12 ± 0.04 | +12 % | agrees |
| Terneuzen: sea-going, time to pass, 90th percentile, h | C | 1.42 ± 0.13 | 1.88 ± 0.08 | +33 % | differs |
| Zandvliet-Berendrecht: inland, time to pass, median, h | C | 1.25 ± 0.08 | 1.53 ± 0.04 | +23 % | differs |
| Zandvliet-Berendrecht: inland, time to pass, 90th percentile, h | C | 2.17 ± 0.16 | 2.47 ± 0.08 | +14 % | agrees |
| Zandvliet-Berendrecht: sea-going, time to pass, median, h | C | 1.75 ± 0.06 | 1.68 ± 0.03 | -4 % | agrees |
| Zandvliet-Berendrecht: sea-going, time to pass, 90th percentile, h | C | 2.25 ± 0.12 | 2.40 ± 0.06 | +7 % | agrees |
| Hansweert: commercial passages, Rijkswaterstaat's count, a day | C | 113 ± nan | 112 ± 4 | -1 % | agrees |
| Kreekrak: commercial passages, Rijkswaterstaat's count, a day | C | 189 ± nan | 177 ± 4 | -6 % | agrees |
| Terneuzen: commercial passages, Rijkswaterstaat's count, a day | C | 126 ± nan | 149 ± 5 | +18 % | differs |

## Ships in the area

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| bulk and general cargo ships at anchor, ships | C | 5.62 ± 0.72 | 6.36 ± 1.09 | +13 % | agrees |
| bulk and general cargo ships at a berth, ships | I | 55.7 ± 3.7 | 55.1 ± 1.9 | -1 % | agrees |
| bulk and general cargo ships in the area, ships | E | 77.4 ± 4.3 | 75.6 ± 3.1 | -2 % | agrees |
| container ships at anchor, ships | E | 2.06 ± 0.43 | 1.94 ± 0.20 | -6 % | agrees |
| container ships at a berth, ships | I | 20.1 ± 1.2 | 12.9 ± 0.3 | -36 % | differs |
| container ships in the area, ships | E | 29.7 ± 1.4 | 21.8 ± 0.4 | -26 % | differs |
| inland cargo craft at anchor, ships | E | 1.07 ± 0.25 | 0.00 | -100 % | differs |
| inland cargo craft at a berth, ships | C | 161 ± 7 | 165 ± 8 | +3 % | agrees |
| inland cargo craft in the area, ships | E | 226 ± 6 | 217 ± 10 | -4 % | agrees |
| inland tankers at anchor, ships | E | 0.87 ± 0.32 | 0.00 | -100 % | differs |
| inland tankers at a berth, ships | C | 156 ± 14 | 158 ± 7 | +1 % | agrees |
| inland tankers in the area, ships | E | 218 ± 9 | 191 ± 7 | -12 % | agrees |
| tankers at anchor, ships | C | 9.64 ± 0.74 | 9.58 ± 1.03 | -1 % | agrees |
| tankers at a berth, ships | I | 42.4 ± 1.9 | 42.1 ± 2.2 | -1 % | agrees |
| tankers in the area, ships | E | 67.4 ± 2.1 | 63.7 ± 3.0 | -5 % | agrees |

## Container ships

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| share that anchors before berthing | E | 0.12 ± 0.05 | 0.18 ± 0.01 | +46 % | agrees |
| at the four terminals, ships | E | 12.4 ± 0.8 | 11.1 ± 0.6 | -10 % | agrees |
| berthing against the schedule, mean, h | I | 28.9 ± 8.6 | 34.2 ± 2.0 | +18 % | agrees |
| berthing against the schedule, standard deviation, h | I | 32.4 ± 7.6 | 30.4 ± 1.8 | -6 % | agrees |
| share berthing over 12 h after their planned time | E |  | 0.04 ± 0.02 |  |  |
| 3.10°E to the berth, median, h | E | 4.92 ± 0.12 | 5.12 ± 0.10 | +4 % | agrees |
| 3.10°E to the berth, 90th percentile, h | E | 5.82 ± 7.86 | 7.20 ± 1.43 | +24 % | agrees |
| time at the berth, median, h | I | 24.9 ± 2.3 | 27.1 ± 1.8 | +9 % | agrees |
