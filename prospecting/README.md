# Sultan–Gold Bar–Index Gold Prospectivity System (V0.1)

A GIS pipeline that scores stream segments in the Sultan → Gold Bar → Index corridor (plus the Sultan Basin source area, with Monte Cristo/Silverton as historical reference) for **relative gold prospectivity**, kept strictly separate from a **legal access** layer. The score is a rank, not a probability — calibration waits for field samples.

## Documents

| Doc | Contents |
|---|---|
| [docs/01_data_inventory.md](docs/01_data_inventory.md) | Every dataset: verified URLs, fields, limitations |
| [docs/02_architecture.md](docs/02_architecture.md) | GIS stack decision + full data model (incl. `field_samples`) |
| [docs/03_scoring_v01.md](docs/03_scoring_v01.md) | The explainable scoring algorithm + its known weaknesses |
| [docs/04_validation.md](docs/04_validation.md) | Holdout experiment to test whether the model predicts anything |
| [docs/05_map_and_roadmap.md](docs/05_map_and_roadmap.md) | QGIS + web map outputs; Phases 2–5 evolution plan |
| [config/weights.yaml](config/weights.yaml) | Every scoring weight, editable |

## Status: V0.1 is BUILT and validated (2026-08-18)

```
cd prospecting && uv venv .venv && uv pip install --python .venv/bin/python \
  geopandas pyogrio shapely pyproj pyyaml folium pyarrow pandas scipy
.venv/bin/python pipeline/01_download.py        # S3 downloads + verifies cached extracts
.venv/bin/python pipeline/02_clean_occurrences.py
.venv/bin/python pipeline/03_build_network.py
.venv/bin/python pipeline/04b_overlays.py       # geology/claims/access per segment
.venv/bin/python pipeline/04_link_sources.py
.venv/bin/python pipeline/05_score.py --run-label v01
.venv/bin/python pipeline/06_validate.py
.venv/bin/python pipeline/07_map.py             # -> map/index.html (self-contained)
```

**What the first run found** (raw extracts cached in `data/raw/`, committed):
- 1,017 raw records (WGS + MRDS) → 747 gold → **340 deduplicated sites** (dedup removed 55% — the duplication problem is real), 27 placer sites, 70 past producers, 194 sites confirmed by ≥2 databases.
- 13,893 stream segments (NHDPlus HR, HUC8 17110009); Culmback Dam snapped onto the Sultan mainstem at 178 km² drainage with 26.4 km of sediment-starved river below it.
- Top-scoring drainages: NF Skykomish, Silver Creek, Troublesome Creek, Williamson Creek (45 Mine), Sultan River — matching the district literature without being told about districts.
- **Validation (10 seeds, ~3 placer clusters held out each):** river-scale AUC **0.82** (0.74–0.90) — the model reliably identifies gold-bearing drainages; stream-order-matched AUC **0.60** vs naive-baseline 0.51 — within-river reach discrimination is weak, which is exactly the gap the Phase-2 terrain-trap score exists to fill; 60% of held-out placer clusters land in the model's top 10% of segments.
- WGS "Historical Mining Districts" polygons tile the entire corridor (administrative divisions, not mineralized zones) — district weight zeroed, kept as a map layer only.

Open `map/index.html` in any browser (fully self-contained; JS/CSS inlined —
works offline except basemap tiles). Click any stream for its score breakdown,
nearest upstream source, claim conflict, and access status.

## The critical caveats (read before believing the map)

1. **Historical data measures where people prospected, not where gold is.** All three occurrence databases inherit 1890s road-and-rail accessibility bias; validation is designed to partially control for it, field samples are the only cure.
2. **Positional accuracy is bad enough to change conclusions.** MRDS errors reach >1 km; a mislocated record snaps to the wrong fork and poisons a whole drainage. The pipeline weights by snap distance and source trust (USMIN > WGS > MRDS), but single-record scores are rumors.
3. **The same mine appears up to 4+ times across sources.** Without dedup, "multiple independent records" — a confidence input — is fiction.
4. **Glacial gold breaks the source→downstream model.** Much lower-valley placer gold was distributed by ice and outwash, not the modern network. V0.1 knowingly under-scores glacially fed bars; the geology factor (nonzero rating for outwash units) only partially compensates.
5. **The lower Sultan River is sediment-starved.** Culmback Dam (1965/1984) traps upper-basin bedload; lower-Sultan placers are a relict resource. Encoded as `dam_pass_factor`, but the local lore of "the Sultan replenishes every winter" is only true for tributary-fed and Skykomish reaches.
6. **Claims data is section-level.** MLRS polygons mean "a claim exists in this ~640-acre section," never a boundary. Claim conflict flags are a trigger for serial-number research, not a map of claimed ground. And claim *absence* in the Wilderness areas is regulatory (withdrawn from entry), not geological.
7. **Legal ≠ geological, and both change.** State parks (incl. Wallace Falls) and DNR trust land are closed to panning; Wilderness flagged restricted; the WDFW Gold and Fish pamphlet (May 2021 edition, still current) sets short in-water work windows — **Skykomish mainstem/SF: Aug 1–15 only**. Every access rule row carries its source and date.
8. **Scores max at 70/100 in V0.1** — 30 points are reserved for the Phase 2 terrain-trap score so runs stay comparable across versions. Never rescale to hide what isn't built yet.

## Non-goals for V0.1

No machine learning, no LiDAR terrain analysis, no coarse/fine gold split, no flood-reworking score, no statewide coverage. Each has a designed slot (doc 05) and a prerequisite: a validated V0.1 and a growing `field_samples` table — failures included.
