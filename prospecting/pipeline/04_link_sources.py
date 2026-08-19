"""Stage 04 — snap fused occurrences to the network and propagate influence.

Inputs: `occurrences` layer (stage 02) + `stream_segments` (stage 03).
Outputs: occurrences updated with snap info; `influence` interim table with
one row per (segment, occurrence) pair carrying decayed source influence.
"""
import sys

import argparse

import geopandas as gpd
import numpy as np
import pandas as pd

from common import CRS, GPKG, INTERIM, load_weights


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default=None,
                    help="alternate weight profile (e.g. config/weights_coarse.yaml)")
    ap.add_argument("--out", default="influence.parquet",
                    help="output filename under data/interim/")
    args = ap.parse_args()
    W = load_weights(args.weights)
    dec = W["decay"]
    snap_cfg = W["snap"]

    occ = gpd.read_file(GPKG, layer="occurrences").to_crs(CRS)
    seg = gpd.read_file(GPKG, layer="stream_segments").to_crs(CRS)

    # ---- snap gold occurrences to nearest segment -------------------------
    gold = occ[occ["is_gold"]].copy()
    seg_geo = seg[["segment_id", "geometry"]].reset_index(drop=True)
    joined = gpd.sjoin_nearest(
        gold, seg_geo, how="left",
        max_distance=snap_cfg["max_snap_m"], distance_col="snap_dist_m",
    )
    # sjoin_nearest can duplicate on ties; keep first
    joined = joined[~joined.index.duplicated(keep="first")]
    occ["snapped_segment_id"] = joined["segment_id"]
    occ["snap_dist_m"] = joined["snap_dist_m"]
    n_gold = int(occ["is_gold"].sum())
    n_snap = int(occ["snapped_segment_id"].notna().sum())
    print(f"{n_gold} gold occurrences; {n_snap} snapped within {snap_cfg['max_snap_m']} m "
          f"({n_gold - n_snap} unsnapped — reference-only, e.g. Monte Cristo/Silverton)")

    # position-confidence factor from snap distance
    occ["snap_conf"] = np.clip(
        1 - occ["snap_dist_m"] / snap_cfg["max_snap_m"], snap_cfg["conf_floor"], 1.0
    )

    # ---- navigation lookups ----------------------------------------------
    dn_of = dict(zip(seg["HydroSeq"], seg["DnHydroSeq"]))
    len_of = dict(zip(seg["HydroSeq"], seg["length_km"]))
    dam_segments = set(seg.loc[seg["is_dam_segment"], "HydroSeq"])
    segid_of = dict(zip(seg["HydroSeq"], seg["segment_id"]))
    # upstream adjacency for the short upstream bleed
    ups_of: dict = {}
    for h, d in dn_of.items():
        ups_of.setdefault(d, []).append(h)

    lam = dec["lambda_downstream_km"]
    lam_up = dec["lambda_upstream_km"]
    up_max = dec["upstream_max_km"]
    dam_factor = dec["dam_pass_factor"]
    # stop the walk once influence is negligible
    max_walk_km = lam * 8

    seg_by_id = seg.set_index("segment_id", drop=False)
    rows = []
    snapped = occ[occ["snapped_segment_id"].notna() & occ["is_gold"]]
    for _, o in snapped.iterrows():
        strength = o["base_strength"] * o["snap_conf"]
        if strength <= 0:
            continue
        seg0 = seg_by_id.loc[int(o["snapped_segment_id"])]
        # downstream walk (influence at segment midpoint distance)
        h, d_km, dammed = seg0["HydroSeq"], 0.0, False
        visited = set()
        while h in dn_of and h not in visited and d_km < max_walk_km:
            visited.add(h)
            mid_d = d_km + len_of.get(h, 0) / 2
            infl = strength * np.exp(-mid_d / lam) * (dam_factor if dammed else 1.0)
            rows.append((segid_of[h], o["occ_id"], mid_d, infl))
            d_km += len_of.get(h, 0)
            # attenuation applies only to influence whose path crosses a dam
            if h in dam_segments:
                dammed = True
            h = dn_of[h]
        # short upstream bleed (position-error tolerance)
        frontier = [(u, len_of.get(u, 0) / 2) for u in ups_of.get(seg0["HydroSeq"], [])]
        while frontier:
            u, d_up = frontier.pop()
            if d_up > up_max:
                continue
            infl = strength * np.exp(-d_up / lam_up)
            rows.append((segid_of[u], o["occ_id"], -d_up, infl))
            frontier.extend(
                (u2, d_up + len_of.get(u2, 0)) for u2 in ups_of.get(u, [])
            )

    infl = pd.DataFrame(rows, columns=["segment_id", "occ_id", "dist_km", "influence"])
    infl.to_parquet(INTERIM / args.out)
    print(f"{len(infl)} (segment, occurrence) influence pairs "
          f"on {infl['segment_id'].nunique()} segments")

    occ.to_file(GPKG, layer="occurrences", driver="GPKG")
    return 0


if __name__ == "__main__":
    sys.exit(main())
