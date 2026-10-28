# Scheldt approaches – simulation dataset (built 2026-10-28)

**Not for navigation.** Area: 2.30–4.45°E, 51.10–51.80°N (Westhinder to the Belgian border near Bath).

## Vertical datum: matches Reeds
Reeds gives tidal heights above **chart datum, which is LAT** for Belgian and Dutch ports (Vlissingen, Westkapelle, Zeebrugge, Terneuzen, Hansweert, Bath).
All depths here are **metres below LAT**:

    water depth now = depth_m + Reeds tide height (for the nearest/interpolated port)

Positive values are charted depth. Negative values are drying heights, as on a chart.

## Files
| File | Content |
|---|---|
| `scheldt_depth_LAT_wgs84.tif` | Float32 depth grid, EPSG:4326, about 21 × 20 m cells. Land is nodata. |
| `scheldt_depth_source_wgs84.tif` | Source per cell: 1 = Rijkswaterstaat 20 m (surveys to 2024), 2 = EMODnet DTM (~115 m), 3 = land |
| `scheldt_navigation.gpkg` | Vector layers, listed below |
| `preview_*.png` | Quick-look maps |
| `scripts/` | Python used to build everything, so you can re-run it |

### GeoPackage layers
- `buoys_nl` (594): Dutch floating marks for the Westerschelde, its mouth and the Dutch North Sea approaches. Fields are name, category (lateral/cardinal/…), shape, colour, topmark, light (e.g. `Iso G 8s`), racon, fairway and s57_id.
- `fixed_marks_lights_nl` (101): fixed beacons and lights, with function, light height and sector table (`colour->bearing`).
- `anchorages` (17), each with an `accuracy` field:
  - Westhinder and Oostdyck: official polygons from the Belgian marine spatial plan 2026.
  - Schouwenbank: official coordinates from GNA notice GB 01-2019.
  - Everingen A–E and Put van Terneuzen A–B: official centre and radius.
  - Wielingen Noord/Zuid, Rede Vlissingen (+ eastern part), Springergeul, Zuid Everingen, Marlemon: **approximate**. Each is the convex hull of the boundary buoys named in GB 01-2019, and shore-side limits are not included.
- `anchor_berth_centres`: centre points of the anchor berths.
- `shipping_zones_be` / `shipping_lines_be`: Belgian traffic separation schemes, precautionary areas, area to be avoided, and the Westerschelde-approach deep-water route.
- `land_gshhg`: land polygon used for masking.

## How the depth grid was made
1. Rijkswaterstaat `bodemhoogte_20mtr_2024` (relative to NAP) was converted to LAT cell by cell with **NLLAT2018** (Dutch Hydrographic Service, NAP−LAT separation 1.4–3.1 m in this area).
2. EMODnet DTM (already relative to LAT) fills everything else. The edge between the two is blended over about 200 m.
3. Check: where both datasets cover open water, Rijkswaterstaat minus EMODnet has a median of **+0.15 m**, so the datums agree.
4. EMODnet cells on land (GSHHG coastline) were set to nodata, because EMODnet shows Dutch polders below LAT.

Spot checks (deepest point across the channel): Wielingen 15.8–16.2 m, Scheur west 18.3 m, Vlissingen 23 m, Hansweert 28 m, Bath 20.5 m.

## Known gaps
- **Belgian buoys are missing.** Rijkswaterstaat data stops at the border (Scheur/Wandelaar, Zeebrugge approach, A-Zuid etc. are not included). OpenStreetMap/OpenSeaMap could not be reached from the build environment. Rerun once the Overpass API is reachable, or add marks from a current Belgian chart or notices to mariners.
- **Belgian waters use EMODnet (~115 m).** The 20 m Flemish Hydrography grid server (`bathy.agentschapmdk.be`) no longer resolves. Rijkswaterstaat survey coverage does extend into the Wielingen/Scheur east of about 3.0°E.
- **The Zeeschelde (Belgian border to Antwerp) is not covered** by any of the open sources used.
- The Scheldt is dredged continuously and buoys are moved often, so treat this as a snapshot.

## Sources and licences
- Rijkswaterstaat bodemhoogte 20 m and Vaarwegmarkeringen Nederland: CC0.
- NLLAT2018 (Dienst der Hydrografie): CC0.
- EMODnet Bathymetry DTM: CC-BY 4.0, *"EMODnet Bathymetry Consortium"*.
- Belgian marine spatial plan, shipping zones (RBINS): CC-BY 4.0.
- GNA Gezamenlijke Bekendmaking GB 01-2019 (Staatscourant 2019-21256).
- GSHHG coastline: LGPL.
