"""Stage 02 — fuse WGS + MRDS gold records into deduplicated occurrence sites.

- Fixes the (lat, lon) axis swap in the WFS-derived MRDS/USMIN files.
- Classifies each record: gold?, placer/lode, evidence class -> base_strength.
- Clusters duplicates across sources (<=100 m always; <=250 m with similar
  names) and fuses each cluster to one site, keeping the member audit trail.
- Counts USMIN physical workings (adits/shafts/prospect pits) near each site
  as corroboration for the confidence score.

Outputs GPKG layers: occurrences, occurrence_members, occurrences_nongold,
usmin_features.
"""
import difflib
import json
import re
import sys

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from common import CRS, GPKG, RAW, load_weights, raw_all

PLACER_RE = re.compile(r"\b(placers?|bars?|bench(es)?|gravels?|dredge)\b", re.I)
USMIN_MINING = {"Adit", "Mine Shaft", "Prospect Pit", "Open Pit Mine or Quarry"}


def load_swapped(name):
    """WFS 1.1 GML came back (lat, lon); swap to (lon, lat)."""
    g = gpd.read_file(RAW / name)
    xs = g.geometry.x
    if xs.abs().max() <= 90:  # x looks like latitude -> swapped
        g["geometry"] = [Point(p.y, p.x) for p in g.geometry]
    return g.set_crs("EPSG:4326", allow_override=True)


def norm_name(s):
    s = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
    s = re.sub(r"\b(the|mine|claim|claims|group|no|nos|prospect)\b", " ", s)
    return " ".join(s.split())


def name_sim(a, b):
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def main() -> int:
    W = load_weights()
    S = W["source_strength"]

    records = []

    # ---- WGS layers 12 + 13 (identical schema; dedup on SITE_ID) ---------
    wgs_files = [f for b in ("wgs_gold_silver.geojson", "wgs_metallic.geojson")
                 for f in raw_all(b)]
    if not wgs_files:
        raise SystemExit("no WGS extracts for this region — run the fetch first")
    wgs = pd.concat([gpd.read_file(f) for f in wgs_files]
                    ).drop_duplicates(subset="SITE_ID").set_crs("EPSG:4326", allow_override=True)
    # Drop mining-district CENTROIDS: these are polygon centres masquerading as
    # point sites (LOCATION_ACCURACY "mining district centroid"). Left in, they
    # inject a phantom high-strength source in the middle of a district.
    n0 = len(wgs)
    wgs = wgs[~wgs["LOCATION_ACCURACY"].fillna("").str.contains("centroid", case=False)]
    if len(wgs) < n0:
        print(f"dropped {n0 - len(wgs)} mining-district centroid pseudo-sites")
    for _, r in wgs.iterrows():
        commodities = f"{r.get('PRIMARY_COMMODITY') or ''};{r.get('COMMODITIES') or ''}"
        is_gold = "gold" in commodities.lower()
        gold_primary = "gold" in (r.get("PRIMARY_COMMODITY") or "").lower()
        text = " ".join(str(r.get(c) or "") for c in
                        ("SITE_NAME", "ALTERNATE_NAMES", "LOCATION_DESCRIPTION", "COMMENTS"))
        placer = bool(PLACER_RE.search(text))
        produced = (r.get("PRODUCTION") or "").strip().upper().startswith("Y")
        records.append(dict(
            source="wgs", source_id=str(r["SITE_ID"]), name=r.get("SITE_NAME") or "",
            is_gold=is_gold, gold_primary=gold_primary, placer=placer,
            producer=produced, commodities=commodities.strip(";"),
            loc_acc=r.get("LOCATION_ACCURACY") or "",
            district=r.get("MINING_DISTRICT") or "", geometry=r.geometry))

    # ---- MRDS ------------------------------------------------------------
    mrds_parts = [load_swapped(f.name) for f in raw_all("mrds.geojson")]
    mrds = (pd.concat(mrds_parts).drop_duplicates(subset="dep_id")
            if mrds_parts else pd.DataFrame(columns=["dep_id", "site_name", "code_list",
                                                     "dev_stat", "geometry"]))
    for _, r in mrds.iterrows():
        codes = (r.get("code_list") or "").upper().split()
        is_gold = "AU" in codes
        gold_primary = bool(codes) and codes[0] == "AU"
        placer = bool(PLACER_RE.search(r.get("site_name") or ""))
        producer = (r.get("dev_stat") or "") in ("Producer", "Past Producer")
        records.append(dict(
            source="mrds", source_id=str(r["dep_id"]), name=r.get("site_name") or "",
            is_gold=is_gold, gold_primary=gold_primary, placer=placer,
            producer=producer, commodities=" ".join(codes),
            loc_acc="", district="", geometry=r.geometry))

    rec = gpd.GeoDataFrame(records, crs="EPSG:4326").to_crs(CRS)
    rec["nname"] = rec["name"].map(norm_name)
    print(f"{len(rec)} raw records ({(rec['source']=='wgs').sum()} wgs, "
          f"{(rec['source']=='mrds').sum()} mrds); {rec['is_gold'].sum()} gold")

    # ---- cluster gold records (union-find) -------------------------------
    gold = rec[rec["is_gold"]].reset_index(drop=True)
    xy = np.c_[gold.geometry.x, gold.geometry.y]
    parent = list(range(len(gold)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[find(i)] = find(j)

    from scipy.spatial import cKDTree
    tree = cKDTree(xy)
    for i, j in tree.query_pairs(r=250.0):
        d = np.hypot(*(xy[i] - xy[j]))
        if d <= 100 or name_sim(gold.loc[i, "nname"], gold.loc[j, "nname"]) >= 0.55:
            union(i, j)
    gold["cluster"] = [find(i) for i in range(len(gold))]
    n_clusters = gold["cluster"].nunique()
    print(f"{len(gold)} gold records -> {n_clusters} deduplicated sites")

    # ---- USMIN physical workings ----------------------------------------
    usmin_files = raw_all("usmin_points.geojson")
    if usmin_files:
        usmin = load_swapped(usmin_files[0].name).to_crs(CRS)
        usmin.to_file(GPKG, layer="usmin_features", driver="GPKG")
        workings = usmin[usmin["ftr_type"].isin(USMIN_MINING)]
    else:
        print("NOTE: no USMIN extract for this region — n_workings_300m will be 0")
        workings = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=CRS)
    wtree = cKDTree(np.c_[workings.geometry.x, workings.geometry.y]) if len(workings) else None

    # ---- fuse clusters ---------------------------------------------------
    sites = []
    for occ_id, (cl, grp) in enumerate(gold.groupby("cluster"), start=1):
        # representative: prefer WGS position (better vetted), else MRDS
        rep = grp[grp["source"] == "wgs"].iloc[0] if (grp["source"] == "wgs").any() else grp.iloc[0]
        placer = grp["placer"].any()
        producer = grp["producer"].any()
        gold_primary = grp["gold_primary"].any()
        if placer:
            strength = S["placer_producer"] if producer else S["placer_occurrence"]
            dep_class = "placer"
        elif gold_primary:
            strength = S["lode_producer_au_primary"] if producer else S["lode_mine_au_primary"]
            dep_class = "lode"
        else:
            strength = S["au_secondary"]
            dep_class = "unknown"
        n_workings = (len(wtree.query_ball_point([rep.geometry.x, rep.geometry.y], r=300))
                      if wtree is not None else 0)
        sites.append(dict(
            occ_id=occ_id, name=rep["name"],
            source_ids=";".join(grp["source"] + ":" + grp["source_id"]),
            n_records=len(grp), n_sources=grp["source"].nunique(),
            is_gold=True, deposit_class=dep_class, gold_primary=gold_primary,
            producer=producer, base_strength=strength,
            district=next((d for d in grp["district"] if d), ""),
            commodities=rep["commodities"], n_workings_300m=n_workings,
            geometry=rep.geometry))

    occ = gpd.GeoDataFrame(sites, crs=CRS)
    print("deposit_class:", occ["deposit_class"].value_counts().to_dict())
    print("producers:", int(occ["producer"].sum()),
          "| placer sites:", int((occ['deposit_class']=='placer').sum()),
          "| multi-source sites:", int((occ['n_sources']>=2).sum()))

    occ.to_file(GPKG, layer="occurrences", driver="GPKG")
    gold_members = gold[["cluster", "source", "source_id", "name", "geometry"]].copy()
    gold_members.to_file(GPKG, layer="occurrence_members", driver="GPKG")
    rec[~rec["is_gold"]].drop(columns="nname").to_file(GPKG, layer="occurrences_nongold", driver="GPKG")
    print(f"wrote {len(occ)} occurrences -> {GPKG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
