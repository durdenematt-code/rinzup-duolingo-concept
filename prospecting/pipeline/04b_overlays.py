"""Stage 04b — static overlays per segment.

Computes, for every stream segment:
  - gold_frac: area-weighted gold-association of geology within a 300 m buffer
    (ratings from config/geology_gold_assoc.csv, scaled to [0,1])
  - in_district: intersects a historical mining-district polygon
  - claim_conflict: intersects an active MLRS claim (section-level geometry!)
  - access_status: coarse legal class from ownership layers

Also loads geology / districts / claims / ownership into the GeoPackage and
creates the (empty) field_samples layer.
"""
import sys

import geopandas as gpd
import numpy as np
import pandas as pd

from common import CONFIG, CRS, GPKG, INTERIM, RAW

BUFFER_M = 300


def load_many(*names):
    """Concat any of these extracts that exist (base + king_* strip)."""
    parts = [load_4326(n) for n in names if (RAW / n).exists()]
    if not parts:
        raise FileNotFoundError(names[0])
    out = pd.concat(parts, ignore_index=True)
    return gpd.GeoDataFrame(out, geometry="geometry", crs=parts[0].crs)


def load_4326(name):
    g = gpd.read_file(RAW / name)
    if g.crs is None:
        g = g.set_crs("EPSG:4326")
    return g.to_crs(CRS)


def main() -> int:
    seg = gpd.read_file(GPKG, layer="stream_segments")
    buf = seg[["segment_id", "geometry"]].copy()
    buf["geometry"] = buf.geometry.buffer(BUFFER_M)
    buf["buf_area"] = buf.geometry.area

    # ---- geology ---------------------------------------------------------
    geol = load_many("wgs_geology_100k.geojson", "king_wgs_geology_100k.geojson")
    assoc = pd.read_csv(CONFIG / "geology_gold_assoc.csv", comment="#")
    rating = dict(zip(assoc["unit"], assoc["rating"]))
    geol["rating"] = geol["MAP_UNIT_100K"].map(rating)
    unknown = geol.loc[geol["rating"].isna(), "MAP_UNIT_100K"].unique()
    if len(unknown):
        print(f"WARNING: {len(unknown)} unrated map units (rated 0): {list(unknown)[:10]}")
        geol["rating"] = geol["rating"].fillna(0)
    # only ratings >= 2 count toward the geology factor (docs/03); rating-1
    # background units (melange belts, till) cover too much area to discriminate
    geol = geol[geol["rating"] >= 2][["MAP_UNIT_100K", "rating", "geometry"]]

    ix = gpd.overlay(buf, geol, how="intersection", keep_geom_type=True)
    ix["w"] = ix.geometry.area * np.where(ix["rating"] >= 3, 1.0, 0.7)
    frac = ix.groupby("segment_id")["w"].sum() / buf.set_index("segment_id")["buf_area"]
    seg_geol = pd.DataFrame({"gold_frac": frac.clip(0, 1)}).reindex(
        seg["segment_id"]).fillna(0)
    seg_geol.to_parquet(INTERIM / "segment_geology.parquet")
    print(f"geology: {len(ix)} intersections; mean gold_frac "
          f"{seg_geol['gold_frac'].mean():.3f}, >0 on {(seg_geol['gold_frac']>0).sum()} segments")

    # ---- districts -------------------------------------------------------
    try:
        dist = load_many("wgs_mining_districts.geojson", "king_wgs_mining_districts.geojson")
        hit = gpd.sjoin(seg[["segment_id", "geometry"]], dist[["geometry"]],
                        how="inner", predicate="intersects")["segment_id"].unique()
        sd = pd.DataFrame({"in_district": 0.0}, index=seg["segment_id"])
        sd.loc[sd.index.isin(hit), "in_district"] = 1.0
        sd.to_parquet(INTERIM / "segment_district.parquet")
        dist.to_file(GPKG, layer="mining_districts", driver="GPKG")
        print(f"districts: {len(dist)} polygons; {len(hit)} segments inside")
    except Exception as e:  # districts file may not exist yet
        print(f"districts skipped: {e}")

    # ---- claims ----------------------------------------------------------
    claims = load_many("blm_claims_active.geojson", "king_blm_claims_active.geojson")
    claims["claim_kind"] = claims["BLM_PROD"].str.title()
    claims.to_file(GPKG, layer="claims_active", driver="GPKG")
    cc = gpd.sjoin(seg[["segment_id", "geometry"]], claims[["geometry"]],
                   how="inner", predicate="intersects")["segment_id"].unique()
    print(f"claims: {len(claims)} active; {len(cc)} segments intersect a claim section")

    # ---- ownership / access ---------------------------------------------
    ndmpl = load_many("ndmpl_ownership.geojson", "king_ndmpl_ownership.geojson")
    dnr = load_many("dnr_managed_lands.geojson", "king_dnr_managed_lands.geojson")
    ndmpl.to_file(GPKG, layer="ownership_public", driver="GPKG")
    dnr.to_file(GPKG, layer="dnr_managed_lands", driver="GPKG")

    def txt(v):
        return v.lower() if isinstance(v, str) else ""

    def classify(row):
        mt, mgr = txt(row.get("MANAGEMENT_TYPE")), txt(row.get("MANAGER"))
        if "wilderness" in mt:
            return "restricted"      # withdrawn from entry; hand-pan legality ambiguous
        if mt == "park" and "state parks" in mgr:
            return "closed"          # WA State Parks ban panning outright
        if "watershed" in mt:
            return "closed"          # municipal water-supply lands: no public entry
        if "forest service" in mgr:
            return "likely_open"     # non-designated NF: casual use, pamphlet rules apply
        if "land management" in mgr:
            return "likely_open"     # BLM public domain: casual use
        return "permission_needed"   # WDFW, county/city parks, schools, misc.
    ndmpl["access"] = ndmpl.apply(classify, axis=1)

    order = {"closed": 3, "restricted": 2, "permission_needed": 1, "likely_open": 0}
    j = gpd.sjoin(seg[["segment_id", "geometry"]],
                  ndmpl[["access", "geometry"]], how="left", predicate="intersects")
    j["rank"] = j["access"].map(order)
    worst = j.sort_values("rank").groupby("segment_id")["access"].last()

    # DNR-managed trust land: closed to panning absent a placer contract
    dnr_hit = gpd.sjoin(seg[["segment_id", "geometry"]], dnr[["geometry"]],
                        how="inner", predicate="intersects")["segment_id"].unique()

    acc = pd.DataFrame(index=seg["segment_id"])
    acc["access_status"] = worst.reindex(acc.index)
    acc.loc[acc.index.isin(dnr_hit) & acc["access_status"].isin([None, np.nan, "likely_open"]),
            "access_status"] = "dnr_closed_no_contract"
    acc["access_status"] = acc["access_status"].fillna("unknown_check_parcel")
    acc["claim_conflict"] = acc.index.isin(cc)
    # ---- overlay COVERAGE flag ------------------------------------------
    # A segment outside the geology/ownership extract footprints scores 0 on
    # the geology factor and 'unknown' on access for lack of DATA, not because
    # the ground is barren or private. Flag it so scores are never compared
    # across the coverage boundary without knowing.
    geol_hull = geol.geometry.union_all().convex_hull
    own_hull = ndmpl.geometry.union_all().convex_hull
    acc["has_geology"] = seg.set_index("segment_id").geometry.intersects(geol_hull).reindex(acc.index).fillna(False)
    acc["has_ownership"] = seg.set_index("segment_id").geometry.intersects(own_hull).reindex(acc.index).fillna(False)
    acc["overlays_complete"] = acc["has_geology"] & acc["has_ownership"]
    print(f"overlay coverage: geology {int(acc.has_geology.sum())}/{len(acc)}, "
          f"ownership {int(acc.has_ownership.sum())}/{len(acc)}, "
          f"both {int(acc.overlays_complete.sum())}/{len(acc)}")

    acc.to_parquet(INTERIM / "segment_access.parquet")
    print("access:", acc["access_status"].value_counts().to_dict())
    print(f"claim_conflict on {acc['claim_conflict'].sum()} segments")
    return 0


if __name__ == "__main__":
    sys.exit(main())
