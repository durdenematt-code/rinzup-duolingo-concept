# V0.2 — Expanded area + authoritative bulk sources (2026-08-18)

## What changed

### 1. Study area

`BBOX_4326` grew from `(-121.95, 47.75, -121.30, 48.10)` to
`(-122.30, 47.75, -121.25, 48.35)`, and the scored network went from one HUC8
to four (`common.SCORED_HUC8S`):

| HUC8 | Basin | Why |
|---|---|---|
| 17110009 | Skykomish | original V0.1 corridor (Sultan–Gold Bar–Index) |
| 17110008 | Stillaguamish | SF Stilly: Granite Falls → Silverton veins; NF Stilly: Arlington–Oso (Deer Creek) |
| 17110006 | Sauk | SF Sauk headwaters = **Monte Cristo district**, down to Darrington |
| 17110011 | Snohomish | Pilchuck River side of Granite Falls |

Monte Cristo and Silverton occurrences — reference-only points in V0.1 because
their drainages weren't scored — now snap to scored segments like everything
else. Basins are clipped at the bbox edge, which truncates downstream
navigation there (same behavior V0.1 had for the Skykomish).

### 2. Occurrence sources: service caches → authoritative bulk downloads

New stage **01b_import_local.py** rebuilds the committed `data/raw/` extracts
from full local downloads instead of bbox-limited web-service queries:

| Extract | Now built from | Notes |
|---|---|---|
| `wgs_gold_silver.geojson`, `wgs_metallic.geojson`, `wgs_mining_districts.geojson` | DNR GER portal `WGS_Mines_Minerals.gdb` | identical schema to the old MapServer extracts |
| `mrds.geojson` | USGS MRDS `rdbms-tab` (MRDS.txt + Commodity.txt) | `code_list` rebuilt primaries-first from the Commodity table — same semantics stage 02's `gold_primary` check relies on |
| `usmin_points.geojson` | USGS USMIN `usmin-WA` shapefile | columns lowercased to match the old WFS cache; no more lat/lon axis swap |

New stage **01c_refetch_extracts.py** refetches the overlay extracts (100k
geology GeMS layer 11, NonDNR public lands, DNR managed lands, BLM active +
closed claims) from the live ArcGIS endpoints with paginated GeoJSON queries —
run it whenever the bbox changes. (gis.blm.gov requires a non-default
User-Agent.)

### 3. Geology ratings

`config/geology_gold_assoc.csv` gained 76 units for the expansion area (names
resolved from the DNR 100k DMU table). Rated ≥2 (i.e., scoring-relevant):
Granite Falls stock `Eigd(g)` and the Squire Creek phase at Granite Lakes
(Silverton/SF Stilly vein intrusives), two more Barlow Pass Volcanics phases
and the Dead Duck pluton (Monte Cristo/Grotto families), plus the usual
outwash/ice-contact/older-alluvium drift-gold carriers. Glaciomarine drift,
lahars, Chuckanut/Bulson sediments, and the Darrington–Shuksan–Chiwaukum
metamorphics rate 0.

## Run results (v02, 2026-08-18)

- **1,396 raw records** (398 WGS, 998 MRDS) → 885 gold → **411 fused sites**
  (V0.1: 340) — 34 placer sites, 76 past producers, 242 multi-source sites.
- **46,201 stream segments** (V0.1: 13,893) across the four basins.
- All 411 occurrences snapped within 1,500 m of a scored segment (V0.1 left
  Monte Cristo/Silverton unsnapped); 58,945 segment–occurrence influence pairs
  on 4,185 segments.
- Top drainages per basin: NF Skykomish 67.9 (unchanged best), **SF
  Stillaguamish 66.4** (below Silverton), **SF Sauk 65.7** (below Monte
  Cristo) — the expansion districts score right where the literature says they
  should, without being told about districts.
- **Validation** (10 seeds, 5 placer clusters held out each, from 34 placers /
  17 clusters): matched AUC mean **0.75** (min 0.48, max 0.86), river-scale
  AUC mean **0.80**, naive-baseline mean 0.70 (model − naive = **+0.05**).
  More holdout data than V0.1 and the model still beats the
  distance-to-nearest-source baseline.

## Notes / open items

- Culmback Dam still snaps 841 m from the Sultan mainstem flowline (the
  reservoir thalweg) — pre-existing V0.1 behavior, correct river, works fine.
- The WGS district polygons still blanket ~88% of segments (administrative
  divisions, not mineralized zones); district weight stays zeroed, map layer
  only.
- The **field sampling plan was re-drawn over the expanded area**
  (2026-08-18, superseding the V0.1 draw from the day before): 35 sites
  (15 HIGH / 10 MID / 10 LOW), now **ordered by drive time from home**
  (Everett). Stage 08 queries the OSRM demo server for car-profile drive
  times; each site carries `drive_min` (to the nearest OSM-mapped road) and
  `road_snap_km` (the remaining off-road approach). Closest HIGH sites: SF
  Stillaguamish at Silverton (~74 min, roadside via the Mountain Loop);
  the SF Sauk / Monte Cristo cluster is ~94 min plus a 2–4.5 km walk up the
  gated Monte Cristo road. The empty-log guard means re-runs never overwrite
  a `field_samples_log.csv` that has entries.
- **Site ids are basin-coded**: `<basin>-<band><nn>` (SK Skykomish, ST
  Stillaguamish, SA Sauk, SN Snohomish-Pilchuck), numbered by score within
  basin+band — `ST-H01` is the best HIGH site in the Stillaguamish. Historical
  district (Silverton / Index / Monte Cristo / Darrington / …) and HUC10
  drainage are attribute columns for sorting and pattern analysis, kept out of
  the id because the WGS district polygons tile most of the corridor. Sites
  are persisted to the GeoPackage (`sample_sites` layer) and drawn on the web
  map as labeled dots (red/blue/green = HIGH/MID/LOW).
- Reference PDFs downloaded alongside the data (DNR Bulletin 42 *Gold in
  Washington*, RI-6 Snohomish County mineral properties) back the new geology
  ratings; not machine-read by the pipeline.
