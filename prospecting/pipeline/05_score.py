"""Stage 05 — compute component scores per segment and write a versioned run.

Usage: 05_score.py [--run-label LABEL] [--exclude-occs FILE]
  --exclude-occs: newline-separated occ_ids to hide (used by validation)
"""
import argparse
import datetime
import sqlite3
import sys

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

from common import GPKG, INTERIM, load_weights


def tri_band(x, lo, peak_lo, peak_hi, hi):
    """Trapezoid membership: 0 at/below lo, 1 across [peak_lo, peak_hi], 0 at/above hi."""
    x = np.asarray(x, dtype=float)
    up = np.clip((x - lo) / max(peak_lo - lo, 1e-9), 0, 1)
    down = np.clip((hi - x) / max(hi - peak_hi, 1e-9), 0, 1)
    return np.where(np.isnan(x), 0.0, np.minimum(up, down))


def compute_scores(W, seg, occ, infl, geol_frac=None, district_seg=None):
    """Pure scoring from inputs -> DataFrame indexed by segment_id."""
    comp = W["components"]

    # ---- source ----------------------------------------------------------
    agg = infl.groupby("segment_id")["influence"].sum()
    source_signal = 1 - np.exp(-agg)  # squash stacked influence to [0,1)
    src = pd.DataFrame(index=seg["segment_id"])
    src["signal"] = source_signal.reindex(src.index).fillna(0)
    src["geology"] = (geol_frac.reindex(src.index).fillna(0) if geol_frac is not None else 0.0)
    src["district"] = (district_seg.reindex(src.index).fillna(0) if district_seg is not None else 0.0)
    c = comp["source"]
    src_score = c["max"] * (
        c["w_signal"] * src["signal"] + c["w_geology"] * src["geology"] + c["w_district"] * src["district"]
    )

    # ---- transport -------------------------------------------------------
    t = comp["transport"]
    s = seg.set_index("segment_id")
    g_lo, g_hi = t["gradient_peak_pct"]
    grad = tri_band(s["slope_pct"], t["gradient_min_pct"], g_lo, g_hi, t["gradient_zero_pct"])

    da = s["TotDASqKm"].astype(float)
    p_lo, p_hi = t["drainage_primary_km2"]
    s_lo, s_hi = t["drainage_secondary_km2"]
    da_primary = tri_band(np.log10(da.clip(lower=0.01)), np.log10(p_lo / 5), np.log10(p_lo), np.log10(p_hi), np.log10(p_hi * 5))
    da_secondary = tri_band(np.log10(da.clip(lower=0.01)), np.log10(s_lo / 5), np.log10(s_lo), np.log10(s_hi), np.log10(s_hi * 5))
    drain = np.maximum(da_primary, 0.8 * da_secondary)

    # junction bonus: segment starts at a confluence AND has upstream signal
    junction = (s["is_junction"] & (src["signal"] > 0.05)).astype(float)

    tr_score = t["max"] * (t["w_gradient"] * grad + t["w_drainage"] * drain + t["w_junction"] * junction)
    tr_score = pd.Series(np.asarray(tr_score), index=s.index)

    # ---- confidence ------------------------------------------------------
    # n independent contributing records (post-dedup occurrences)
    n_up = infl[infl["influence"] > 0.02].groupby("segment_id")["occ_id"].nunique().reindex(s.index).fillna(0)
    multi_src = (
        occ.set_index("occ_id")["n_sources"].reindex(infl["occ_id"]).values
        if "n_sources" in occ.columns else None
    )
    if multi_src is not None:
        infl2 = infl.assign(multi=(multi_src >= 2).astype(float) * infl["influence"])
        agree = (infl2.groupby("segment_id")["multi"].max() > 0.05).reindex(s.index).fillna(False)
    else:
        agree = pd.Series(False, index=s.index)
    conf_max = comp["confidence"]["max"]
    conf_score = conf_max * (
        0.5 * np.clip(n_up / 3, 0, 1) + 0.3 * agree.astype(float) + 0.2 * 1.0  # 0.2 = mapping-scale baseline (100k everywhere)
    )

    out = pd.DataFrame({
        "segment_id": s.index,
        "source_score": np.round(src_score.values, 2),
        "transport_score": np.round(tr_score.values, 2),
        "confidence_score": np.round(conf_score.values, 2),
        "n_upstream_gold": n_up.astype(int).values,
    })
    out["total_score"] = (out["source_score"] + out["transport_score"] + out["confidence_score"]).round(2)

    # top contributing occurrence per segment (positive-distance = upstream source)
    down = infl[infl["dist_km"] >= 0]
    if len(down):
        top = down.loc[down.groupby("segment_id")["influence"].idxmax()]
        out = out.merge(
            top[["segment_id", "occ_id", "dist_km"]].rename(
                columns={"occ_id": "top_occ_id", "dist_km": "top_occ_dist_km"}),
            on="segment_id", how="left")
    else:
        out["top_occ_id"] = np.nan
        out["top_occ_dist_km"] = np.nan
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-label", default="default")
    ap.add_argument("--exclude-occs", default=None)
    ap.add_argument("--no-write", action="store_true", help="print summary only")
    ap.add_argument("--weights", default=None,
                    help="alternate weight profile (e.g. config/weights_coarse.yaml)")
    ap.add_argument("--influence", default="influence.parquet",
                    help="influence table under data/interim/ (must match the profile)")
    args = ap.parse_args()

    W = load_weights(args.weights)
    seg = gpd.read_file(GPKG, layer="stream_segments")
    occ = gpd.read_file(GPKG, layer="occurrences")
    infl = pd.read_parquet(INTERIM / args.influence)

    if args.exclude_occs:
        hide = set(int(x) for x in open(args.exclude_occs).read().split())
        infl = infl[~infl["occ_id"].isin(hide)]
        print(f"validation mode: {len(hide)} occurrences hidden")

    geol_frac = None
    district_seg = None
    try:
        geol_frac = pd.read_parquet(INTERIM / "segment_geology.parquet")["gold_frac"]
    except FileNotFoundError:
        print("NOTE: segment_geology.parquet missing — geology factor = 0")
    try:
        district_seg = pd.read_parquet(INTERIM / "segment_district.parquet")["in_district"]
    except FileNotFoundError:
        print("NOTE: segment_district.parquet missing — district factor = 0")

    scores = compute_scores(W, seg, occ, infl, geol_frac, district_seg)

    ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    run_id = f"{args.run_label}_{ts.replace(':', '').replace('-', '')[:15]}"
    scores.insert(0, "run_id", run_id)

    print(scores["total_score"].describe().round(2).to_string())
    print("top 10 segments:")
    top = scores.nlargest(10, "total_score").merge(
        seg[["segment_id", "GNIS_Name", "StreamOrde"]], on="segment_id")
    print(top[["segment_id", "GNIS_Name", "StreamOrde", "total_score",
               "source_score", "transport_score", "confidence_score"]].to_string(index=False))

    if not args.no_write:
        with sqlite3.connect(GPKG) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS score_runs
                          (run_id TEXT PRIMARY KEY, ts TEXT, label TEXT, weights_yaml TEXT)""")
            db.execute("INSERT OR REPLACE INTO score_runs VALUES (?,?,?,?)",
                       (run_id, ts, args.run_label, yaml.safe_dump(W)))
            scores.to_sql("scores", db, if_exists="append", index=False)
        print(f"run {run_id} -> {GPKG}:scores")
    return 0


if __name__ == "__main__":
    sys.exit(main())
