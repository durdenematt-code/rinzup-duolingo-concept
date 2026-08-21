"""Stage 06 — holdout validation (docs/04_validation.md).

Hides ~30% of placer clusters, rescores, and asks whether segments at the
held-out placers outrank stream-order-matched background segments.
Also runs the mandatory naive baseline (distance to nearest visible gold
record). Repeats over N seeds and reports ranges.
"""
import sys
import importlib

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

from common import CRS, GPKG, INTERIM, load_weights

score_mod = importlib.import_module("05_score", package=None) if False else None
# import compute_scores without executing the CLI
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("score05", __file__.replace("06_validate.py", "05_score.py"))
score05 = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(score05)


def cluster_placers(gold: gpd.GeoDataFrame, eps_km: float) -> pd.Series:
    """Greedy spatial clustering (single-link, eps in km) — no sklearn dep."""
    pts = np.array([(g.x, g.y) for g in gold.geometry])
    n = len(pts)
    cluster = -np.ones(n, dtype=int)
    cid = 0
    for i in range(n):
        if cluster[i] >= 0:
            continue
        stack = [i]
        cluster[i] = cid
        while stack:
            j = stack.pop()
            d = np.hypot(*(pts - pts[j]).T) / 1000.0
            for k in np.where((d <= eps_km) & (cluster < 0))[0]:
                cluster[k] = cid
                stack.append(k)
        cid += 1
    return pd.Series(cluster, index=gold.index)


def auc_from_u(u, n1, n2):
    return u / (n1 * n2)


def main() -> int:
    W = load_weights()
    V = W["validation"]
    seg = gpd.read_file(GPKG, layer="stream_segments")
    occ = gpd.read_file(GPKG, layer="occurrences").to_crs(CRS)
    infl_all = pd.read_parquet(INTERIM / "influence.parquet")

    geol_frac = district_seg = None
    try:
        geol_frac = pd.read_parquet(INTERIM / "segment_geology.parquet")["gold_frac"]
        district_seg = pd.read_parquet(INTERIM / "segment_district.parquet")["in_district"]
    except FileNotFoundError:
        pass

    placers = occ[occ["is_gold"] & (occ["deposit_class"] == "placer")
                  & occ["snapped_segment_id"].notna()].copy()
    if len(placers) < 6:
        print(f"only {len(placers)} snapped placer occurrences — validation underpowered; aborting")
        return 1
    placers["cluster"] = cluster_placers(placers, V["holdout_cluster_eps_km"])
    clusters = placers["cluster"].unique()
    print(f"{len(placers)} snapped placer occurrences in {len(clusters)} spatial clusters")

    seg_i = seg.set_index("segment_id")
    results = []
    for seed in range(V["n_seeds"]):
        rng = np.random.default_rng(seed)
        n_hold = max(1, round(len(clusters) * V["holdout_cluster_frac"]))
        held = set(rng.choice(clusters, size=n_hold, replace=False))
        hidden_ids = set(placers.loc[placers["cluster"].isin(held), "occ_id"])
        infl = infl_all[~infl_all["occ_id"].isin(hidden_ids)]

        scores = score05.compute_scores(W, seg, occ, infl, geol_frac, district_seg)
        scores = scores.set_index("segment_id")

        # hit score per held placer point: MAX score among segments within the
        # buffer — tolerates wrong-fork snapping from position error
        buffer_m = V["hit_buffer_m"]
        held_pts = placers[placers["cluster"].isin(held)]
        seg_sindex = seg_i.sindex

        def buffered_max(pt_geom):
            idx = seg_sindex.query(pt_geom.buffer(buffer_m), predicate="intersects")
            ids = seg_i.iloc[idx].index
            return (scores.loc[scores.index.intersection(ids), "total_score"].max()
                    if len(ids) else np.nan)

        hit_scores = held_pts.geometry.apply(buffered_max).dropna()
        hit_segs = list(held_pts["snapped_segment_id"].astype(int).unique())

        # background: random matched-order segments, scored the same buffered-max way
        hit_orders = seg_i.loc[seg_i.index.intersection(hit_segs), "StreamOrde"]
        bg_scores = []
        for order, cnt in hit_orders.value_counts().items():
            pool = seg_i[(seg_i["StreamOrde"] == order) & (~seg_i.index.isin(hit_segs))]
            take = rng.choice(pool.index, size=min(len(pool), cnt * 20), replace=False)
            pts = pool.loc[take].geometry.interpolate(0.5, normalized=True)
            bg_scores.append(pts.apply(buffered_max).dropna())
        bg_scores = pd.concat(bg_scores)

        u, p = mannwhitneyu(hit_scores, bg_scores, alternative="greater")
        auc = auc_from_u(u, len(hit_scores), len(bg_scores))

        # river-scale skill: same comparison without order matching
        pool_any = seg_i[~seg_i.index.isin(hit_segs)]
        take_any = rng.choice(pool_any.index, size=min(len(pool_any), len(hit_scores) * 40), replace=False)
        pts_any = pool_any.loc[take_any].geometry.interpolate(0.5, normalized=True)
        bg_any = pts_any.apply(buffered_max).dropna()
        u2, _ = mannwhitneyu(hit_scores, bg_any, alternative="greater")
        auc_unmatched = auc_from_u(u2, len(hit_scores), len(bg_any))

        # naive baseline: nearest visible gold occurrence distance (smaller = better)
        visible = occ[occ["is_gold"] & ~occ["occ_id"].isin(hidden_ids)]
        vis_union = visible.geometry.union_all()
        d_hit = held_pts.geometry.distance(vis_union)
        # background points: matched-order segment midpoints
        bg_pts = []
        for order, cnt in hit_orders.value_counts().items():
            pool = seg_i[(seg_i["StreamOrde"] == order) & (~seg_i.index.isin(hit_segs))]
            take = rng.choice(pool.index, size=min(len(pool), cnt * 20), replace=False)
            bg_pts.append(pool.loc[take].geometry.interpolate(0.5, normalized=True))
        bg_pts = pd.concat(bg_pts)
        d_bgv = bg_pts.distance(vis_union)
        u_n, _ = mannwhitneyu(-d_hit, -d_bgv, alternative="greater")
        auc_naive = auc_from_u(u_n, len(d_hit), len(d_bgv))

        # capture: fraction of held clusters whose best segment is in top 10% by score
        thresh = scores["total_score"].quantile(0.90)
        captured = 0
        for cl in held:
            cl_segs = placers.loc[placers["cluster"] == cl, "snapped_segment_id"].astype(int)
            best = scores.loc[scores.index.intersection(cl_segs), "total_score"].max()
            captured += int(best >= thresh)
        results.append({"seed": seed, "n_held_clusters": len(held), "n_hit_pts": len(hit_scores),
                        "auc_matched": auc, "p": p, "auc_unmatched": auc_unmatched,
                        "auc_naive": auc_naive, "capture_top10pct": captured / len(held)})
        print(f"seed {seed}: {len(held)} clusters held, matched AUC={auc:.3f} (p={p:.3g}), "
              f"river-scale AUC={auc_unmatched:.3f}, naive AUC={auc_naive:.3f}, "
              f"top-10% capture={captured}/{len(held)}")

    df = pd.DataFrame(results)
    df.to_csv(INTERIM / "validation_results.csv", index=False)
    print("\nSummary over seeds:")
    print(df[["auc_matched", "auc_unmatched", "auc_naive", "capture_top10pct"]]
          .describe().loc[["mean", "min", "max"]].round(3).to_string())
    delta = (df["auc_matched"] - df["auc_naive"]).mean()
    print(f"\nmodel AUC - naive AUC (mean): {delta:+.3f}")
    if delta <= 0:
        print("WARNING: the model does not beat the naive nearest-record baseline — "
              "simplify before adding features (see docs/04).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
