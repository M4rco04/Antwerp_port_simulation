# Validation of 0002_bvc-passage-time

AIS record 2026-10-26 01:00 to 2026-11-12 01:28 UTC, 4581 snapshots, 15 whole days. Model: mean of 5 replications. ± is a 95 % interval (the record's from its day-to-day spread).
A number agrees when the difference is within twice its standard error or within the tolerance.

- emergent: 43 of 66 agree
- calibrated: 21 of 35 agree
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
| km 8, off Vlissingen: inland, passages a day | E | 12.7 ± 1.4 | 10.8 ± 0.6 | -16 % | agrees |
| km 8, off Vlissingen: sea-going, passages a day | E | 106 ± 7 | 101 ± 2 | -5 % | agrees |
| km 32, Terneuzen to Hansweert: inland, passages a day | E | 179 ± 21 | 171 ± 5 | -5 % | agrees |
| km 32, Terneuzen to Hansweert: sea-going, passages a day | E | 80.9 ± 3.1 | 73.0 ± 2.0 | -10 % | agrees |
| km 48, Hansweert to Bath: inland, passages a day | E | 92.0 ± 11.5 | 103 ± 4 | +12 % | agrees |
| km 48, Hansweert to Bath: sea-going, passages a day | E | 80.5 ± 3.4 | 73.1 ± 2.0 | -9 % | agrees |
| km 62, Bath to the Zandvliet locks: inland, passages a day | E | 91.4 ± 10.9 | 103 ± 4 | +12 % | agrees |
| km 62, Bath to the Zandvliet locks: sea-going, passages a day | E | 80.8 ± 2.9 | 73.1 ± 1.9 | -10 % | agrees |
| km 68, Zandvliet to Deurganckdok: inland, passages a day | E | 132 ± 13 | 127 ± 4 | -4 % | agrees |
| km 68, Zandvliet to Deurganckdok: sea-going, passages a day | E | 46.1 ± 3.4 | 38.0 ± 2.0 | -17 % | differs |
| km 72, Deurganckdok to Boudewijn: inland, passages a day | E | 103 ± 9 | 123 ± 5 | +19 % | agrees |
| km 72, Deurganckdok to Boudewijn: sea-going, passages a day | E | 22.9 ± 3.9 | 15.8 ± 1.0 | -31 % | differs |
| km 80, Kallo to Antwerp: inland, passages a day | E | 51.7 ± 9.1 | 63.7 ± 1.4 | +23 % | agrees |
| km 80, Kallo to Antwerp: sea-going, passages a day | E | 5.20 ± 1.47 | 2.57 ± 0.64 | -51 % | differs |
| km 88, above Antwerp: inland, passages a day | E | 46.4 ± 9.1 | 52.7 ± 1.4 | +13 % | agrees |
| km 88, above Antwerp: sea-going, passages a day | E | 2.73 ± 1.30 | 1.46 ± 0.30 | -47 % | agrees |
| sea, 3.10°E (Wandelaar to Wielingen): sea-going, passages a day | E | 78.9 ± 4.8 | 72.1 ± 1.6 | -9 % | agrees |
| sea-going ships calling at Antwerp (the port's statistics, 2020 and 2021), a day | E | 38.1 ± 1.6 | 36.8 ± 1.2 | -3 % | agrees |

## Sailing times

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| sea-going, km 8 to km 62, median, h | C | 2.67 ± 0.08 | 2.67 | +0 % | agrees |
| sea-going, km 8 to km 62, 90th percentile, h | E | 3.50 ± 0.15 | 3.08 ± 0.05 | -12 % | differs |
| sea-going, km 62 to km 8, median, h | C | 2.50 ± 0.08 | 2.58 | +3 % | agrees |
| sea-going, km 62 to km 8, 90th percentile, h | E | 3.25 ± 0.08 | 3.00 ± 0.05 | -8 % | agrees |
| inland, km 32 to km 48, median, h | E | 1.17 ± 0.01 | 1.18 ± 0.03 | +1 % | agrees |
| inland, km 32 to km 48, 90th percentile, h | E | 1.67 ± 0.08 | 1.47 ± 0.04 | -12 % | differs |
| inland, km 48 to km 32, median, h | E | 1.17 ± 0.03 | 1.28 ± 0.04 | +10 % | agrees |
| inland, km 48 to km 32, 90th percentile, h | E | 1.58 ± 0.08 | 1.67 ± 0.05 | +5 % | agrees |
| sea-going, sea to km 8, median, h | C | 1.83 ± 0.05 | 1.92 | +5 % | agrees |
| sea-going, sea to km 8, 90th percentile, h | E | 2.42 ± 0.11 | 2.00 | -17 % | differs |
| sea-going, km 8 to sea, median, h | C | 1.67 ± 0.02 | 1.73 ± 0.03 | +4 % | agrees |
| sea-going, km 8 to sea, 90th percentile, h | E | 2.20 ± 0.09 | 1.83 | -17 % | differs |

## Ships under way

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| dock: inland, ships | E | 27.0 ± 2.2 | 38.6 ± 2.6 | +43 % | differs |
| dock: sea-going, ships | E | 2.84 ± 0.18 | 4.41 ± 0.69 | +55 % | differs |
| river: inland, ships | E | 25.5 ± 2.9 | 28.4 ± 1.5 | +11 % | agrees |
| river: sea-going, ships | E | 13.2 ± 0.5 | 11.3 ± 0.4 | -14 % | agrees |
| sea: inland, ships | E | 0.65 ± 0.08 | 0.79 ± 0.04 | +20 % | agrees |
| sea: sea-going, ships | E | 10.1 ± 0.6 | 9.97 ± 0.28 | -1 % | agrees |

## Piloted ships under way

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| dock, mean, ships | E | 3.20 ± 0.22 | 4.38 ± 0.69 | +37 % | differs |
| dock, 95th percentile, ships | E | 6.93 ± 0.49 | 7.60 ± 0.78 | +10 % | agrees |
| river, mean, ships | E | 13.4 ± 0.6 | 11.2 ± 0.4 | -16 % | differs |
| river, 95th percentile, ships | E | 19.9 ± 1.1 | 17.2 ± 0.7 | -14 % | agrees |
| sea, mean, ships | E | 11.2 ± 0.6 | 11.5 ± 0.3 | +3 % | agrees |
| sea, 95th percentile, ships | E | 16.7 ± 0.9 | 17.8 ± 0.7 | +7 % | agrees |

## Locks

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| Boudewijn-Van Cauwelaert: inland passing, a day | E | 93.5 ± 6.8 | 115 ± 2 | +23 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going passing, a day | E | 10.8 ± 2.2 | 7.49 ± 0.42 | -31 % | differs |
| Hansweert: inland passing, a day | E | 103 ± 9 | 109 ± 3 | +6 % | agrees |
| Hansweert: sea-going passing, a day | E | 0.47 ± 0.32 | 0.08 ± 0.07 | -84 % | differs |
| Kallo: inland passing, a day | E | 23.3 ± 2.2 | 26.3 ± 1.1 | +13 % | agrees |
| Kallo: sea-going passing, a day | E | 5.53 ± 1.36 | 3.80 ± 0.39 | -31 % | differs |
| Kieldrecht: inland passing, a day | E | 25.4 ± 4.2 | 35.6 ± 2.4 | +40 % | differs |
| Kieldrecht: sea-going passing, a day | E | 11.0 ± 1.0 | 9.32 ± 1.23 | -15 % | differs |
| Kreekrak: inland passing, a day | E | 186 ± 13 | 174 ± 5 | -7 % | agrees |
| Kreekrak: sea-going passing, a day | E | 0.40 ± 0.42 | 0.02 ± 0.03 | -96 % | agrees |
| Royers-Kattendijk: inland passing, a day | E | 0.40 ± 0.57 | 0.51 ± 0.24 | +27 % | agrees |
| Royers-Kattendijk: sea-going passing, a day | E | 0.00 | 0.14 ± 0.07 | +nan % | differs |
| Terneuzen: inland passing, a day | E | 133 ± 16 | 129 ± 3 | -3 % | agrees |
| Terneuzen: sea-going passing, a day | E | 26.9 ± 4.1 | 18.8 ± 1.1 | -30 % | differs |
| Zandvliet-Berendrecht: inland passing, a day | E | 71.1 ± 10.0 | 89.1 ± 3.2 | +25 % | differs |
| Zandvliet-Berendrecht: sea-going passing, a day | E | 40.1 ± 2.5 | 34.9 ± 0.8 | -13 % | agrees |
| Boudewijn-Van Cauwelaert: inland, time to pass, median, h | C | 1.08 ± 0.08 | 1.43 ± 0.03 | +32 % | differs |
| Boudewijn-Van Cauwelaert: inland, time to pass, 90th percentile, h | C | 1.88 ± 0.16 | 2.43 ± 0.15 | +29 % | differs |
| Boudewijn-Van Cauwelaert: sea-going, time to pass, median, h | C | 1.33 ± 0.15 | 1.43 ± 0.08 | +7 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going, time to pass, 90th percentile, h | C | 1.92 ± 0.40 | 2.02 ± 0.16 | +6 % | agrees |
| Hansweert: inland, time to pass, median, h | C | 0.67 ± 0.03 | 1.05 ± 0.04 | +57 % | differs |
| Hansweert: inland, time to pass, 90th percentile, h | C | 1.58 ± 0.22 | 1.50 | -5 % | agrees |
| Kallo: inland, time to pass, median, h | C | 0.92 ± 0.13 | 1.07 ± 0.03 | +16 % | agrees |
| Kallo: inland, time to pass, 90th percentile, h | C | 2.14 ± 0.63 | 1.48 ± 0.06 | -31 % | differs |
| Kallo: sea-going, time to pass, median, h | C | 1.25 ± 0.11 | 1.24 ± 0.08 | -1 % | agrees |
| Kallo: sea-going, time to pass, 90th percentile, h | C | 1.92 ± 1.12 | 1.56 ± 0.13 | -19 % | agrees |
| Kieldrecht: inland, time to pass, median, h | C | 1.00 ± 0.11 | 1.17 ± 0.05 | +17 % | agrees |
| Kieldrecht: inland, time to pass, 90th percentile, h | C | 1.84 ± 0.38 | 2.98 ± 0.43 | +62 % | differs |
| Kieldrecht: sea-going, time to pass, median, h | C | 1.42 ± 0.08 | 1.42 ± 0.09 | +0 % | agrees |
| Kieldrecht: sea-going, time to pass, 90th percentile, h | C | 1.87 ± 0.26 | 1.91 ± 0.04 | +2 % | agrees |
| Kreekrak: inland, time to pass, median, h | C | 0.83 ± 0.07 | 1.02 ± 0.03 | +22 % | differs |
| Kreekrak: inland, time to pass, 90th percentile, h | C | 1.58 ± 0.11 | 1.37 ± 0.04 | -14 % | agrees |
| Terneuzen: inland, time to pass, median, h | C | 0.92 ± 0.01 | 1.38 ± 0.04 | +50 % | differs |
| Terneuzen: inland, time to pass, 90th percentile, h | C | 1.83 ± 0.11 | 2.40 ± 0.17 | +31 % | differs |
| Terneuzen: sea-going, time to pass, median, h | C | 1.00 ± 0.07 | 1.31 ± 0.07 | +31 % | differs |
| Terneuzen: sea-going, time to pass, 90th percentile, h | C | 1.42 ± 0.13 | 2.00 ± 0.07 | +41 % | differs |
| Zandvliet-Berendrecht: inland, time to pass, median, h | C | 1.25 ± 0.08 | 1.57 ± 0.03 | +25 % | differs |
| Zandvliet-Berendrecht: inland, time to pass, 90th percentile, h | C | 2.17 ± 0.16 | 2.65 ± 0.12 | +22 % | differs |
| Zandvliet-Berendrecht: sea-going, time to pass, median, h | C | 1.75 ± 0.06 | 1.65 ± 0.06 | -6 % | agrees |
| Zandvliet-Berendrecht: sea-going, time to pass, 90th percentile, h | C | 2.25 ± 0.12 | 2.34 ± 0.09 | +4 % | agrees |
| Hansweert: commercial passages, Rijkswaterstaat's count, a day | C | 113 ± nan | 110 ± 3 | -3 % | agrees |
| Kreekrak: commercial passages, Rijkswaterstaat's count, a day | C | 189 ± nan | 177 ± 5 | -6 % | agrees |
| Terneuzen: commercial passages, Rijkswaterstaat's count, a day | C | 126 ± nan | 148 ± 3 | +18 % | differs |

## Ships in the area

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| bulk and general cargo ships at anchor, ships | C | 5.62 ± 0.72 | 4.59 ± 0.69 | -18 % | differs |
| bulk and general cargo ships at a berth, ships | I | 55.7 ± 3.7 | 54.7 ± 4.6 | -2 % | agrees |
| bulk and general cargo ships in the area, ships | E | 77.4 ± 4.3 | 73.1 ± 5.7 | -5 % | agrees |
| container ships at anchor, ships | E | 2.06 ± 0.43 | 1.97 ± 0.20 | -4 % | agrees |
| container ships at a berth, ships | I | 20.1 ± 1.2 | 12.9 ± 0.3 | -36 % | differs |
| container ships in the area, ships | E | 29.7 ± 1.4 | 21.9 ± 0.7 | -26 % | differs |
| inland cargo craft at anchor, ships | E | 1.07 ± 0.25 | 0.00 | -100 % | differs |
| inland cargo craft at a berth, ships | C | 161 ± 7 | 163 ± 5 | +1 % | agrees |
| inland cargo craft in the area, ships | E | 226 ± 6 | 217 ± 6 | -4 % | agrees |
| inland tankers at anchor, ships | E | 0.87 ± 0.32 | 0.00 | -100 % | differs |
| inland tankers at a berth, ships | C | 156 ± 14 | 161 ± 6 | +3 % | agrees |
| inland tankers in the area, ships | E | 218 ± 9 | 195 ± 6 | -11 % | agrees |
| tankers at anchor, ships | C | 9.64 ± 0.74 | 10.8 ± 0.8 | +12 % | agrees |
| tankers at a berth, ships | I | 42.4 ± 1.9 | 39.1 ± 2.7 | -8 % | agrees |
| tankers in the area, ships | E | 67.4 ± 2.1 | 62.0 ± 3.0 | -8 % | agrees |

## Container ships

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| share that anchors before berthing | E | 0.12 ± 0.05 | 0.18 ± 0.02 | +51 % | differs |
| at the four terminals, ships | E | 12.4 ± 0.8 | 11.1 ± 0.6 | -10 % | agrees |
| berthing against the schedule, mean, h | I | 28.9 ± 8.6 | 34.2 ± 1.9 | +18 % | agrees |
| berthing against the schedule, standard deviation, h | I | 32.4 ± 7.6 | 30.5 ± 2.0 | -6 % | agrees |
| share berthing over 12 h after their planned time | E |  | 0.05 ± 0.04 |  |  |
| 3.10°E to the berth, median, h | E | 4.92 ± 0.12 | 4.98 ± 0.06 | +1 % | agrees |
| 3.10°E to the berth, 90th percentile, h | E | 5.82 ± 7.86 | 6.59 ± 1.30 | +13 % | agrees |
| time at the berth, median, h | I | 24.9 ± 2.3 | 27.1 ± 1.8 | +9 % | agrees |
