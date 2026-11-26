# Behaviour rules for ship agents — Port of Antwerp & Scheldt approaches

Rules extracted from the three PDFs in this repo plus regulations found online (Oct 2026), written as
inputs for agent logic. COLREG rules are in `zasady_ruchu_i_zachowania_statkow_COLREG.md`; this file only
covers local rules that add to or override them.

## Sources and precedence

| Code | Document | Date | Status |
|---|---|---|---|
| **JA22** | `Regulacje_Wejsc_Wyjsc_Antwerpia.pdf` – GNA Joint Announcement 04-2022 "Arrival and departure regulation and working arrangements for Antwerp" | in force 1 Jun 2022 | **Current.** Replaces NtM 1/33 (JN 03-2017). |
| **NtM** | `Przepisy_nautyczne_MDK_Belgijskie_wybrzeże_i_porty.pdf` – Flemish Hydrography *Notices to Mariners No. 01/2021* (annual compilation of standing GNA/MDK rules) | 7 Jan 2021 | Mostly current; section numbers below are "1/xx". 1/33 superseded by JA22. |
| **CP** | `Przepisy_Portowe_Port_Miejski_w_Antwerpii.pdf` – City Port (Stadshaven) police regulations | amended 2021 | Applies only to the old city docks south of Royers/Kattendijk lock. **Seagoing ships and tankers are banned there.** |
| **HPV** | Havenpolitieverordening Haven van Antwerpen (port police regulation for the whole sea port) | 2 Oct 2021 | Found online. A revision dated 14 Mar 2022 is reported; check for differences. |
| **BZS** | Scheepvaartreglement voor de Beneden-Zeeschelde (KB 23 Sep 1992, consolidated to 1999) | 1992 | Found online. River traffic rules from the NL/BE border to Antwerp. |
| **GB25** | GNA Joint Announcement 01-2025 "Passing Walsoorden harbour and other harbours, jetties and quays" (Stcrt. 2025, 20943) | 2025 | Found online. |
| **GB24** | GNA Joint Announcement 03-2024 "Arrival/departure rules for anchorages Put van Terneuzen and Everingen" (Stcrt. 2024, 33414) | 1 Nov 2024 | Found online. Replaces GB 04-2017. |

Where values conflict, the newer document wins: JA22 > NtM 1/33, and HPV > NtM for the docks.

Abbreviations:

- **GNA**: Common Nautical Authority (joint NL/BE)
- **ACC**: Antwerp Coordination Center
- **HKD**: Harbour Master's Office, Antwerp
- **CP**: Coordination Point, a notional point near the Zuid-Saeftinghe beacon
- **WESP**: GNA tidal-window tool
- **HW/LW**: high/low water at Prosperpolder
- **T**: maximum draught in fresh water
- **LOA/B**: length overall / beam overall

---

## 1. Spatial model (zones the agent must know)

1. **Route segments (JA22 art. 1):**
   - *Sea route*: from the pilot stations (Wandelaar, Steenbank) to Vlissingen (Flushing) Roads.
   - *River route*: from Vlissingen Roads to the upper end of Antwerp Roads.
   - *Docks*: behind the locks.
2. **Pilot stations (NtM 1/15):**
   - Wandelaar: ~51°22.2'N 002°42.9'E, north of the KB buoy; VHF 65.
   - Steenbank/Schouwenbank: VHF 64 (traffic) and 79 (pilots).
   - The pilot changes from sea pilot to river pilot at **Vlissingen Roads**.
3. **VTS sectors and VHF channels (NtM 1/29 §4).** Reporting events fire at the boundaries:

   | Sector | Call sign | Channel(s) |
   |---|---|---|
   | Wandelaar | Wandelaar Approach / Traffic Centre Wandelaar | 60 / 65 |
   | Steenbank | Traffic Centre Steenbank | 64 |
   | Zeebrugge | Traffic Centre Zeebrugge | 69 |
   | Vlissingen | Traffic Centre Vlissingen | 14 |
   | Terneuzen | Traffic Centre Terneuzen | 03 |
   | Hansweert | Traffic Centre Hansweert | 65 |
   | Antwerp (buoys 55/46 to buoy 100) | Zandvliet | 12 |
   | Lock and port information | SID Antwerpen | 85 |

   **Upstream of buoy 100 there is no radar coverage.** Ships there broadcast their intentions to all ships on ch 10.
4. **Main fairways (NtM 1/24).** Oostgat, Sardijngeul, Wielingen (NL part), Vlissingen precautionary area, Honte, Drempel van Borssele, Pas van Terneuzen, Gat van Ossenisse, Overloop van Hansweert, Zuidergat, Bocht van Walsoorden, Overloop van Valkenisse, Nauw van Bath, Pas van Rilland, and the Beneden-Zeeschelde up to Antwerp Roads.
   - Main or secondary status does **not** give priority.
   - "F" parallel routes (Fietspad), e.g. F14–F37 and F42–F55 (NtM 1/25), are for inland and recreational craft. They sail in the same direction as the adjacent main fairway.
5. **Main waterways in the docks (HPV 8.3.2).** Traffic here has priority over side docks and lock exits, in both directions.
   - Right bank: kanaaldok B3 → past the Berendrecht/Zandvliet precautionary area → B2 → B1 → Hansadok → 5th Havendok → Amerikadok → Albertdok.
   - Left bank: Verrebroekdok → Waaslandkanaal.
6. **Precautionary areas at the locks (HPV 8.3.6).** Ships passing through must not hinder seagoing ships manoeuvring into the lock, especially when tugs are assisting.
7. **Exclusion zones:**
   - Wind farm safety zones (500 m) and masts (75 m). Polygons are in NtM 1/56–1/57: Belwind/Nobelwind, C-Power A/B, Northwind, Rentel, Norther, Northwester 2.
   - Nature protection zones SBZ 1–3 (NtM 1/53).
   - No anchoring within 250 m either side of submarine cables at sea (NtM 1/54), or within 200 m up/downstream of cables and pipes on the river (BZS 6 §7).
   - The Duc de Normandie wreck at 51°25.517'N 002°36.339'E (Westhinder anchorage).

## 2. Vessel classification (thresholds that switch rules on)

| Flag | Threshold | Source |
|---|---|---|
| Compulsory pilotage (Flemish waters) | Commercial ship **LOA > 80 m**. Exempt: inland vessels, ships at anchor, dredgers, government/naval ships, moves along the same quay. **Never exempt:** tankers loaded or not gas-free, towed and pushed convoys. | NtM 1/16–1/17 |
| Pilot in docks (non-tidal zone) | Seagoing ships, except shifting along the quay with lines fore and aft. **Always** if using a tug, carrying dangerous bulk liquid/gas, **visibility < 1000 m**, or **wind constantly ≥ 6 Bft**. | HPV 8.5.1 |
| Boatmen for mooring/unmooring | Mandatory for seagoing ships at the locks and behind them. Exempt: LOA < 80 m with safe access, ships with an inland tonnage certificate, warping along the quay. | HPV 8.4.2 |
| Oversized (river/sea) — shows 3 red all-round lights + cylinder | Oostgat/Sardijngeul: LOA ≥ 170 m or T ≥ 7.0 m. Sea, Western Scheldt, and Beneden-Zeeschelde downstream of the Doel–Lillo line: LOA ≥ 210 m or T ≥ 10.0 m. Upstream of Doel–Lillo: LOA ≥ 170 m or T ≥ 8.0 m. | NtM 1/31, BZS 28 |
| Oversized (docks) | Amerikadok, Noordkasteeldok, Albertdok, 2nd/3rd Havendok: LOA 180 m / B 27 m / T 10 m. Other docks: LOA 200 m / B 27 m / T 10 m. The comparison signs are lost in the PDF text, so read them as "≥", combined with "én" (and). | HPV 8.3.2 §7 |
| Needs a GNA Permit for Antwerp ("marginal") | LOA ≥ 300 m; B ≥ 45 m; air draught ≥ 60 m; T ≥ 12.0 m (Zandvliet–Berendrecht); T ≥ 12.5 m (Kieldrecht, tidal terminals); T ≥ 10.0 m (Kallo lock); T ≥ 8.0 m (berths upstream of Kallo). | JA22 art. 1 |
| Ultra-large container ship | LOA ≥ 350 m or B ≥ 51 m. Extra rules in §8. | JA22 3.3 / 4.3 |
| Tide-dependent, anchorage Wielingen-Zuid | T ≥ 14.0 m and cannot finish the passage in one tide | NtM 1/26 2.3.5 |
| Everingen / Put van Terneuzen anchorage permit | T ≥ 12.5 m | GB24 |
| Voyage Plan IMO2 gas tanker | By cargo and tank size (NtM 1/60 table 1). Example for LPG/propane/butane: largest tank ≥ 3000 m³ or total ≥ 15000 m³. | NtM 1/60 |
| Small vessel | LOA < 20 m. Gives way to all other ships; stays out of the fairway where practicable if < 12 m. | BZS 2, 9 §3, 18 §6 |
| Tug obligation | Tanker > 120 m: at least 1 tug, unless it has bow + stern thrusters, or a bow thruster and LOA ≤ 150 m. **Gas tanker > 120 m: always.** | HPV 8.6.3 |

## 3. Administrative timeline before movement (agent state machine)

Times are relative to the event in brackets.

| When | Action | Source |
|---|---|---|
| Up to 2 months before | Pre-notification and first berth request in APICS. The berth request includes the **mooring side**; HKD may impose a different side. The agent must keep the data current. | HPV 8.1.1, CP art. 16 |
| ≥ 6 months before (new class of ship) | Ship file for a new class with LOA ≥ 350 m or B ≥ 51 m (manoeuvring trials, speed table, etc.) | JA22 art. 5 |
| ≥ 3 weeks / 8 weeks before | Ship file for ships over 170 m going to the Scheldt quays upstream of Rijnkaai (cruise ships: 8 weeks) | NtM 1/39 |
| ≥ 72 h before entering the GNA area (≥ 14 days for complex cases) | Request permission for a special or extraordinary transport | NtM 1/30 |
| ≥ 24 h before entering the GNA area | Report dangerous cargo (SRW Annex 1) and any LNG fuel system on board. If the voyage is shorter than 24 h, report at departure from the previous port. | NtM 1/59 |
| ≥ 24 h before the pilot station / ≥ 12 h before leaving the anchorage | Everingen / Put van Terneuzen permit for T ≥ 12.5 m | GB24 |
| **≥ 6 h before the pilot station / ≥ 10 h before leaving the berth** | **GNA Permit** for marginal ships (arrival, departure, or change of anchorage) | JA22 art. 2 |
| ≥ 6 h before the pilot request time | Pilot order for an arrival: ETA, pilot required (yes/no/part), arrival type. Orders placed more than 24 h ahead must be reconfirmed 12–6 h before. The order becomes active 6 h before. | NtM 1/18 |
| ≥ 3 h before the pilot request time | Pilot order for a departure or shift. Behind the locks, the lock departure time set by HKD becomes the pilot time. | NtM 1/18 art. 11 |
| Delay > 1 h | Must be reported before the order becomes active. Otherwise the ship is delayed or the order cancelled. | NtM 1/18 |
| No VHF contact 1 h before the pilot time | The pilot order is cancelled | NtM 1/18 art. 9 |
| Pilot on board but ship not ready within 1 h | The order is cancelled and a new time is needed | NtM 1/18 art. 15 |
| Tugs, arrival from sea | Request when ordering the pilot; **place the tug order before passing buoy 35** | HPV 8.6.2 |
| Tugs, departure from behind the locks | Order ≥ 1 h before departure. The tug task activates when the lock plan is released. | HPV 8.6.2 §7 |
| Tugs, arrival from the Boven-Schelde | Request 6 h ahead, order 3 h ahead of Antwerp Roads | HPV 8.6.2 |
| ≥ 1 h before departure | A special transport announces itself to VTS | NtM 1/30 |

The ACC gives an **imposed arrival time (RTA) at CP**, or a departure clearance, only when all formalities are done (HPV 8.6.2 §8). Movement of a ship behind the locks starts only at the time the ACC approves (CP art. 16 §2).

## 4. Arrival types and pilot assignment

1. **Arrival types (NtM 1/18 art. 2, 1/32).** Exactly one is active at a time:
   - **ETA**: proceed on arrival at the pilot station.
   - **GTO**: proceed only from a given time.
   - **GTA**: required time of arrival at a reference point. For Antwerp the point is **CP**; for the Boven-Zeeschelde it is Antwerp Roads. Pilotage computes the boarding time backwards from it.
   - **BTV**: not allowed to proceed. Hold offshore or at anchor.
2. **Pilot queue.** First come, first served by pilot request time.
   - Priority overrides: ships in distress, then **tide- or current-dependent ships**, then ships ordered ahead by the authority.
   - A ship delayed by congestion gets a pilot within 6 h of being cleared (NtM 1/18 art. 17–18; art. 7).
3. **Marginal ships** get **priority at Vlissingen Roads**. The GNA sets the earliest and latest time at Vlissingen Roads (JA22 3.1).
4. **Storm pilotage (NtM 1/21–1/22).** Options are a SWATH pilot boat, shore-based pilotage (LOA), or waiting offshore.
   - LOA limits: Scheur/Wielingen LOA ≤ 175 m and T ≤ 8.0 m; Oostgat LOA ≤ 125 m and T ≤ 6.4 m.
   - **No shore-based pilotage upstream of Vlissingen Roads.** Excluded from it: special transports, IMO2 gas tankers, and ships carrying SRW Annex 1 §1–3 cargo.
5. **Tanker gas check at the pilot station (NtM 1/62).** A tanker still venting cargo vapour, or with cargo residue in its drip trays, gets **no pilot**. It is sent to an anchorage or out of the pilot area and needs a new pilot order.

## 5. Traffic rules on the river (BZS; the Western Scheldt regulation uses the same article structure)

1. **Keep to the starboard edge of the fairway** (art. 9 §1). Outside the fairway, keep to the starboard bank (§2).
2. **Crossing, entering or leaving the fairway** must not force a ship following the fairway to change course or speed. If there is a risk of collision, the crossing or entering ship gives way (art. 9 §4).
3. **Narrow passage, bend or berth with current running (art. 6 §4).**
   - The ship going **against the current waits** until the ship going **with the current** is through.
   - At slack water in a bend, the ship with the outer bend on its starboard side proceeds and the other waits.
   - At slack water in a narrows, the ship with no obstruction on its starboard side proceeds.
4. **Overtaking (art. 13), a local rule that differs from COLREG.**
   - The overtaking ship keeps clear.
   - A power-driven ship normally overtakes on the **port side** of the ship ahead. Signals: 2 long + 2 short; the overtaken ship answers with 1 short and moves to starboard.
   - Overtaking to starboard: 2 long + 1 short; answer 2 short.
   - **5 short** means overtaking is not possible.
   - The overtaken ship must make room and reduce speed.
   - **Sailing side by side is prohibited** unless it causes no hindrance (§10).
5. **Priority (art. 18).** A power-driven ship gives way to:
   - ships not under command;
   - **oversized seagoing ships**;
   - ships restricted in their ability to manoeuvre;
   - ships fishing outside the fairway.

   An oversized ship gives way only to ships not under command. It may not cross, enter or leave the fairway unless it can do so without forcing others to change course. Small ships give way to all others.
6. **Turning around (art. 10).**
   - Announce with 1 long + 1 short (turning to starboard) or 1 long + 2 short (turning to port).
   - Ships going against the current keep going; ships going with the current slow down.
   - **No turning in front of a harbour mouth** while other ships are entering or leaving it.
7. **No drifting sideways across the current** except for short moves (art. 6 §6).
8. **Anchoring** only outside the fairway, or at its edge. No stopping or anchoring off harbour mouths, in bends or on leading lines (art. 9 §5–6). No loading or bunkering unless moored (art. 9 §7).
9. **Ships ≥ 12 m in the main fairway** need an adequate engine. Ships < 12 m need an engine that can hold **≥ 6 km/h through the water** (art. 6 §2).
10. **Restricted visibility (art. 19).** Machinery must be ready for immediate manoeuvre. On hearing a fog signal forward of the beam, slow to the minimum steering speed.
11. **Keeping watch (art. 43).** A ship at anchor, moored or aground must have someone on board keeping watch and listening on VHF.
12. **Agreements between ships.** Ships make passing and overtaking arrangements directly with each other on the VTS traffic channel (phrases such as "green to green" or "I will overtake you on your port side"). VTS monitors and intervenes. A VTS **INSTRUCTION** is binding unless the ship reports a safety reason not to follow it; an **ADVICE** is optional (NtM 1/29).

## 6. Location-specific encounter restrictions

| Location | Rule | Source |
|---|---|---|
| **Sardijngeul** | Ships with LOA ≥ 80 m must not meet or overtake each other there | NtM 1/27 |
| **Pas van Borssele, Nauw van Bath** | Container ships ≥ 350 m or ≥ 51 m wide avoid meeting IMO2 gas tankers, special transports and oversized ships | JA22 3.3 / 4.3 |
| **Pas van Borssele, Bocht van Bath** | IMO2 gas tankers may not meet or overtake special transports, oversized ships or other IMO2 tankers | NtM 1/60 4.d4 |
| **Buoy 35 ↔ CP** | **≥ 3 nm** spacing between ships over 300 m and container ships ≥ 350 m sailing in the same direction | JA22 |
| Passage of a container ship ≥ 350 m | **All traffic from the Zandvliet–Berendrecht locks, Terneuzen and Hansweert is held** during the passage | JA22 |
| **Walsoorden harbour mouth** | Slow down in good time; **no overtaking between oversized ships** abreast of the mouth; avoid meetings between oversized ships near the mouth | GB25 |
| Vlissingen Roads | No two IMO2 gas tankers change pilots at the same time; IMO2 tankers may not make repeated crossings (e.g. compass adjustment) | NtM 1/60 |
| Container ship ≥ 350 m at Vlissingen | Pilots are changed using a separate pilot boat for each ship, as early as possible in the roads | JA22 |
| Cruise ship 200–265 m upstream of buoy 93 | Police escort; no ships anchored on the Antwerp or Oosterweel roads; listed berths kept empty | NtM 1/39 |

## 7. Speed

**No numeric speed limit for seagoing ships on the Western Scheldt or Beneden-Zeeschelde was found.** The legal rule is safe speed (BZS 6, HPV 8.1.7) plus the local reductions below. For timing, use the official planning speeds in §8.

| Context | Rule | Source |
|---|---|---|
| Everywhere | Safe speed. Wash and suction must not damage moored ships, their lines or structures. Follow any speed limits set by HKD. | HPV 8.1.7, CP 30, BZS 6 |
| Near ships showing "wash-sensitive" signals | Slow down, and stop if needed | BZS 6 §3 |
| Passing harbours, jetties, quays (whole GNA area) | Reduce speed, taking account of distance to the harbour mouth or quay | GB25 |
| Oostgat / Sardijngeul | Slow down in advance so that wash and bank suction don't endanger bathers; keep clear of the Vlissingen beach | NtM 1/27 |
| Minimum speed | Special transports ≥ 6 km/h through the water; small craft in the main fairway ≥ 6 km/h | NtM 1/30, BZS 6 |
| Last half-hour of a tidal slot (deep-draught ships) | Mean speed of about 14 kn is assumed | NtM 1/29 §6.1 |
| Typical observed (Western Scheldt) | 12–15 kn by AIS sampling | NTSB MAB-16/10 |
| Boven-Zeeschelde, inland craft only | 15 km/h (18 km/h for pleasure craft), RIS-km 8.0–36.1 | Zeeschelde waterway guide 2026 |
| Coastal marinas (Nieuwpoort, Blankenberge) | 5 kn in the channels, 3 kn in the docks | NtM 1/42 |

## 8. Tidal windows and draught for Antwerp (JA22)

1. **Permit and window.**
   - The tidal window is computed with WESP via Vaargeul 1 or the Westrond route, and accounts for air draught.
   - Density assumed: 1000 kg/m³ on the river and 1020 kg/m³ at sea.
   - **The permit is refused if the window at the start of the voyage is < 60 min**, or < 30 min for a change of anchorage.
2. **Start of voyage.** Arrival: pilot on the bridge, in the fairway, heading for port. Departure: ship on the river, heading for sea.
   - The ship should start at the **beginning of its window**.
   - Arrivals must leave the pilot station ≥ 60 min before the window closes. Departures must be on the river ≥ 60 min before it closes (NtM 1/33).
3. **No routine departures spread over two tides.** The GNA may cap the number of marginal ships per tide.
4. **Visibility ≥ 1000 m over the whole route at the start** for ships with LOA ≥ 300 m, B ≥ 45 m or T ≥ 12.5 m.
5. **Planning ground speeds (knots, JA22 Appendix 1):**

   | Ship type | Draught | Arrival, sea | Arrival, river | Departure, sea | Departure, river |
   |---|---|---|---|---|---|
   | Container | ≤ 14.5 m | 15 | 13 | 16 | 12 |
   | Container | > 14.5 m | 14.5 | 12.5 | 15.5 | 11.5 |
   | Bulk / tanker | any | 12 | 12 | 12 | 10 |

6. **Bulk carriers and tankers, arrival time at CP:**
   - T < 13.5 m: anywhere in the window.
   - T 13.5–14.5 m: CP no later than **HW + 1 h**.
   - T > 14.5 m to the right-bank locks: CP at **HW ± 15 min**.
   - T > 14.5 m to Kieldrecht: Deurganckdok mouth between **HW and HW + 40 min**.
7. **Maximum draught:**

   | Case | Arrival | Departure |
   |---|---|---|
   | Right-bank locks (Zandvliet/Berendrecht) | 15.56 m (NtM 1/33) | **14.5 m** |
   | Kieldrecht lock | 15.4 m for bulk carriers and tankers; more for container ships | 14.5 m |
   | Container ships | — | up to **15.2 m**, with a stated speed |
   | Bulk carriers / tankers | — | **14.0 m** (deviation allowed if the window is ≥ 60 min) |
   | Container ships ≥ 350 m: Zandvliet | — | 14.5 m |
   | Container ships ≥ 350 m: Deurganckdok / Noordzee Terminal | — | 15.2 m |

   Port reference values: tide-independent draught **13.10 m**; tide-bound maximum **16.0 m inbound / 15.2 m outbound** (Port of Antwerp-Bruges).
8. **Pilots.**
   - Two river pilots (at least one of the highest category) for ships with LOA ≥ 340 m or B ≥ 51 m, and for ships with LOA ≥ 300 m or B ≥ 45 m going to or from the locks.
   - Ships ≥ 350 m additionally need a simulator-trained pilot and the Full SNMS navigation system.
9. **Locks.**
   - Ships with B ≥ 43 m preferably use the **Berendrecht** lock.
   - The ship lies at the front of the chamber, leaving tugs room to work.
   - For container ships ≥ 350 m, the lock must be **empty and available from CP**.
   - Lock water levels are lowered to suit departures.
   - Container ships may leave on a rising tide with ≥ 1.0 m under-keel clearance in the lock or at the berth.
10. **Tidal terminals.** Ships berth according to the tide.
    - **Noordzee Terminal S901/S903 (overlap S905), ships over 300 m:** berth or unberth only on the rising tide up to HW + 1 h. **Not allowed from HW + 1 h until LW.**
    - Ships not moored head-out in Deurganckdok can only leave between the rising tide and HW.
11. **Container ships ≥ 350 m:**
    - At least 3 tugs available on arrival and at least 2 on departure.
    - The agent provides a **fallback berth** (Noordzee Terminal, Europa Terminal or Deurganckdok) available from CP onwards.
12. **The dock pilot reads the actual draught** before departure from behind the locks. A difference from the permit is reported to the GNA.

## 9. Weather and visibility gates

| Condition | Effect | Source |
|---|---|---|
| Visibility < 1000 m at the start (LOA ≥ 300 m / B ≥ 45 m / T ≥ 12.5 m) | No start | JA22, GB24 |
| Visibility < 1000 m | Special transports stop; pilot compulsory in the docks | NtM 1/30, HPV 8.5.1 |
| IMO2 gas tanker, visibility < 1000 m at sea / < 2000 m upstream of the De Nolle–Nieuwe Sluis line | No sailing; the GNA decides whether to anchor or continue | NtM 1/60 |
| Container ship ≥ 350 m, wind > 5 Bft at the locks | No arrival or departure permit | JA22 |
| Container ship ≥ 350 m, wind > 6 Bft (arrival) / > 7 Bft (departure) at tidal terminals | No permit. The wind trend must stay at or below the limit for ≥ 3 h after ETA and be falling. | JA22 |
| Wind ≥ 6 Bft constant | Pilot compulsory in the docks | HPV 8.5.1 |
| Everingen/Put van Terneuzen, mean wind ≥ 13.8 m/s (6 Bft) or ≥ 17.1 m/s (7 Bft) | Extra conditions apply, or the GNA decides whether the voyage starts (10-min mean at Terneuzen) | GB24 |
| Cruise ships upstream of the Kallo lock | Max 7 Bft (170–200 m) or 6 Bft (200–265 m) at the Boudewijn lock | NtM 1/39 |
| Extreme weather (GNA) | Selective or total ban on arrivals and departures, port areas closed, extra tugs | NtM 1/12 |
| Storm warning ≥ 8 Bft | Issued up to 18 h ahead; gale warning (6–7 Bft) up to 12 h ahead | NtM 1/11 |
| River cruise ship without passengers | May be allowed to sail at visibility ≤ 1000 m or significant wave height 1.5 m | NtM 1/29 §8.2.2 |

## 10. Locks, docks and berths (HPV)

1. **Locks.**
   - HKD assigns the lock, the time and the **order of entry**. Seagoing ships get a **turn number** shown on the signal mast.
   - Orders from lock control override the lock signals.
   - Weekly liner services to left-bank berths can get **fixed lock slots** (8.2).
2. **Dock priority.**
   - A main waterway has priority over side waterways and lock exits.
   - A dock-oversized ship has priority over everything except ships not under command, including at the cut-through and at bridges.
   - Between two oversized ships, the standard rules apply (8.3.2).
3. **Bridges (HPV 8.3.3–8.3.4, CP 35).**
   - Red or no light: keep clear and leave the bridge channel free.
   - Green: pass, keeping to the starboard bank. Green does not mean the water beyond is clear.
   - Lillo and Noordkasteel bridges:
     - Red + 2 yellow: under-passage allowed, one way only.
     - Red + 1 yellow: under-passage allowed both ways, keep to starboard.
     - Red over yellow: get ready; inland craft keep clear for a seagoing ship.
     - Yellow over green: seagoing ships only.
   - Marshalldok access, the 5th Havendok cut-through, bridges and jetty 512 have **size limits and a direction with priority**.
4. **Berths.**
   - HKD gives berth permission and can reassign a berth at any time.
   - The master must check the berth is safe.
   - A seagoing ship may moor **only if the berth is free over a safe length in time**; otherwise the master must find another berth (8.4.8).
5. **Mooring.**
   - No mooring at lock heads or in lock/bridge channels.
   - When two seagoing ships lie alongside each other, **the larger one goes against the quay**.
   - Follow HKD's limits on mooring width and number of ships abreast.
   - Enough crew on board to move the ship immediately.
   - **Tankers and tank barges may moor only at tanker berths.**
6. **Container terminals.**
   - Cranes topped (raised clear), with **no cranes within 2 bollards** of the bow or stern during arrival and departure.
   - **Deurganckdok: ships over 210 m moor bow towards the river (head-out).** HPV 2021 says 210 m; NtM 1/33 said 260 m. Use HPV.
7. **On board while moored.**
   - No propeller thrust while moored or in a lock; limit thruster use near quays.
   - No anchors in lock or bridge channels, lock chambers, within 25 m of a mooring buoy, or near cables.
   - Listing ships, or ships with loads sticking out, need permission to pass locks or bridges.
   - Moored ships light the side facing the fairway at night or when visibility is < 500 m.
   - Bunkering only by licensed suppliers. In the City Port: never under way and never LNG.
8. **Restricted view from the bridge.** When shifting in the docks, a ship must use a tug made fast forward (HPV 8.1.6, 8.6.3 §3).
9. **Pilots and tugs on the river stretch.** The master decides on tug use; on binding pilot advice for marginal ships. A tow move may start only once the ACC confirms it (HPV 8.6.2).

## 11. Anchoring (NtM 1/26, GB24)

1. **All anchoring needs GNA permission.** In Wielingen N/Z, Vlissingen Roads, Springergeul, Zuid-Everingen, Marlemon, Everingen and Put van Terneuzen, the normal maximum is **24 h**.
2. **Sea anchorages:** Westhinder, Oostdyck, Schouwenbank. Polygons are in NtM 1/26 §2.1.
3. **Anchorage by ship type:**
   - Ships with dangerous cargo that must show signals: **Wielingen Noord only**.
   - Ships with SRW Annex 1 §1–2 cargo: only Schouwenbank or Westhinder (Wielingen Noord in an emergency).
   - Ships ≤ 110 m with dangerous cargo, in nautical or weather difficulty: eastern part of Vlissingen Roads.
   - Tide-dependent ships with T ≥ 14.0 m: **Wielingen-Zuid**.
   - LNG ships for Zeebrugge without a pilot: Westhinder.
   - Interrupted IMO2 gas tankers: anchorage named by the GNA. Large gas carriers in force majeure: as far west as possible in Wielingen Noord, or Everingen A.
4. **Beneden-Zeeschelde anchorages** (assigned by Zandvliet): Schaar van Ouden Doel, Liefkenshoek (not above the tunnel), Meestoof (right bank, draught limits), Oosterweel, Rede van Antwerpen.
   - Seagoing ships anchor at the edge of the channel; others close to the bank.
   - Seagoing ships over 90 m bound for the Boven-Zeeschelde that need formalities anchor on the Oosterweel roads.
   - Ships with dangerous cargo may not anchor or moor along the Antwerp quays section.
5. **Everingen / Put van Terneuzen with T ≥ 12.5 m:** sail within the GNA tidal window or at the given RTA/RTD (GB24).

## 12. Dangerous goods and tankers

1. Tankers may not vent cargo vapour in the GNA area or at anchor, must stop before reaching the pilot area, and must have empty drip trays (NtM 1/62).
2. **IMO2 gas tankers (NtM 1/60):**
   - GNA clearance for the whole voyage, which can be revoked.
   - Fixed routes: inbound preferably via A1 + Scheur; outbound via Vaargeul 1; Westrond via Westpit, Rabsbank, NE Akkaert, Scheur, S4.
   - "IMO2" suffix on the radio; extra reports at buoys S3 (inbound) and S4 (outbound).
   - Voyage plan required; no shore-based pilotage.
   - VHF watch while at anchor.
3. **Banned liquefied gases** (e.g. chlorine, phosgene, hydrogen sulphide) may not be carried; chlorine, SO₂ and dimethylamine only with GNA permission (NtM 1/60 table 2).
4. **WETREP reporting** for tankers > 600 t carrying heavy crude, heavy fuel oil or bitumen (NtM 1/61).

## 13. Special and extraordinary transports (NtM 1/30)

1. GNA permission is required.
2. **Minimum tugs and pilots by tow length:**
   - Sea: ≤ 80 m: 1 tug + 1 pilot; 80–125 m: 1–2 tugs; 125–200 m: 2 tugs; ≥ 200 m: 3 tugs inbound / 2 outbound, Scheur/Wielingen route only.
   - River: 80–150 m: 2 tugs; 150–200 m: 3 tugs; ≥ 200 m: 3 tugs + 2 pilots.
3. Visibility ≥ 1000 m; ≥ 6 km/h through the water; no shore-based pilotage; announce ≥ 1 h before departure.

## 14. Incidents and damage

1. Report fire, collision, grounding, damage, list, loss of cargo, pollution, risk of sinking, or damage to hull, propeller or rudder.
   - To HKD before arrival at the pilot station, or immediately if it happens on the way (HPV 8.1.4).
   - To the MRCC on VHF 16 or 67 at sea (NtM 1/63).
   - To the police on the Beneden-Zeeschelde (BZS 44).
2. Warn approaching ships and keep the fairway clear.
3. **After an incident:** no entry into locks, no bridge passage, and no mooring or unmooring without HKD permission. HKD assigns a **compulsory berth** (HPV 8.1.4). A damaged ship on the river anchors where the GNA says until inspected (NtM 1/65).
4. A sunken vessel or obstruction must be marked and guarded (CP 65).

## 15. Communication

1. Only **Dutch or English** on VHF. A ship that can't use either may be held at a mooring or kept out of the area (NtM 1/29 §8, CP 11, HPV 8.1.16).
2. Continuous listening watch on the sector traffic channel and on the lock channel while in a lock.
3. Sign in when joining traffic (leaving a berth, anchor or lock) and sign off when leaving it (NtM 1/29 §5.3–5.4).
4. **AIS must be on and correct** at all times. In a tow, at least one unit transmits (HPV 8.1.17, CP 12–13). Pilots use GPS smoothing of ≤ 10 s (NtM 1/20).

## 16. City Port only (barges, river cruise ships, pleasure craft)

1. Seagoing ships, tankers and sea cruise ships are **banned** (CP 5 §5, 37).
2. Entry only with a berth assigned in advance; go straight to it (CP 14–15).
3. River cruise ships request a berth 1 month ahead; barges 48 h ahead.
4. Dinghies may navigate only 08:00–22:00.
5. Bridge rules as in §10.3; bridge VHF 62; City Port VHF 23.

## 17. Infrastructure reference data (for the environment model)

| Item | Value | Source quality |
|---|---|---|
| Berendrecht lock | 500 × 68 m, sill about −13.6 m TAW | Wikipedia / 2012 presentation |
| Zandvliet lock | 500 × 57 m, sill about −13.6 m TAW | 2012 presentation |
| Kieldrecht lock | 500 × 68 m, about −17.8 m TAW | Wikipedia |
| Kallo lock | 360 × 50 m (310 m between inner gates), sill −12.58 m TAW | binnenvaartinbeeld |
| Boudewijn lock | 360 × 45 m, −10.33 m TAW | nl.wikipedia |
| Van Cauwelaert lock | 270 × 35 m (34 m in one source), −9.83 m TAW | nl.wikipedia |
| Royers lock | 180 × 22 m, −6.42 m TAW | Wikipedia |
| Tidal range | About 3.7–4 m at Vlissingen, rising to about 5–5.7 m at Antwerp | Research papers |
| Tidal current | Up to about 3 kn in the Western Scheldt. One marina source gives flood 2–3 kn, ebb 3–4.5 kn. | Weak sources |
| Air draught | 380 kV crossing Zandvliet–Lillo (2020) built for ≥ 100 m clearance above highest water; WESP still checks air draught; permit needed if air draught ≥ 60 m | Elia |

## 18. Environmental and other regulatory items

1. **Shore power.**
   - FuelEU Maritime: from 2030, container and passenger ships over 5000 GT must connect to shore power at TEN-T ports.
   - AFIR: ports must provide it by the end of 2029.
   - Port of Antwerp-Bruges targets shore power for the largest container ships by 2028.
   - City Port: generators are banned where a shore power connection is available (CP 28).
2. **Emission control.** The North Sea is a SOx ECA (0.10 % sulphur) and, since 2021, a NOx ECA for new ships. This comes from general knowledge and was not re-verified for this file.

## 19. Known gaps

1. No numeric speed limit for seagoing ships on the Scheldt was found. Use safe speed plus the JA22 planning speeds.
2. The full consolidated text of the **Scheepvaartreglement Westerschelde 1990** was not retrieved. Court rulings confirm it uses the same art. 9 and art. 13 rules as BZS.
3. **Havenonderrichtingen** (Antwerp port instructions) were not retrieved. They may hold dock speed limits and dimension limits for bridges and the cut-through.
4. A 2022 revision of HPV is reported; the 2021 text was used here.
5. Coordinates of the TSS (West Hinder) and the routing measures were not extracted.
6. Lock dimensions come from secondary sources; verify them with the Port of Antwerp-Bruges.

## Online sources

- Havenpolitieverordening Antwerpen 2021: https://www.itb-info.be/Uploads/pdf/havenpolitieverordening-antwerpen-2021.pdf
- Scheepvaartreglement Beneden-Zeeschelde: https://www.itb-info.be/Uploads/pdf/Scheepvaartreglement-voor-de-Beneden-Zeeschelde.pdf
- GB 01-2025 Walsoorden: https://zoek.officielebekendmakingen.nl/stcrt-2025-20943.pdf
- GB 03-2024 Everingen/Put van Terneuzen: https://zoek.officielebekendmakingen.nl/stcrt-2024-33414.pdf
- Port of Antwerp-Bruges nautical draught: https://www.portofantwerpbruges.com/en/shipping/maritime-services/nautical-draught-and-tides
- Port of Antwerp-Bruges shore power: https://www.portofantwerpbruges.com/en/our-port/climate-and-energy-transition/shore-power
- Western Scheldt court ruling (art. 9 / 13): https://www.bijzonderstrafrecht.nl/home/artikel-9-vierde-lid-onder-b-scheepvaartreglement-westerschelde-1990-geen-oplopend-schip-maar-schip-dat-een-vaargeul-wil-binnen-varen-met-kruisende-koerslijn
- NTSB MAB-16/10 (observed Western Scheldt speeds): https://www.ntsb.gov/investigations/AccidentReports/Reports/MAB1610.pdf
- Locks: https://en.wikipedia.org/wiki/Berendrecht_Lock, https://en.wikipedia.org/wiki/Kieldrecht_Lock, https://nl.wikipedia.org/wiki/Boudewijnsluis_(Antwerpen), https://nl.wikipedia.org/wiki/Van_Cauwelaertsluis, https://en.wikipedia.org/wiki/Royers_Lock, https://www.binnenvaartinbeeld.com/nl/haven_van_antwerpen/kallosluis
- Elia Scheldt crossing: https://elia.be/en/infrastructure-and-projects/infrastructure-projects/brabo-ii/20200824-commissioning-of-scheldt-crossing-and-upgraded-lillo-high-voltage-substation
- Zeeschelde waterway guide: https://www.binnenvaartkennis.nl/2026/10/zeeschelde-vaarweggids/
