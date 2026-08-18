# V0.1 Validation: Does the model actually predict anything?

## The question

If we hide some known placer occurrences from the model, do the segments where they sit score higher than typical segments? If not, the map is decoration.

## Holdout design

**Spatially blocked holdout, not random.** Random holdout leaks: hiding one record of the Sultan River placers while leaving three neighboring records of the same deposit in the training set lets the model "rediscover" what it was effectively told. Instead:

1. Take all *placer* gold occurrences in the study area (placers only — they are the ground truth for "pannable gold was here"; lode records stay in the model as sources).
2. Cluster them spatially (DBSCAN, ~2 km eps). Each cluster = one deposit-scale unit.
3. Randomly assign **~30% of clusters** (not points) to the holdout set. Every record in a held-out cluster is removed from scoring input.
4. **Also freeze the geology table**: the `gold_assoc` classes in `config/geology_gold_assoc.csv` must be justified from literature (district reports, bulletins), *not* from the spatial pattern of the holdout points. This is the subtle leak: if you rated a formation 3/3 "because placers sit on it," the holdout is contaminated. Document the literature source for each nonzero rating.
5. Re-run the full pipeline → `score_run` with `holdout_seed` recorded.
6. Repeat for ~10 random seeds so results aren't one lucky draw.

## Comparison groups

For each run compare three segment populations:

| Group | Definition |
|---|---|
| **Hit segments** | segments within 300 m of a held-out placer cluster centroid (buffered snap, since holdout points have position error too) |
| **Background** | random segments **matched on Strahler order** to the hit segments (this is essential — placers cluster on order 4–6 rivers, and an unmatched background would let the model "win" just by liking big rivers) |
| **Top-decile** | the segments the model ranks in its top 10% |

## Metrics

1. **Rank test**: Mann–Whitney U between hit-segment scores and matched-background scores. Report the AUC equivalent (probability a random hit segment outscores a random background segment). AUC ≈ 0.5 → no signal; ≥ 0.75 → genuinely useful for a heuristic model.
2. **Capture curve** (the standard mineral-prospectivity diagnostic): sort all segments by score descending; plot cumulative % of held-out placer clusters captured vs. cumulative % of stream length. Report e.g. "top 10% of stream km captures 62% of held-out placers." Compare against the diagonal (random) and against a naive baseline (see below).
3. **Naive baseline — mandatory**: score segments by *distance to nearest non-held-out gold record*, nothing else. If the full model doesn't beat this one-liner, the transport/geology machinery is adding complexity without information, and V0.1 should be simplified rather than extended.

## Interpretation cautions

- **n is small.** The corridor may hold only ~10–25 distinct placer clusters. With 30% held out that's 3–8 test units per seed — hence the 10-seed repetition and reporting ranges, not single numbers. Do not read "capture = 71.4%" as precision; it's 5 of 7.
- **Shared exploration bias.** Held-out placers were found by the same road-and-rail-biased prospectors who found the training records. Passing this validation shows the model reproduces the *historical record*, which is necessary but not sufficient for predicting *unworked* gold. The only cure is your own field samples, especially from low-scoring and never-prospected segments.
- **Failing validation is a useful result.** If AUC ≈ 0.5, the likely culprits in order: bad occurrence dedup, wrong-fork snapping, decay length far off, or the corridor's gold being dominated by glacial redistribution (which the model ignores by design). Diagnose before adding features.

## Field-sample validation (the real one, ongoing)

Once `field_samples` accumulates: for every sampling trip, record pans at *both* high-scoring and low-scoring sites (pre-commit to the low-score sites before going — otherwise sampling will drift toward pretty spots and the labels become as biased as the 1890s data). Colors-per-pan vs. segment score gives the first genuine calibration curve, and is the gate for any Phase 3 statistical/ML work.

---

## V0.1 results (2026-08-18, run v01)

20 snapped placer occurrences formed 10 spatial clusters; 3 clusters held out
per seed, 10 seeds, buffered-max hit scoring (300 m), matched on Strahler order.

| Metric | mean | range |
|---|---|---|
| River-scale AUC (unmatched background) | **0.82** | 0.74–0.90 |
| Reach-scale AUC (order-matched background) | 0.60 | 0.48–0.72 |
| Naive baseline AUC (dist. to nearest visible record) | 0.51 | 0.18–0.74 |
| Held-out clusters captured in top 10% of segments | 60% | 33–100% |

Interpretation: V0.1 has real skill at the question "which drainages carry
gold" and only modest skill at "which reach of a gold-bearing river" — the
latter is what the Phase-2 terrain-trap score is for. The model beats the
naive baseline by +0.10 matched AUC on average. n is tiny (3 clusters/seed);
treat all numbers as ranges, not points. Wrong-fork snapping was directly
observed (e.g. "Gold Bar Placer" snapped to an unnamed side channel), which
is why hit scoring uses a 300 m buffered max.
