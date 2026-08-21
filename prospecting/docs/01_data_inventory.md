# V0.1 Data Inventory

All URLs verified live on 2026-08-18 unless marked *(referenced, not fetched)*. Study area: Sultan–Gold Bar–Index corridor + Sultan Basin, with Monte Cristo/Silverton as historical reference. HUC8 **17110009 (Snohomish)**, HU4 **1711**.

**Priority key:** 🟢 = required for V0.1 scoring · 🟡 = required for the legal/access layer · ⚪ = Phase 2+, don't download yet.

---

## A. Mineralization / mines

### 🟢 A1. WA Mines and Minerals Database (WGS Digital Data Series 30 v2.0)
- **Agency:** Washington Geological Survey (WA DNR)
- **Download:** `https://fortress.wa.gov/dnr/geologydata/publications/data_download/ger_portal_mines_minerals.zip` (76 MB, updated Aug 2023)
- **Service:** `https://gis.dnr.wa.gov/site1/rest/services/Public_Geology/Mines_and_Minerals/MapServer` (MapServer only — no FeatureServer; per-layer `/query?f=geojson` works, maxRecordCount 2000)
- **Type:** Esri file GDB, EPSG:2927 (WA South, US ft — reproject immediately)
- **Layers that matter:** **12 Gold and Silver Locations** (points), **13 Metallic Mineral Locations**, **22 Historical Mining Districts** (polygons — Sultan, Index, Monte Cristo, Silverton), 8/9 IAML inactive-mine sites/features, table 73 scanned-document links keyed on `SITE_ID`
- **Key fields:** `SITE_ID, SITE_NAME, ALTERNATE_NAMES, PRIMARY_COMMODITY, COMMODITIES, ORE_MINERALS, LOCATION_ACCURACY, MINING_DISTRICT, ASSAYS (Y/N), PRODUCTION (Y/N), LEGAL_DESCRIPTION`
- **Usefulness:** the single best scoring input — purpose-built gold layer with per-record location accuracy and production flags, plus the district polygons the scoring model needs.
- **Limitations:** static since Aug 2023; compiled from the same 1940s–50s sources as MRDS, so heavy overlap/duplication with it; historical prospect positions can be off by hundreds of meters.

### 🟢 A2. USGS MRDS (legacy)
- **Agency:** USGS. **Frozen since 2011**; subsumes MAS/MILS.
- **Download:** `https://mrdata.usgs.gov/mrds/mrds-csv.zip` (flattened CSV, 44 fields, 23 MB) or `rdbms-tab.zip` (relational); AOI extractor `https://mrdata.usgs.gov/mrds/geo-inventory.php`; WFS `https://mrdata.usgs.gov/services/wfs/mrds`
- **Key fields:** `dep_id, site_name, dev_stat` (Producer / Past Producer / Prospect / Occurrence), `commod1/2/3`, deposit type, production text, **record-quality grade A–E**
- **Usefulness:** densest occurrence inventory for the corridor; `dev_stat` is the evidence gradient the scoring model runs on.
- **Limitations (serious):** positional errors 100 m–>1 km (section centroids, small-scale map digitizing); duplicate records from the MRDS/MAS-MILS merge; drop or down-weight grades D/E. Never treat raw MRDS point counts as independent evidence.

### 🟢 A3. USMIN Prospect- and Mine-Related Features
- **Agency:** USGS (v10.0, May 2023)
- **Download (WA extract):** `https://mrdata.usgs.gov/usmin/state/usmin-WA.zip` (1.3 MB shapefile)
- **What:** adits, shafts, prospect pits, tailings digitized from historical 7.5'/15' topo quads; `Ftr_Type` attribute, split point/line/polygon
- **Usefulness:** best positional accuracy of the three sources (±10–50 m, as-drawn on 24k topos); physical-workings density is a strong lode-source signal for Monte Cristo/Silverton slopes.
- **Limitations:** **no commodity attribute** — a pit is a pit; must be joined to A1/A2 by proximity for commodity. (The separate USMIN Mineral Deposit Database has no gold release — ignore it.)

**Dedup mandate:** the same mine appears in A1, A2 (sometimes twice), and as several A3 features. Fuse into site clusters (normalized name similarity + ~250 m buffer) before anything counts as "multiple records." Positional trust ranking: USMIN > WGS (respect its `LOCATION_ACCURACY`) > MRDS A–C > MRDS D/E.

### 🟢 A4. Historical bulletins (attribute enrichment + geology calibration, not geocodable layers)
All DNR PDFs; legacy `www.dnr.wa.gov/Publications/...` URLs 301-redirect to `dnr.wa.gov/sites/default/files/...`:
- **Bulletin 37** *Inventory of Washington Minerals Part II (Metallic)* — gold inventory: `.../ger_b37_part2_metallic_v1_2_gold-iron.pdf` (verified)
- **Bulletin 42** Huntting, *Gold in Washington* (1955) — statewide lode + placer inventory
- **Bulletin 36** *Geology and Ore Deposits of the Sultan Basin*
- **RI-6** *Mineral Properties of Snohomish County* (Silverton + Sultan districts)
- **IC-57** *Handbook for Gold Prospectors in Washington*; OFR *Placer Gold Mining in Washington*
- **Use:** justify the `geology_gold_assoc` ratings from these documents (validation requires literature-based, not point-derived, geology calibration — see docs/04). Also production tonnage/vein detail per site.

## B. Hydrography

### 🟢 B1. NHDPlus High Resolution, HU4 1711
- **Agency:** USGS. **Status: frozen** — NHD maintenance ended Oct 2023; Region 17 got no National Release 2 update. No fixes are ever coming, and that's acceptable for V0.1.
- **Download (verified):** `https://prd-tnm.s3.amazonaws.com/StagedProducts/Hydrography/NHDPlusHR/VPU/Current/GDB/NHDPLUS_H_1711_HU4_GDB.zip` (482 MB, 2024-02-29). Beta path also has FDR/FAC/DEM rasters (3.8 GB .7z) — skip for V0.1.
- **Type:** file GDB — `NHDFlowline` + VAA tables (`NHDPlusFlowlineVAA`, EROM flow)
- **Key fields:** `NHDPlusID`, `ReachCode` (filter `17110009*`), `StreamOrde`, `Slope`, `TotDASqKm`, `HydroSeq / UpHydroSeq / DnHydroSeq` (the downstream-walk keys), `LevelPathI`, `FCode`
- **Why not 3DHP:** the successor program's only download is an 11.9 GB national GDB and it **doesn't carry the VAA stack** (order, slope, drainage area, navigation) V0.1 depends on. Migrate later, not now.
- **Limitations:** Region 17 VAAs are beta quality — slope on short flowlines is noisy (1e-5 = "unknown"), drainage areas can err at divergences; flowline geometry predates recent channel migration (the braided Skykomish has moved, especially after the 2021 flood); EROM flows are modeled and ignore Sultan regulation.

### 🟢 B2. Watershed Boundary Dataset (WBD)
- **Download (verified):** `https://prd-tnm.s3.amazonaws.com/StagedProducts/Hydrography/WBD/HU2/GDB/WBD_17_HU2_GDB.zip` (2025-01-08) — clip locally to HUC8 17110009; read actual HUC10/12 codes from the data, don't hardcode.
- **Fields:** `huc10/huc12, name, areasqkm, tohuc`
- **Limitation:** 1:24k divides; ridgelines can be off tens of meters vs LiDAR — irrelevant at V0.1 scale.

## C. Terrain

### 🟢 C1. USGS 3DEP 10 m seamless DEM (context only in V0.1)
- **Download (verified):** `https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/n48w122/USGS_13_n48w122.tif` (474 MB, updated 2025-08-13) — **one tile covers the entire study area**
- V0.1 use: hillshade for the map, nothing else. Slope/drainage come from NHDPlus VAAs.

### ⚪ C2. 1 m LiDAR DEMs (Phase 2)
- **USGS 1m projects (verified tiles exist):** `WA_Western_North_2016` (Sultan–Gold Bar) and `WA_KingCounty_2021_B21` (Gold Bar–Index), `https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1m/Projects/...`, UTM10 10-km tiles x58–x61 / y529–531
- **WA DNR Lidar Portal (better catalog, verified):** `https://lidarportal.dnr.wa.gov/` — working query API (`/query?geojson=...`) and download-by-dataset-id. Corridor coverage: **Cascades North Wali 2023** (newest, upper Sultan/Spada), **King County East 2021**, **North Puget 2017** (primary Sultan–Gold Bar valley), plus legacy 2003–2007 flights.
- **Phase 2 bonus:** three vintages (2003/06 → 2017 → 2023) straddle the 2006 and 2021 floods — LiDAR differencing can show actual channel migration and bar turnover, feeding the replenishment score.
- **Limitations:** project seams with different vintages cross the corridor; no bathymetry (water surfaces flattened); canopy gaps in legacy flights.

## D. Flow / flood history (Phase 4 input; grab gauge IDs now)

### 🟢 D1. USGS gauges
| Site | Name | Status |
|---|---|---|
| **12134500** | Skykomish R. nr Gold Bar | **Active**, daily discharge since 1928; annual peaks 1928–2025; record 129,000 cfs (2006-11-06) |
| 12137800 / 12138160 | Sultan R. below diversion dam / below powerplant | Active — quantify the regulated reach |
| 12137500 | Sultan R. nr Startup | Historical, **pre-dam record** |
| 12134000 / 12133000 / 12135000 | NF Sky at Index / SF Sky nr Index / Wallace at Gold Bar | Historical |

- **API — use the new one:** `https://api.waterdata.usgs.gov/ogcapi/v0/` (collections `daily`, `peaks`, `monitoring-locations`). **Legacy `waterservices.usgs.gov` is being decommissioned Q1 2027** with brownouts starting late 2026 — do not build against it.

### ⚪ D2. NOAA NWPS flood categories
- `https://api.water.noaa.gov/nwps/v1/gauges/GLBW1` (Skykomish nr Gold Bar): action 12.2 ft / minor 15 / moderate 17 / major 19, historic crests + impact statements. Ready-made event-class thresholds for the Phase 4 reworking score.

### Culmback Dam — a hard fact the model must encode
Culmback Dam (Sultan RM 16.5, Stage I 1965, raised 1984 for the Jackson Hydro Project) impounds Spada Lake and **traps essentially all upper-Sultan bedload; the lower Sultan is flow-regulated and sediment-starved**. Lower-Sultan placers are largely a relict (pre-1965) resource replenished only by tributaries and reworking. The Skykomish mainstem is unregulated and keeps reworking with every major flood. This is why the scoring pipeline has a `dam_pass_factor` and `below_dam` flag.

## E. Geology

### 🟢 E1. WGS 1:100,000 surface geology
- **Download:** `https://fortress.wa.gov/dnr/geologydata/publications/data_download/ger_portal_surface_geology_100k.zip` (109 MB, updated Feb 2026)
- **Type:** GeMS-style file GDB; `geologic_unit_polygons` + faults/contacts + `unit_descriptions` table (join on unit label for age + lithology)
- Also available: 1:24k gdb (220 MB, Jun 2026 — coverage in the high country is quad-by-quad and spotty; check its map_index), 1:500k for context. USGS SGMC is just a staler repackaging of the same WA data — use WGS native.
- **Gold-association targets (from literature, for `geology_gold_assoc.csv`):** Index batholith (Oligocene granodiorite) margins and N–S shear zones (Index district veins); Tertiary intrusive margins near Monte Cristo (Au-Ag arsenopyrite veins); Sultan Basin polymetallic vein country (45 Mine, Williamson Ck); **and glacial outwash/alluvium units** in the valleys, which carry reconcentrated drift gold — do not leave these at zero.

## F. Ownership & legal 🟡

### F1. Land ownership stack (all needed; none alone is sufficient)
| Layer | Source | Notes |
|---|---|---|
| WA DNR Managed Land Parcels | `https://data-wadnr.opendata.arcgis.com` / geo.wa.gov | state trust land = **closed to panning without a DNR placer contract** |
| Non-DNR Major Public Lands (NDMPL) | same portal; REST `.../Public_Boundaries/WADNR_PUBLIC_Major_Public_Lands_NonDNR/MapServer` | federal/state/county/city/tribal ownership |
| USFS Surface Ownership / Basic Ownership | `https://data.fs.usda.gov/geodata/edw/datasets.php` | **admin boundary ≠ ownership** — the corridor is full of checkerboard inholdings; use the ownership layer, not the forest boundary |
| PAD-US 4.1 | `https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-data-download` | designation overlay (Wilderness, State Parks, NRCA); coarse boundaries — flag, don't adjudicate |
| Snohomish County parcels | `https://snohomish-county-open-data-portal-snoco-gis.hub.arcgis.com/datasets/snoco-gis::parcels` | updated ~3×/week; the private-land truth along valley bottoms (owner name, use code); StatePlane ft |

### 🟡 F2. BLM MLRS mining claims
- **Service (verified):** `https://gis.blm.gov/nlsdb/rest/services/HUB/BLM_Natl_MLRS_Mining_Claims_Not_Closed/FeatureServer/0` (polygons, EPSG:4269, geojson export, pagination at 2000). Closed-claims sibling service exists *(referenced)*.
- **Fields:** `CSE_NR` (MLRS serial), `LEG_CSE_NR` (legacy WMC serial), `CSE_NAME`, `CSE_TYPE_NR` (lode 384101 / placer 384102 / mill), `CSE_DISP` (disposition), `RCRD_ACRS`, `QLTY`
- **Hard limitation:** geometry is **PLSS-section-level**, not surveyed boundaries — a 20-acre claim renders as its whole quarter/quarter-quarter section(s); overlaps stack. Treat as "claim exists somewhere in this section → research serial + get permission." Claimant detail lives in MLRS public reports (reports.blm.gov), not the GIS layer.
- **Interpretation trap:** Monte Cristo/upper corridor sits in Wild Sky / Henry M. Jackson Wilderness — **withdrawn from mineral entry**. Claim absence there is regulatory, not geological. Never feed claim density into the prospectivity score.
- **Known local reality:** Horseshoe Bend (Sultan R.) is reportedly held by prospecting-club claims — verify serials in MLRS before treating it as open.

### 🟡 F3. Legal rules (current as of 2026-08-18) → `access_rules` table
- **WDFW Gold and Fish pamphlet, May 19, 2021 edition, is still current** (verified on WDFW's site) and acts as the HPA for **non-motorized** methods: `https://wdfw.wa.gov/sites/default/files/publications/02150/wdfw02150.pdf`. Carry a copy in the field.
- **Motorized/suction dredging is effectively unavailable here:** ESHB 1261 (Laws of 2020, eff. June 2020 — *not* 2023-24) removed motorized/gravity-siphon methods from pamphlet coverage and prohibited them in ESA critical-habitat waters (essentially the whole anadromous Skykomish/Sultan/Wallace system); elsewhere they need an individual HPA + Ecology NPDES permit. WAC 220-660-300/-305.
- **Work windows (from the 2021 pamphlet; re-verify against the printed table before fieldwork):**
  - Skykomish mainstem & SF Skykomish: **Aug 1–15** (short!)
  - NF Skykomish below Deer Falls, Sultan below RM 15.7, Wallace below the falls, Olney Ck below falls: **Aug 1–31**
  - Above anadromous barriers (NF Sky above Deer Falls: Aug 1–Feb 28; Sultan above RM 15.7: Jul 16–Feb 28; Wallace/Olney above falls: Aug 1–Feb 28) — long windows
- **USFS (Mt. Baker–Snoqualmie):** hand panning = casual use under 36 CFR 228A, no permit on open FS land; pamphlet still governs in-water work. **Wilderness areas: treat as closed** in the GIS (withdrawn from entry; hand-pan legality ambiguous — flag `restricted`).
- **State Parks:** panning/sluicing/dredging **not allowed in any state park** → Wallace Falls SP is closed.
- **DNR trust land:** closed absent a placer contract (DNR's own pamphlet, verified quote). Matters in Sultan Basin / Morning Star NRCA.
- **Skykomish is a WA State Scenic River (RCW 79A.55)** — state designation with State Parks overlay; not a federal Wild & Scenic river. No prospecting-specific ban found; noted as `unknown` overlay pending confirmation.
- **DNR's own panning-locality list** (Recreational Gold Panning pamphlet): Horseshoe Bend, Sultan Canyon, Sultan, Gold Bar, "Bench" (Skykomish) — useful as V0.1 sanity-check sites *and* as validation targets.

---

## Download size budget (V0.1)
~0.8 GB total: NHDPlus HU4 (482 MB) + WBD 17 (~70 MB) + WGS mines (76 MB) + WGS 100k geology (109 MB) + MRDS CSV (23 MB) + USMIN WA (1 MB) + ownership/claims GeoJSON clips (small). The 10 m DEM tile (474 MB) is optional (hillshade only). No LiDAR in V0.1.

## Environment note (this repo's pipeline)
The sandbox egress proxy blocks some `.gov` hosts directly; `prd-tnm.s3.amazonaws.com` supports anonymous ListObjectsV2 and direct GETs and is the reliable scripted path for USGS staged products. WA DNR downloads should target the `fortress.wa.gov/dnr/geologydata/...` ZIPs; the DNR REST services may require tokens for anonymous JSON in some configurations.
