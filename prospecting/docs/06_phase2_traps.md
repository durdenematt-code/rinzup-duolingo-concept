# Phase 2 — LiDAR terrain traps (stage 09)

Fills the 30 reserved trap points. Run:

    .venv/bin/python pipeline/09_traps.py     # -> data/interim/segment_traps.parquet

## Data

USGS 3DEP 1 m bare-earth DTM, project **WA_Western_North_2016**, from
`prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1m/Projects/...`.
Tiles are 10 km UTM-10N squares named `x<E/10km>y<N/10km>` where **y is the
tile's TOP edge** (tile x61y532 spans N 5310000-5320000). Getting this
backwards downloads the wrong ground — verify with `rasterio.open().bounds`
before trusting coverage.

Downloaded: x60y532, x60y533, x61y530, x61y531, x61y532, x61y533, x62y531,
x62y532 (~1.5 GB, gitignored).

## Metrics (per segment)

| Metric | Meaning | Why it traps gold |
|---|---|---|
| `grad_break` | max downstream **decrease** in channel slope | competence drops, coarse gold drops. Best single DEM signal. |
| `release` | max downstream widening of valley | confinement release = deposition |
| `valley_w` | valley width 5 m above channel (median) | narrow = bedrock canyon, scour + crevices |
| `curv` / `sinuosity` | planform curvature | inside-bend point bars |
| `plunge` | max local channel slope | waterfall/chute -> plunge pool below |

`trap_score` (0-30) = percentile-ranked mix: 0.30 grad_break, 0.20 release,
0.20 confinement, 0.15 bend, 0.15 plunge. Ranks are computed **within the
LiDAR-covered set**, so a trap_score is relative to other covered segments,
not absolute.

## Limits — read before trusting

1. **No bathymetry.** Bare-earth LiDAR flattens water surfaces. Every metric
   describes the valley, not the streambed. Actual bedrock crevices in the
   wetted channel are invisible.
2. **Flowline/DEM mismatch.** NHD geometry is 1:24k and predates the 2016
   flight; on small creeks the mapped line can sit tens of metres off the
   real channel, so cross-sections may not be centred on it. Metrics are
   reach-scale (~100s of m), NOT spot-scale.
3. **Coverage is patchy.** Valid-data fraction by tile ranges 15%-99%. Only
   4,016 of 46,201 segments got metrics. Absence of a trap score means no
   data, never "no traps".
4. **2016 vintage.** Post-2016 channel change is invisible; the 2021 flood
   reworked some of this ground.
5. **`bedrock` is a proxy**, from valley-wall steepness plus mapped geology -
   it is not a bedrock-exposure map.
6. Newer/denser coverage exists (DNR Cascades North Wali 2023, King County
   East 2021) on lidarportal.dnr.wa.gov, which this environment cannot
   reach. Worth adding from the desktop for upper Silver Creek / Monte Cristo.

## First results (coarse profile + traps, legal + unclaimed only)

Highest combined scores overall are on the **South Fork Sauk** near Blake
Placer / Keystone (full 72-77) - but that reach is CLOSED (Aug 1-15 window)
and sits in the Monte Cristo arsenic cleanup area.

In-window (Skykomish basin) leaders:

| Creek | Full | coarse | trap | km2 | slope | valley w | Coords |
|---|---|---|---|---|---|---|---|
| Silver Creek | 67.5 | 56.4 | 11.1 | 31.8 | 5.7% | 70 m | 47.903386, -121.437115 |
| Silver Creek | 65.7 | 56.4 | 9.3 | 31.6 | 3.0% | 84 m | 47.903908, -121.437142 |
| Sultan River (upper) | 58.6 | 45.2 | 13.4 | 7.1 | 4.3% | 60 m | 47.968961, -121.490328 |
| Williamson Creek | 56.9 | 37.5 | 19.3 | 5.7 | 29.9% | 36 m | 48.042235, -121.548816 |
| Barclay Creek | 45.8 | 25.1 | 20.7 | 21.9 | 9.9% | 64 m | 47.789480, -121.495144 |

Note the pattern: Silver Creek wins on **source** (lode 1 km up), Barclay and
Williamson win on **traps** (steep, confined, big gradient breaks) but have
little known source. Neither alone is the answer - which is the point of
keeping the components separate and visible.
