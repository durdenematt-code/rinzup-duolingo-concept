# V0.1 Architecture: GIS Stack and Data Model

## 1. Recommended stack

Guiding principle: V0.1 is a **batch pipeline that produces one GeoPackage and one map**. It is not a service, not a database server, not an ML system. Every tool below was chosen to keep it that way.

### Use these

| Tool | Role | Why |
|---|---|---|
| **Python 3.11+** (managed with `uv`) | Pipeline language | Everything scriptable and reproducible; `uv` avoids conda pain |
| **GeoPandas + Shapely 2** | Vector processing | Snap occurrences to streams, spatial joins, buffers, dissolves — 90% of V0.1 is this |
| **PyArrow / GeoParquet** | Intermediate storage | Fast columnar intermediates between pipeline stages |
| **GeoPackage (.gpkg)** | Canonical output database | Single file, opens directly in QGIS, supports multiple layers + plain tables, SQLite underneath so you can query it |
| **QGIS 3.34+ LTR** | Viewing, styling, manual QA, printing maps | Free, the standard; you will live in it for QA. Not used for processing logic (that stays in Python so it's reproducible) |
| **Folium or MapLibre GL (static HTML export)** | Interactive web map | Self-contained HTML file with clickable stream segments; no server needed |
| **PyYAML** | Scoring weight config | Every weight lives in `weights.yaml`, never hardcoded |

### Explicitly deferred (do not install for V0.1)

| Tool | Verdict |
|---|---|
| **Rasterio / WhiteboxTools** | Phase 2. Needed for LiDAR terrain-trap work (valley confinement, terraces, gradient breaks from DEM). V0.1 uses stream attributes that NHDPlus already computed (slope, drainage area), so no raster processing is required at all. |
| **PostGIS** | Overkill. A few tens of thousands of stream segments for one county corridor fits in memory. PostGIS earns its complexity when you go statewide or multi-user. |
| **DuckDB Spatial** | Nice, not needed. GeoPandas handles V0.1 volumes. Revisit if you go statewide (DuckDB reads GeoParquet larger-than-memory). |
| **GRASS GIS** | Its watershed tools (`r.watershed`, `r.stream.order`) are excellent but redundant: NHDPlus HR ships pre-computed flow navigation. Reconsider only if NHDPlus navigation proves broken in the study area. |
| **QField / Mergin Maps** | Phase 2 field app — but note it now: it is the reason the field-sample schema below is designed as a flat attribute form. Do not build a custom mobile app; QGIS-native mobile forms already do offline capture with GPS + photos. |

### Pipeline layout

```
prospecting/
  config/
    weights.yaml          # all scoring weights, decay constants, thresholds
    study_area.geojson    # corridor boundary polygon
  data/
    raw/                  # downloads, never edited (gitignored)
    interim/              # cleaned GeoParquet per source
    prospect.gpkg         # canonical output: all layers + score tables
  pipeline/
    01_download.py        # fetch each source (idempotent, caches raw/)
    02_clean_occurrences.py  # merge MRDS+USMIN+WA records, dedup, flag gold/placer
    03_build_network.py   # clip NHDPlus HR to study area, validate navigation
    04_link_sources.py    # snap occurrences to segments, walk downstream
    05_score.py           # apply weights.yaml → scores table
    06_validate.py        # holdout experiment (docs/04)
    07_map.py             # QGIS styling files + interactive HTML export
  docs/
```

Each stage reads the previous stage's output from disk, so you can rerun any single step. Score runs are versioned (see `score_runs` below) so changing weights never silently overwrites history.

## 2. Data model

Canonical storage: layers and tables inside `prospect.gpkg`. CRS: **EPSG:26910 (NAD83 / UTM zone 10N)** for all analysis — meters, correct for western WA. Store a copy of geometries in EPSG:4326 only at web-map export time.

ID convention: every record keeps its **source-native ID prefixed with the source** (`mrds:10067222`, `wadnr:MI-123`, `usmin:...`, `nhd:55000900012345`), plus an internal integer key. Never mint IDs that lose the link back to the authority record — you will need it to chase down data problems.

### `occurrences` — unified mineral occurrence/mine table

One row per *deduplicated* site, merging MRDS + USMIN + WA DNR records. This is deliberately one table, not separate `mines` / `mineral_occurrences` / `placer_occurrences` tables: the source databases do not draw those lines consistently, and modeling them as separate tables would bake their inconsistency into the schema. Distinguish with typed columns instead.

| Field | Type | Notes |
|---|---|---|
| `occ_id` | int PK | internal |
| `source_ids` | text | semicolon list of contributing records, e.g. `mrds:10067222;wadnr:...` (dedup merges several) |
| `name` | text | site name |
| `commodities` | text | full commodity list from source |
| `is_gold` | bool | gold appears as primary or secondary commodity |
| `deposit_class` | text enum | `placer` / `lode` / `unknown` — from source deposit-type fields plus name heuristics ("placer", "bar", "gulch") |
| `dev_status` | text enum | `occurrence` / `prospect` / `mine` / `producer` (past producer) — the single strongest evidence gradient in the data |
| `production_note` | text | free text on recorded production |
| `position_conf_m` | int | estimated positional uncertainty in meters (source-dependent, see data inventory) |
| `dup_cluster_id` | int | dedup cluster this row came from; audit trail lives in `occurrence_members` |
| `snapped_segment_id` | int FK | stream segment assigned in step 04 |
| `snap_dist_m` | real | distance moved when snapping — large values weaken confidence |
| `geom` | POINT | |

Companion table `occurrence_members(occ_id, source, source_id, raw_name, raw_geom)` preserves every raw record before dedup so merges are reversible.

### `stream_segments` — NHDPlus HR flowlines (clipped to study area)

| Field | Type | Notes |
|---|---|---|
| `segment_id` | int PK | internal |
| `nhdplusid` | text | NHDPlus HR permanent ID |
| `gnis_name` | text | "Sultan River", "Wallace River"… |
| `huc12` | text | |
| `stream_order` | int | Strahler |
| `slope` | real | from NHDPlus VAA |
| `drainage_area_km2` | real | from VAA |
| `length_km` | real | |
| `hydroseq`, `dnhydroseq`, `uphydroseq` | text | NHDPlus navigation keys — these are what make downstream walking trivial |
| `ftype` | int | keep StreamRiver/ArtificialPath through lakes flagged; drop canals/pipelines |
| `geom` | LINESTRING | |

### `watersheds` — WBD HUC10 + HUC12 polygons

`huc_code (PK)`, `name`, `level`, `geom`.

### `geology_units`

| Field | Type | Notes |
|---|---|---|
| `geo_id` | int PK | |
| `unit_symbol`, `unit_name`, `lithology`, `age` | text | from WGS 100k geodatabase |
| `gold_assoc` | int 0–3 | **manually assigned** V0.1 favorability class from literature (see scoring doc) — 0 none, 3 known gold host. This is a judgment call and lives in a reviewable CSV (`config/geology_gold_assoc.csv`), not buried in code |
| `geom` | POLYGON | |

### `claims` — BLM MLRS mining claims

| Field | Type | Notes |
|---|---|---|
| `claim_id` | int PK | |
| `blm_serial` | text | MLRS serial number |
| `claim_name`, `claimant` | text | |
| `claim_type` | enum | `placer` / `lode` / `mill` / `tunnel` |
| `case_status` | enum | `active` / `closed` |
| `located_date`, `last_assessment` | date | |
| `geom` | POLYGON | **section-level only** — see limitations in data inventory; a claim polygon means "somewhere in this ~640-acre section", not a surveyed boundary |

### `ownership`

`own_id PK`, `owner_class` enum (`usfs` / `dnr_trust` / `state_parks` / `wdfw` / `county` / `city` / `private` / `tribal` / `other_federal`), `admin_name`, `source`, `geom POLYGON`.

### `access_rules` — the legal layer, kept separate from geology on purpose

| Field | Type | Notes |
|---|---|---|
| `rule_id` | int PK | |
| `applies_to` | text | HUC12, named stream, ownership class, or specific polygon |
| `rule_type` | enum | `open_casual` / `permit_required` / `seasonal_window` / `claim_permission_needed` / `closed` / `unknown` |
| `work_window` | text | e.g. allowed in-water work window from current WDFW rules |
| `source_doc`, `source_date` | text | citation — rules change; every rule must carry its provenance and date |
| `geom` | POLYGON nullable | null when `applies_to` references segments/ownership |

### `field_samples` — designed now, used from day one of fieldwork

| Field | Type | Notes |
|---|---|---|
| `sample_id` | int PK | |
| `ts` | datetime | |
| `geom` | POINT | GPS |
| `segment_id` | int FK | auto-snapped |
| `pans` | int | number of pans processed |
| `material_l` | real | approx. liters of material |
| `colors` | int | count of gold colors — **0 is a valid and important value** |
| `est_gold_mg` | real nullable | |
| `largest_particle_mm` | real nullable | |
| `gold_character` | enum | `flour` / `fine` / `flake` / `coarse` / `nugget` / `none` |
| `black_sand` | int 0–3 | qualitative |
| `bedrock_present` | bool | |
| `sediment_desc` | text | gravel size, imbrication, clay layers… |
| `water_level` | text + `gauge_cfs` real | qualitative note plus the USGS gauge reading that day (auto-fillable later) |
| `site_type` | enum | `inside_bend` / `bedrock_crevice` / `boulder_riffle` / `bench_terrace` / `trib_junction` / `other` |
| `photos` | text | file paths |
| `notes` | text | |

Every sample — including empty pans — is a labeled data point for future calibration. The schema treats a zero-color pan identically to a rich one.

### `scores` + `score_runs` — versioned model output

`score_runs(run_id PK, ts, weights_yaml TEXT, code_version, holdout_seed nullable)` — the full config is snapshotted into the run row.

`scores(run_id FK, segment_id FK, source_score, transport_score, confidence_score, total_score, top_occ_id FK, top_occ_dist_km, n_upstream_gold, claim_conflict BOOL, access_status TEXT)` — one row per segment per run. The map always renders a named run, so two people (or you in six months) can compare runs instead of overwriting them.
