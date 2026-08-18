# V0.1 Scoring Model

## Design constraints

1. **Explainable**: every segment's score must decompose into named components a person can argue with.
2. **Editable**: all weights in `config/weights.yaml`; changing a weight and rerunning takes minutes.
3. **Honest**: the output is a *relative prospectivity rank*, not a probability. The map legend and popups must say "prospectivity score", never "probability of gold".

## What the score is built from (and what it is not)

V0.1 uses only: known mineralization → drainage relationship → downstream distance → geology → historical placer evidence, plus two cheap transport attributes NHDPlus already provides (slope, drainage area). No LiDAR, no terrain traps, no flood modeling. Those are Phase 2+ (docs/05).

## Pipeline logic

### Step 1 — Source strength per occurrence

Each gold occurrence gets a base strength from the strongest evidence gradient in the data — development status and deposit class:

| Evidence | `base_strength` (editable) |
|---|---|
| Placer past-producer / documented placer production | 1.00 |
| Placer occurrence or prospect | 0.65 |
| Lode past-producer, gold primary | 0.80 |
| Lode mine/prospect, gold primary | 0.50 |
| Any occurrence, gold secondary commodity | 0.25 |

Multiplied by a **position-confidence factor**: `conf = clamp(1 - snap_dist_m / 1500, 0.3, 1.0)`. A record that had to be dragged 1 km to reach a stream is worth much less than one sitting on the bank — this directly counters the known positional sloppiness of MRDS-era records.

Lode sources deliberately score high even though you can't pan a lode: a lode mine upstream is exactly the "gold source" the transport model exists to propagate downstream. Placer records are *evidence gold already concentrated there*; lode records are *evidence gold enters the system there*. Both matter, differently — which is why they carry separate strengths instead of being merged.

### Step 2 — Downstream propagation with distance decay

For each occurrence, walk downstream through the NHDPlus navigation (`hydroseq → dnhydroseq`) accumulating influence on every segment passed:

```
influence(segment) = base_strength × conf × exp(-d_downstream_km / λ)
```

- `λ` (decay length) default **5 km**, editable. Rationale: placer concentration from a point source is typically strongest within the first few km below the source; beyond ~15 km influence should be near zero unless many sources stack.
- Influence also propagates a short distance **upstream** (default 1 km, steep decay λ=0.5 km) because occurrence coordinates are sloppy and gold sources are often slightly upslope of the plotted point.
- **Hard stops**: propagation terminates at reservoirs/dams (Culmback Dam on the Sultan — everything below it is sediment-starved for post-1965 transport; pre-dam deposits remain, so the stop reduces rather than zeroes influence: multiply by `dam_pass_factor` default 0.4, editable, and flag the segment `below_dam=true`).
- A segment's raw source signal is the **sum over all upstream occurrences**, then squashed: `source_signal = 1 - exp(-Σ influence)`. Summation rewards multiple independent sources; the squash stops 15 duplicate records of one mine from dominating the map (dedup should catch these, but defense in depth).

### Step 3 — Component scores

**Source score (0–40)** = 40 × weighted mix of:
- `0.60` × source_signal (from step 2)
- `0.25` × geology factor: fraction of the segment's local catchment on `gold_assoc ≥ 2` units (from the manually assigned `geology_gold_assoc.csv`)
- `0.15` × district factor: 1 if segment drains a documented historical gold district, else 0

**Transport score (0–20)** = 20 × weighted mix of:
- `0.40` × gradient suitability: triangular function peaking at slope 0.5–2% (deposition-favorable), falling to 0 above ~8% (transport-only chutes) and near 0 below 0.1% (fines only). *Known simplification: coarse gold drops at gradient breaks, which need the DEM — Phase 2.*
- `0.30` × drainage-area suitability: inverted-U over log(drainage area) peaking ~50–500 km² for the mainstem-bar case, with a second usable band 5–50 km² for small creeks. Editable band edges.
- `0.30` × junction bonus: segment is within 500 m downstream of a confluence where the *tributary* carries source_signal above threshold — classic concentration point.

**Confidence score (0–10)**, deliberately *not* mixed into prospectivity:
- number of independent (post-dedup) gold records contributing
- source agreement (record appears in ≥2 of MRDS / USMIN / WA DNR)
- positional quality of contributing records
- geologic mapping scale available at the segment (1:24k > 1:100k)
- LiDAR available flag (for Phase 2 readiness)

**Total (0–100)** = source (0–40) + transport (0–20) + confidence (0–10) + **30 points reserved** for the Phase 2 trap score. In V0.1 the reserved block is empty, so V0.1 totals max at 70 — display as `xx/70 (V0.1)` rather than silently rescaling, so scores remain comparable across versions.

### Step 4 — Legal overlay (never subtracted)

Each segment gets flags, not score changes: `claim_conflict` (intersects active MLRS claim section), `access_status` (from ownership + access_rules: `likely_open` / `permission_needed` / `restricted` / `closed` / `unknown`). The map symbolizes these as hatching/outline on top of the score color. Geologic truth and legal availability stay orthogonal, as specified.

## `weights.yaml` sketch

```yaml
decay:
  lambda_downstream_km: 5.0
  lambda_upstream_km: 0.5
  upstream_max_km: 1.0
  dam_pass_factor: 0.4
source_strength:
  placer_producer: 1.0
  placer_occurrence: 0.65
  lode_producer_au_primary: 0.8
  lode_mine_au_primary: 0.5
  au_secondary: 0.25
snap:
  max_snap_m: 1500
  conf_floor: 0.3
components:
  source: {max: 40, w_signal: 0.6, w_geology: 0.25, w_district: 0.15}
  transport:
    max: 20
    w_gradient: 0.4
    w_drainage: 0.3
    w_junction: 0.3
    gradient_peak_pct: [0.5, 2.0]
    gradient_zero_pct: 8.0
  confidence: {max: 10}
```

## Known weaknesses (read before trusting the map)

1. **Glacial gold breaks the source→downstream logic.** The lower Skykomish valley is full of glacial outwash and recessional deposits; some placer gold there was transported by ice and meltwater from sources the modern drainage never touches. The model will under-score glacially fed bars and over-credit modern upstream lode sources. V0.1 accepts this; the geology factor partially compensates if outwash units get a nonzero `gold_assoc`.
2. **Exploration bias.** Occurrence databases record where prospectors went (near roads, rail, towns), not where gold is. The model partly rediscovers 1890s accessibility. Validation (docs/04) must compare against *stream-order-matched* background, and even that only mitigates.
3. **Duplicates masquerading as independent evidence.** MRDS, USMIN, and WA DNR describe many of the same historical sites. Without aggressive dedup (cluster by name similarity + distance ≤ 1 km), "multiple independent records" confidence is fiction.
4. **Position error vs. tributary assignment.** A record 800 m off can snap to the wrong fork of a creek, sending all its influence down the wrong drainage. The snap-confidence factor shrinks the damage but cannot fix the topology. Segments whose entire score hangs on one far-snapped record should be treated as rumors.
5. **Slope/drainage-area sweet spots are hand-tuned guesses** until field samples exist. They encode conventional placer wisdom, not local calibration.
6. **The score is not a probability** and V0.1 has no mechanism to become one. Calibration requires the field-sample table to fill up — including failures.
