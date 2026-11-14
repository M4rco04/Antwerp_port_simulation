# Validation of 0001_baseline

AIS record 2026-10-26 01:00 to 2026-11-12 01:28 UTC, 4581 snapshots, 15 whole days. Model: mean of 5 replications. ± is a 95 % interval (the record's from its day-to-day spread).
A number agrees when the difference is within twice its standard error or within the tolerance.

- emergent: 43 of 66 agree
- calibrated: 19 of 35 agree
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
| km 8, off Vlissingen: inland, passages a day | E | 12.7 ± 1.4 | 10.5 ± 0.3 | -17 % | agrees |
| km 8, off Vlissingen: sea-going, passages a day | E | 106 ± 7 | 101 ± 2 | -5 % | agrees |
| km 32, Terneuzen to Hansweert: inland, passages a day | E | 179 ± 21 | 173 ± 6 | -4 % | agrees |
| km 32, Terneuzen to Hansweert: sea-going, passages a day | E | 80.9 ± 3.1 | 72.9 ± 2.3 | -10 % | agrees |
| km 48, Hansweert to Bath: inland, passages a day | E | 92.0 ± 11.5 | 104 ± 4 | +13 % | agrees |
| km 48, Hansweert to Bath: sea-going, passages a day | E | 80.5 ± 3.4 | 73.0 ± 2.3 | -9 % | agrees |
| km 62, Bath to the Zandvliet locks: inland, passages a day | E | 91.4 ± 10.9 | 104 ± 4 | +13 % | agrees |
| km 62, Bath to the Zandvliet locks: sea-going, passages a day | E | 80.8 ± 2.9 | 72.9 ± 2.4 | -10 % | agrees |
| km 68, Zandvliet to Deurganckdok: inland, passages a day | E | 132 ± 13 | 124 ± 5 | -6 % | agrees |
| km 68, Zandvliet to Deurganckdok: sea-going, passages a day | E | 46.1 ± 3.4 | 38.6 ± 2.3 | -16 % | differs |
| km 72, Deurganckdok to Boudewijn: inland, passages a day | E | 103 ± 9 | 119 ± 3 | +16 % | agrees |
| km 72, Deurganckdok to Boudewijn: sea-going, passages a day | E | 22.9 ± 3.9 | 15.9 ± 0.9 | -31 % | differs |
| km 80, Kallo to Antwerp: inland, passages a day | E | 51.7 ± 9.1 | 64.4 ± 1.6 | +25 % | agrees |
| km 80, Kallo to Antwerp: sea-going, passages a day | E | 5.20 ± 1.47 | 2.62 ± 0.76 | -50 % | differs |
| km 88, above Antwerp: inland, passages a day | E | 46.4 ± 9.1 | 54.0 ± 1.3 | +16 % | agrees |
| km 88, above Antwerp: sea-going, passages a day | E | 2.73 ± 1.30 | 1.15 ± 0.38 | -58 % | differs |
| sea, 3.10°E (Wandelaar to Wielingen): sea-going, passages a day | E | 78.9 ± 4.8 | 71.5 ± 2.4 | -9 % | agrees |
| sea-going ships calling at Antwerp (the port's statistics, 2020 and 2021), a day | E | 38.1 ± 1.6 | 36.8 ± 1.2 | -3 % | agrees |

## Sailing times

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| sea-going, km 8 to km 62, median, h | C | 2.67 ± 0.08 | 2.68 ± 0.03 | +1 % | agrees |
| sea-going, km 8 to km 62, 90th percentile, h | E | 3.50 ± 0.15 | 3.08 ± 0.05 | -12 % | differs |
| sea-going, km 62 to km 8, median, h | C | 2.50 ± 0.08 | 2.58 | +3 % | agrees |
| sea-going, km 62 to km 8, 90th percentile, h | E | 3.25 ± 0.08 | 2.97 ± 0.04 | -9 % | agrees |
| inland, km 32 to km 48, median, h | E | 1.17 ± 0.01 | 1.20 ± 0.04 | +3 % | agrees |
| inland, km 32 to km 48, 90th percentile, h | E | 1.67 ± 0.08 | 1.46 ± 0.04 | -13 % | differs |
| inland, km 48 to km 32, median, h | E | 1.17 ± 0.03 | 1.27 ± 0.03 | +9 % | agrees |
| inland, km 48 to km 32, 90th percentile, h | E | 1.58 ± 0.08 | 1.62 ± 0.04 | +2 % | agrees |
| sea-going, sea to km 8, median, h | C | 1.83 ± 0.05 | 1.92 | +5 % | agrees |
| sea-going, sea to km 8, 90th percentile, h | E | 2.42 ± 0.11 | 2.00 | -17 % | differs |
| sea-going, km 8 to sea, median, h | C | 1.67 ± 0.02 | 1.73 ± 0.03 | +4 % | agrees |
| sea-going, km 8 to sea, 90th percentile, h | E | 2.20 ± 0.09 | 1.83 | -17 % | differs |

## Ships under way

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| dock: inland, ships | E | 27.0 ± 2.2 | 34.7 ± 2.3 | +29 % | differs |
| dock: sea-going, ships | E | 2.84 ± 0.18 | 5.10 ± 1.32 | +79 % | differs |
| river: inland, ships | E | 25.5 ± 2.9 | 29.7 ± 1.0 | +16 % | agrees |
| river: sea-going, ships | E | 13.2 ± 0.5 | 11.3 ± 0.4 | -14 % | agrees |
| sea: inland, ships | E | 0.65 ± 0.08 | 0.82 ± 0.05 | +25 % | agrees |
| sea: sea-going, ships | E | 10.1 ± 0.6 | 9.93 ± 0.35 | -2 % | agrees |

## Piloted ships under way

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| dock, mean, ships | E | 3.20 ± 0.22 | 5.06 ± 1.32 | +58 % | differs |
| dock, 95th percentile, ships | E | 6.93 ± 0.49 | 8.20 ± 1.57 | +18 % | agrees |
| river, mean, ships | E | 13.4 ± 0.6 | 11.2 ± 0.4 | -16 % | differs |
| river, 95th percentile, ships | E | 19.9 ± 1.1 | 17.2 ± 0.7 | -14 % | agrees |
| sea, mean, ships | E | 11.2 ± 0.6 | 11.5 ± 0.4 | +3 % | agrees |
| sea, 95th percentile, ships | E | 16.7 ± 0.9 | 17.2 ± 1.0 | +3 % | agrees |

## Locks

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| Boudewijn-Van Cauwelaert: inland passing, a day | E | 93.5 ± 6.8 | 112 ± 3 | +20 % | agrees |
| Boudewijn-Van Cauwelaert: sea-going passing, a day | E | 10.8 ± 2.2 | 7.95 ± 1.34 | -26 % | differs |
| Hansweert: inland passing, a day | E | 103 ± 9 | 110 ± 3 | +6 % | agrees |
| Hansweert: sea-going passing, a day | E | 0.47 ± 0.32 | 0.05 ± 0.06 | -90 % | differs |
| Kallo: inland passing, a day | E | 23.3 ± 2.2 | 26.1 ± 1.7 | +12 % | agrees |
| Kallo: sea-going passing, a day | E | 5.53 ± 1.36 | 3.42 ± 0.25 | -38 % | differs |
| Kieldrecht: inland passing, a day | E | 25.4 ± 4.2 | 37.7 ± 1.2 | +49 % | differs |
| Kieldrecht: sea-going passing, a day | E | 11.0 ± 1.0 | 10.4 ± 1.3 | -6 % | agrees |
| Kreekrak: inland passing, a day | E | 186 ± 13 | 174 ± 4 | -6 % | agrees |
| Kreekrak: sea-going passing, a day | E | 0.40 ± 0.42 | 0.02 ± 0.03 | -96 % | agrees |
| Royers-Kattendijk: inland passing, a day | E | 0.40 ± 0.57 | 0.72 ± 0.24 | +81 % | agrees |
| Royers-Kattendijk: sea-going passing, a day | E | 0.00 | 0.37 ± 0.24 | +nan % | differs |
| Terneuzen: inland passing, a day | E | 133 ± 16 | 130 ± 4 | -2 % | agrees |
| Terneuzen: sea-going passing, a day | E | 26.9 ± 4.1 | 18.4 ± 1.3 | -32 % | differs |
| Zandvliet-Berendrecht: inland passing, a day | E | 71.1 ± 10.0 | 89.0 ± 2.5 | +25 % | differs |
| Zandvliet-Berendrecht: sea-going passing, a day | E | 40.1 ± 2.5 | 34.7 ± 1.7 | -13 % | agrees |
| Boudewijn-Van Cauwelaert: inland, time to pass, median, h | C | 1.08 ± 0.08 | 2.12 ± 0.12 | +95 % | differs |
| Boudewijn-Van Cauwelaert: inland, time to pass, 90th percentile, h | C | 1.88 ± 0.16 | 4.18 ± 0.33 | +122 % | differs |
| Boudewijn-Van Cauwelaert: sea-going, time to pass, median, h | C | 1.33 ± 0.15 | 1.88 ± 0.15 | +41 % | differs |
| Boudewijn-Van Cauwelaert: sea-going, time to pass, 90th percentile, h | C | 1.92 ± 0.40 | 3.39 ± 0.61 | +77 % | differs |
| Hansweert: inland, time to pass, median, h | C | 0.67 ± 0.03 | 1.07 ± 0.02 | +61 % | differs |
| Hansweert: inland, time to pass, 90th percentile, h | C | 1.58 ± 0.22 | 1.47 ± 0.04 | -7 % | agrees |
| Kallo: inland, time to pass, median, h | C | 0.92 ± 0.13 | 1.07 ± 0.06 | +16 % | agrees |
| Kallo: inland, time to pass, 90th percentile, h | C | 2.14 ± 0.63 | 1.50 ± 0.09 | -30 % | agrees |
| Kallo: sea-going, time to pass, median, h | C | 1.25 ± 0.11 | 1.17 ± 0.10 | -7 % | agrees |
| Kallo: sea-going, time to pass, 90th percentile, h | C | 1.92 ± 1.12 | 1.55 ± 0.10 | -19 % | agrees |
| Kieldrecht: inland, time to pass, median, h | C | 1.00 ± 0.11 | 1.20 ± 0.04 | +20 % | differs |
| Kieldrecht: inland, time to pass, 90th percentile, h | C | 1.84 ± 0.38 | 2.90 ± 0.62 | +57 % | differs |
| Kieldrecht: sea-going, time to pass, median, h | C | 1.42 ± 0.08 | 1.32 ± 0.08 | -7 % | agrees |
| Kieldrecht: sea-going, time to pass, 90th percentile, h | C | 1.87 ± 0.26 | 1.78 ± 0.10 | -5 % | agrees |
| Kreekrak: inland, time to pass, median, h | C | 0.83 ± 0.07 | 1.02 ± 0.03 | +22 % | differs |
| Kreekrak: inland, time to pass, 90th percentile, h | C | 1.58 ± 0.11 | 1.38 ± 0.04 | -13 % | agrees |
| Terneuzen: inland, time to pass, median, h | C | 0.92 ± 0.01 | 1.37 ± 0.04 | +49 % | differs |
| Terneuzen: inland, time to pass, 90th percentile, h | C | 1.83 ± 0.11 | 2.27 ± 0.11 | +24 % | differs |
| Terneuzen: sea-going, time to pass, median, h | C | 1.00 ± 0.07 | 1.35 ± 0.06 | +35 % | differs |
| Terneuzen: sea-going, time to pass, 90th percentile, h | C | 1.42 ± 0.13 | 2.07 ± 0.02 | +46 % | differs |
| Zandvliet-Berendrecht: inland, time to pass, median, h | C | 1.25 ± 0.08 | 1.57 ± 0.03 | +25 % | differs |
| Zandvliet-Berendrecht: inland, time to pass, 90th percentile, h | C | 2.17 ± 0.16 | 2.62 ± 0.05 | +21 % | differs |
| Zandvliet-Berendrecht: sea-going, time to pass, median, h | C | 1.75 ± 0.06 | 1.69 ± 0.05 | -3 % | agrees |
| Zandvliet-Berendrecht: sea-going, time to pass, 90th percentile, h | C | 2.25 ± 0.12 | 2.42 ± 0.07 | +8 % | agrees |
| Hansweert: commercial passages, Rijkswaterstaat's count, a day | C | 113 ± nan | 110 ± 3 | -2 % | agrees |
| Kreekrak: commercial passages, Rijkswaterstaat's count, a day | C | 189 ± nan | 178 ± 3 | -6 % | agrees |
| Terneuzen: commercial passages, Rijkswaterstaat's count, a day | C | 126 ± nan | 150 ± 4 | +19 % | differs |

## Ships in the area

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| bulk and general cargo ships at anchor, ships | C | 5.62 ± 0.72 | 3.88 ± 0.59 | -31 % | differs |
| bulk and general cargo ships at a berth, ships | I | 55.7 ± 3.7 | 53.1 ± 2.9 | -5 % | agrees |
| bulk and general cargo ships in the area, ships | E | 77.4 ± 4.3 | 71.6 ± 3.6 | -7 % | agrees |
| container ships at anchor, ships | E | 2.06 ± 0.43 | 1.97 ± 0.21 | -4 % | agrees |
| container ships at a berth, ships | I | 20.1 ± 1.2 | 12.9 ± 0.2 | -36 % | differs |
| container ships in the area, ships | E | 29.7 ± 1.4 | 22.0 ± 0.8 | -26 % | differs |
| inland cargo craft at anchor, ships | E | 1.07 ± 0.25 | 0.00 | -100 % | differs |
| inland cargo craft at a berth, ships | C | 161 ± 7 | 161 ± 3 | +0 % | agrees |
| inland cargo craft in the area, ships | E | 226 ± 6 | 217 ± 4 | -4 % | agrees |
| inland tankers at anchor, ships | E | 0.87 ± 0.32 | 0.00 | -100 % | differs |
| inland tankers at a berth, ships | C | 156 ± 14 | 160 ± 7 | +3 % | agrees |
| inland tankers in the area, ships | E | 218 ± 9 | 197 ± 8 | -10 % | agrees |
| tankers at anchor, ships | C | 9.64 ± 0.74 | 8.75 ± 0.89 | -9 % | agrees |
| tankers at a berth, ships | I | 42.4 ± 1.9 | 42.6 ± 2.8 | +0 % | agrees |
| tankers in the area, ships | E | 67.4 ± 2.1 | 63.3 ± 2.7 | -6 % | agrees |

## Container ships

| | Kind | Record | Model | Difference | |
| --- | --- | --- | --- | --- | --- |
| share that anchors before berthing | E | 0.12 ± 0.05 | 0.18 ± 0.02 | +51 % | differs |
| at the four terminals, ships | E | 12.4 ± 0.8 | 11.1 ± 0.5 | -11 % | agrees |
| berthing against the schedule, mean, h | I | 28.9 ± 8.6 | 34.2 ± 1.8 | +18 % | agrees |
| berthing against the schedule, standard deviation, h | I | 32.4 ± 7.6 | 30.5 ± 1.8 | -6 % | agrees |
| share berthing over 12 h after their planned time | E |  | 0.04 ± 0.03 |  |  |
| 3.10°E to the berth, median, h | E | 4.92 ± 0.12 | 4.97 ± 0.03 | +1 % | agrees |
| 3.10°E to the berth, 90th percentile, h | E | 5.82 ± 7.86 | 6.44 ± 0.80 | +11 % | agrees |
| time at the berth, median, h | I | 24.9 ± 2.3 | 27.0 ± 1.6 | +8 % | agrees |
