# Validation of 0005_calibration-3

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
| km 8, off Vlissingen: inland, passages a day | E | 12.7 ± 1.4 | 10.5 ± 0.3 | -18 % | agrees |
| km 8, off Vlissingen: sea-going, passages a day | E | 106 ± 7 | 101 ± 3 | -5 % | agrees |
| km 32, Terneuzen to Hansweert: inland, passages a day | E | 179 ± 21 | 171 ± 6 | -4 % | agrees |
| km 32, Terneuzen to Hansweert: sea-going, passages a day | E | 80.9 ± 3.1 | 73.0 ± 2.4 | -10 % | agrees |
| km 48, Hansweert to Bath: inland, passages a day | E | 92.0 ± 11.5 | 102 ± 4 | +11 % | agrees |
| km 48, Hansweert to Bath: sea-going, passages a day | E | 80.5 ± 3.4 | 73.0 ± 2.4 | -9 % | agrees |
| km 62, Bath to the Zandvliet locks: inland, passages a day | E | 91.4 ± 10.9 | 102 ± 4 | +11 % | agrees |
| km 62, Bath to the Zandvliet locks: sea-going, passages a day | E | 80.8 ± 2.9 | 73.0 ± 2.4 | -10 % | agrees |
| km 68, Zandvliet to Deurganckdok: inland, passages a day | E | 132 ± 13 | 125 ± 4 | -5 % | agrees |
| km 68, Zandvliet to Deurganckdok: sea-going, passages a day | E | 46.1 ± 3.4 | 39.4 ± 0.8 | -15 % | agrees |
| km 72, Deurganckdok to Boudewijn: inland, passages a day | E | 103 ± 9 | 121 ± 4 | +18 % | agrees |
| km 72, Deurganckdok to Boudewijn: sea-going, passages a day | E | 22.9 ± 3.9 | 17.2 ± 0.7 | -25 % | differs |
| km 80, Kallo to Antwerp: inland, passages a day | E | 51.7 ± 9.1 | 63.2 ± 1.9 | +22 % | agrees |
| km 80, Kallo to Antwerp: sea-going, passages a day | E | 5.20 ± 1.47 | 2.54 ± 0.39 | -51 % | differs |
| km 88, above Antwerp: inland, passages a day | E | 46.4 ± 9.1 | 52.0 ± 2.4 | +12 % | agrees |
| km 88, above Antwerp: sea-going, passages a day | E | 2.73 ± 1.30 | 1.28 ± 0.41 | -53 % | differs |
| sea, 3.10°E (Wandelaar to Wielingen): sea-going, passages a day | E | 78.9 ± 4.8 | 72.1 ± 2.5 | -9 % | agrees |
| sea-going ships calling at Antwerp (the port's statistics, 2020 and 2021), a day | E | 38.1 ± 1.6 | 36.8 ± 1.5 | -3 % | agrees |

## Sailing times

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| sea-going, km 8 to km 62, median, h | C | 2.67 ± 0.08 | 2.68 ± 0.03 | +1 % | agrees |
| sea-going, km 8 to km 62, 90th percentile, h | E | 3.50 ± 0.15 | 3.27 ± 0.08 | -7 % | agrees |
| sea-going, km 62 to km 8, median, h | C | 2.50 ± 0.08 | 2.65 ± 0.03 | +6 % | agrees |
| sea-going, km 62 to km 8, 90th percentile, h | E | 3.25 ± 0.08 | 3.20 ± 0.08 | -2 % | agrees |
| inland, km 32 to km 48, median, h | E | 1.17 ± 0.01 | 1.17 | +0 % | agrees |
| inland, km 32 to km 48, 90th percentile, h | E | 1.67 ± 0.08 | 1.57 ± 0.06 | -6 % | agrees |
| inland, km 48 to km 32, median, h | E | 1.17 ± 0.03 | 1.28 ± 0.04 | +10 % | agrees |
| inland, km 48 to km 32, 90th percentile, h | E | 1.58 ± 0.08 | 1.71 ± 0.06 | +8 % | agrees |
| sea-going, sea to km 8, median, h | C | 1.83 ± 0.05 | 1.87 ± 0.04 | +2 % | agrees |
| sea-going, sea to km 8, 90th percentile, h | E | 2.42 ± 0.11 | 2.17 | -10 % | differs |
| sea-going, km 8 to sea, median, h | C | 1.67 ± 0.02 | 1.68 ± 0.03 | +1 % | agrees |
| sea-going, km 8 to sea, 90th percentile, h | E | 2.20 ± 0.09 | 1.98 ± 0.03 | -10 % | agrees |

## Ships under way

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| dock: inland, ships | E | 27.0 ± 2.2 | 37.3 ± 3.4 | +38 % | differs |
| dock: sea-going, ships | E | 2.84 ± 0.18 | 4.08 ± 0.70 | +43 % | differs |
| river: inland, ships | E | 25.5 ± 2.9 | 28.7 ± 1.5 | +12 % | agrees |
| river: sea-going, ships | E | 13.2 ± 0.5 | 11.6 ± 0.5 | -12 % | agrees |
| sea: inland, ships | E | 0.65 ± 0.08 | 0.80 ± 0.06 | +23 % | agrees |
| sea: sea-going, ships | E | 10.1 ± 0.6 | 10.00 ± 0.37 | -1 % | agrees |

## Piloted ships under way

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| dock, mean, ships | E | 3.20 ± 0.22 | 4.04 ± 0.71 | +26 % | differs |
| dock, 95th percentile, ships | E | 6.93 ± 0.49 | 7.20 ± 0.73 | +4 % | agrees |
| river, mean, ships | E | 13.4 ± 0.6 | 11.5 ± 0.5 | -14 % | agrees |
| river, 95th percentile, ships | E | 19.9 ± 1.1 | 17.6 ± 0.8 | -12 % | agrees |
| sea, mean, ships | E | 11.2 ± 0.6 | 11.6 ± 0.4 | +3 % | agrees |
| sea, 95th percentile, ships | E | 16.7 ± 0.9 | 18.2 ± 0.4 | +9 % | agrees |

## Locks

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| Boudewijn-Van Cauwelaert: inland passing, a day | E | 93.5 ± 6.8 | 114 ± 3 | +22 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going passing, a day | E | 10.8 ± 2.2 | 8.77 ± 0.62 | -19 % | agrees |
| Hansweert: inland passing, a day | E | 103 ± 9 | 109 ± 4 | +6 % | agrees |
| Hansweert: sea-going passing, a day | E | 0.47 ± 0.32 | 0.06 ± 0.06 | -87 % | differs |
| Kallo: inland passing, a day | E | 23.3 ± 2.2 | 28.1 ± 1.8 | +21 % | agrees |
| Kallo: sea-going passing, a day | E | 5.53 ± 1.36 | 4.62 ± 0.67 | -17 % | agrees |
| Kieldrecht: inland passing, a day | E | 25.4 ± 4.2 | 37.3 ± 1.3 | +47 % | differs |
| Kieldrecht: sea-going passing, a day | E | 11.0 ± 1.0 | 8.95 ± 0.93 | -19 % | differs |
| Kreekrak: inland passing, a day | E | 186 ± 13 | 173 ± 4 | -7 % | agrees |
| Kreekrak: sea-going passing, a day | E | 0.40 ± 0.42 | 0.03 ± 0.04 | -92 % | agrees |
| Royers-Kattendijk: inland passing, a day | E | 0.40 ± 0.57 | 0.60 ± 0.10 | +50 % | agrees |
| Royers-Kattendijk: sea-going passing, a day | E | 0.00 | 0.40 ± 0.09 | +nan % | differs |
| Terneuzen: inland passing, a day | E | 133 ± 16 | 129 ± 5 | -3 % | agrees |
| Terneuzen: sea-going passing, a day | E | 26.9 ± 4.1 | 18.4 ± 1.6 | -32 % | differs |
| Zandvliet-Berendrecht: inland passing, a day | E | 71.1 ± 10.0 | 86.8 ± 4.0 | +22 % | agrees |
| Zandvliet-Berendrecht: sea-going passing, a day | E | 40.1 ± 2.5 | 33.3 ± 1.9 | -17 % | differs |
| Boudewijn-Van Cauwelaert: inland, time to pass, median, h | C | 1.08 ± 0.08 | 1.38 ± 0.04 | +28 % | differs |
| Boudewijn-Van Cauwelaert: inland, time to pass, 90th percentile, h | C | 1.88 ± 0.16 | 2.28 ± 0.14 | +21 % | differs |
| Boudewijn-Van Cauwelaert: sea-going, time to pass, median, h | C | 1.33 ± 0.15 | 1.32 ± 0.08 | -1 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going, time to pass, 90th percentile, h | C | 1.92 ± 0.40 | 1.91 ± 0.13 | -0 % | agrees |
| Hansweert: inland, time to pass, median, h | C | 0.67 ± 0.03 | 0.82 ± 0.03 | +22 % | differs |
| Hansweert: inland, time to pass, 90th percentile, h | C | 1.58 ± 0.22 | 1.28 ± 0.04 | -19 % | agrees |
| Kallo: inland, time to pass, median, h | C | 0.92 ± 0.13 | 1.07 ± 0.03 | +16 % | agrees |
| Kallo: inland, time to pass, 90th percentile, h | C | 2.14 ± 0.63 | 1.42 ± 0.05 | -34 % | differs |
| Kallo: sea-going, time to pass, median, h | C | 1.25 ± 0.11 | 1.19 ± 0.09 | -5 % | agrees |
| Kallo: sea-going, time to pass, 90th percentile, h | C | 1.92 ± 1.12 | 1.72 ± 0.14 | -10 % | agrees |
| Kieldrecht: inland, time to pass, median, h | C | 1.00 ± 0.11 | 1.10 ± 0.03 | +10 % | agrees |
| Kieldrecht: inland, time to pass, 90th percentile, h | C | 1.84 ± 0.38 | 1.65 ± 0.06 | -11 % | agrees |
| Kieldrecht: sea-going, time to pass, median, h | C | 1.42 ± 0.08 | 1.34 ± 0.05 | -5 % | agrees |
| Kieldrecht: sea-going, time to pass, 90th percentile, h | C | 1.87 ± 0.26 | 1.75 ± 0.13 | -6 % | agrees |
| Kreekrak: inland, time to pass, median, h | C | 0.83 ± 0.07 | 0.82 ± 0.03 | -2 % | agrees |
| Kreekrak: inland, time to pass, 90th percentile, h | C | 1.58 ± 0.11 | 1.18 ± 0.03 | -25 % | differs |
| Terneuzen: inland, time to pass, median, h | C | 0.92 ± 0.01 | 1.25 | +36 % | differs |
| Terneuzen: inland, time to pass, 90th percentile, h | C | 1.83 ± 0.11 | 3.30 ± 0.26 | +80 % | differs |
| Terneuzen: sea-going, time to pass, median, h | C | 1.00 ± 0.07 | 1.12 ± 0.04 | +12 % | agrees |
| Terneuzen: sea-going, time to pass, 90th percentile, h | C | 1.42 ± 0.13 | 1.78 ± 0.08 | +26 % | differs |
| Zandvliet-Berendrecht: inland, time to pass, median, h | C | 1.25 ± 0.08 | 1.52 ± 0.03 | +21 % | differs |
| Zandvliet-Berendrecht: inland, time to pass, 90th percentile, h | C | 2.17 ± 0.16 | 2.43 ± 0.10 | +12 % | agrees |
| Zandvliet-Berendrecht: sea-going, time to pass, median, h | C | 1.75 ± 0.06 | 1.68 ± 0.02 | -4 % | agrees |
| Zandvliet-Berendrecht: sea-going, time to pass, 90th percentile, h | C | 2.25 ± 0.12 | 2.39 ± 0.11 | +6 % | agrees |
| Hansweert: commercial passages, Rijkswaterstaat's count, a day | C | 113 ± nan | 110 ± 4 | -3 % | agrees |
| Kreekrak: commercial passages, Rijkswaterstaat's count, a day | C | 189 ± nan | 178 ± 4 | -6 % | agrees |
| Terneuzen: commercial passages, Rijkswaterstaat's count, a day | C | 126 ± nan | 149 ± 5 | +18 % | differs |

## Ships in the area

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| bulk and general cargo ships at anchor, ships | C | 5.62 ± 0.72 | 6.17 ± 0.62 | +10 % | agrees |
| bulk and general cargo ships at a berth, ships | I | 55.7 ± 3.7 | 53.8 ± 3.6 | -3 % | agrees |
| bulk and general cargo ships in the area, ships | E | 77.4 ± 4.3 | 73.7 ± 4.7 | -5 % | agrees |
| container ships at anchor, ships | E | 2.06 ± 0.43 | 1.95 ± 0.19 | -5 % | agrees |
| container ships at a berth, ships | I | 20.1 ± 1.2 | 12.9 ± 0.3 | -36 % | differs |
| container ships in the area, ships | E | 29.7 ± 1.4 | 21.9 ± 0.6 | -26 % | differs |
| inland cargo craft at anchor, ships | E | 1.07 ± 0.25 | 0.00 | -100 % | differs |
| inland cargo craft at a berth, ships | C | 161 ± 7 | 161 ± 7 | +0 % | agrees |
| inland cargo craft in the area, ships | E | 226 ± 6 | 212 ± 9 | -6 % | agrees |
| inland tankers at anchor, ships | E | 0.87 ± 0.32 | 0.00 | -100 % | differs |
| inland tankers at a berth, ships | C | 156 ± 14 | 166 ± 9 | +6 % | agrees |
| inland tankers in the area, ships | E | 218 ± 9 | 200 ± 10 | -8 % | agrees |
| tankers at anchor, ships | C | 9.64 ± 0.74 | 9.17 ± 1.25 | -5 % | agrees |
| tankers at a berth, ships | I | 42.4 ± 1.9 | 41.3 ± 2.5 | -3 % | agrees |
| tankers in the area, ships | E | 67.4 ± 2.1 | 62.3 ± 2.6 | -7 % | agrees |

## Container ships

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| share that anchors before berthing | E | 0.12 ± 0.05 | 0.18 ± 0.01 | +49 % | agrees |
| at the four terminals, ships | E | 12.4 ± 0.8 | 11.1 ± 0.6 | -11 % | agrees |
| berthing against the schedule, mean, h | I | 28.9 ± 8.6 | 34.4 ± 2.0 | +19 % | agrees |
| berthing against the schedule, standard deviation, h | I | 32.4 ± 7.6 | 30.8 ± 2.5 | -5 % | agrees |
| share berthing over 12 h after their planned time | E |  | 0.05 ± 0.04 |  |  |
| 3.10°E to the berth, median, h | E | 4.92 ± 0.12 | 5.09 ± 0.08 | +4 % | agrees |
| 3.10°E to the berth, 90th percentile, h | E | 5.82 ± 7.86 | 7.09 ± 1.27 | +22 % | agrees |
| time at the berth, median, h | I | 24.9 ± 2.3 | 27.0 ± 1.6 | +8 % | agrees |
