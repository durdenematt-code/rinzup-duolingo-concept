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

        # hit segments: where the hidden placers snapped
        hit_segs = list(placers.loc[placers["cluster"].isin(held), "snapped_segment_id"].astype(int).unique())
        hit_scores = scores.loc[scores.index.intersection(hit_segs), "total_score"]

        # background: random segments matched on Strahler order
        hit_orders = seg_i.loc[hit_scores.index, "StreamOrde"]
        bg_scores = []
        for order, cnt in hit_orders.value_counts().items():
            pool = seg_i[(seg_i["StreamOrde"] == order) & (~seg_i.index.isin(hit_segs))].index
            take = rng.choice(pool, size=min(len(pool), cnt * 20), replace=False)
            bg_scores.append(scores.loc[take, "total_score"])
        bg_scores = pd.concat(bg_scores)

        u, p = mannwhitneyu(hit_scores, bg_scores, alternative="greater")
        auc = auc_from_u(u, len(hit_scores), len(bg_scores))

        # naive baseline: nearest visible gold occurrence distance (smaller = better)
        visible = occ[occ["is_gold"] & ~occ["occ_id"].isin(hidden_ids)]
        seg_pts = seg_i.geometry.representative_point()
        vis_union = visible.geometry.union_all()
        d_hit = seg_pts.loc[hit_scores.index].distance(vis_union)
        d_bg = seg_pts.loc[bg_scores.index].distance(vis_union)
        u_n, _ = mannwhitneyu(-d_hit, -d_bg, alternative="greater")
        auc_naive = auc_from_u(u_n, len(d_hit), len(d_bg))

        # capture: fraction of held clusters whose best segment is in top 10% by score
        thresh = scores["total_score"].quantile(0.90)
        captured = 0
        for cl in held:
            cl_segs = placers.loc[placers["cluster"] == cl, "snapped_segment_id"].astype(int)
            best = scores.loc[scores.index.intersection(cl_segs), "total_score"].max()
            captured += int(best >= thresh)
        results.append({"seed": seed, "n_held_clusters": len(held), "n_hit_segs": len(hit_scores),
                        "auc_model": auc, "p": p, "auc_naive": auc_naive,
                        "capture_top10pct": captured / len(held)})
        print(f"seed {seed}: {len(held)} clusters held, AUC={auc:.3f} (p={p:.3g}), "
              f"naive AUC={auc_naive:.3f}, top-10% capture={captured}/{len(held)}")

    df = pd.DataFrame(results)
    df.to_csv(INTERIM / "validation_results.csv", index=False)
    print("\nSummary over seeds:")
    print(df[["auc_model", "auc_naive", "capture_top10pct"]].describe().loc[["mean", "min", "max"]].round(3).to_string())
    delta = (df["auc_model"] - df["auc_naive"]).mean()
    print(f"\nmodel AUC - naive AUC (mean): {delta:+.3f}")
    if delta <= 0:
        print("WARNING: the model does not beat the naive nearest-record baseline — "
              "simplify before adding features (see docs/04).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
