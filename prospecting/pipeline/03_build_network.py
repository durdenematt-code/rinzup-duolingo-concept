"""Stage 03 — build the scored stream network from NHDPlus HR.

Reads flowlines + VAAs straight out of the downloaded GDB zip (no unzip),
keeps the Snohomish HUC8 (17110009) reaches inside the study bbox, joins
navigation/slope/drainage attributes, marks segments below Culmback Dam,
and writes `stream_segments` + `watersheds` layers.
"""
import sys

import geopandas as gpd
import pandas as pd
import pyogrio
from shapely.geometry import Point

from common import BBOX_4326, CRS, DAMS, GPKG, INTERIM, RAW, SCORED_HUC8, ensure_dirs

# unzipped once by stage 01 — /vsizip random access on the 482 MB archive is
# unusably slow for filtered reads
GDB = str(RAW / "NHDPLUS_H_1711_HU4_GDB.gdb")

# FTypes to keep: 460 StreamRiver, 558 ArtificialPath (thalweg through
# waterbodies). Dropped: 336 canal/ditch, 428 pipeline, 334 connector, 566 coast.
KEEP_FTYPE = {460, 558}


def main() -> int:
    ensure_dirs()
    print("Reading flowlines (HUC8 filter)...")
    fl = pyogrio.read_dataframe(
        GDB, layer="NHDFlowline", bbox=BBOX_4326,
        where=f"ReachCode LIKE '{SCORED_HUC8}%'",
        columns=["NHDPlusID", "GNIS_Name", "ReachCode", "FType", "FCode", "LengthKM"],
        force_2d=True,
    )
    print(f"  {len(fl)} flowlines in bbox/HUC8")
    fl = fl[fl["FType"].isin(KEEP_FTYPE)].copy()
    print(f"  {len(fl)} after FType filter")

    print("Reading VAA table...")
    vaa = pyogrio.read_dataframe(
        GDB, layer="NHDPlusFlowlineVAA", read_geometry=False,
        columns=["NHDPlusID", "StreamOrde", "Slope", "TotDASqKm",
                 "HydroSeq", "DnHydroSeq", "UpHydroSeq", "LevelPathI"],
    )
    fl = fl.merge(vaa, on="NHDPlusID", how="left", validate="1:1")
    n_novaa = fl["HydroSeq"].isna().sum()
    if n_novaa:
        print(f"  WARNING: {n_novaa} flowlines lack VAA rows; dropped")
        fl = fl.dropna(subset=["HydroSeq"])

    fl = fl.to_crs(CRS)
    # NHDPlus Slope is m/m; 1e-5 is the "unknown/flat" floor
    fl["slope_pct"] = (fl["Slope"].clip(lower=0) * 100).where(fl["Slope"] > 1e-5)
    fl["length_km"] = fl["LengthKM"]

    # Confluence flag: >=2 upstream segments point here
    inflow_counts = fl.groupby("DnHydroSeq").size()
    fl["n_inflows"] = fl["HydroSeq"].map(inflow_counts).fillna(0).astype(int)
    fl["is_junction"] = fl["n_inflows"] >= 2

    # Mark the dam segment itself (stage 04 attenuates influence whose path
    # crosses it) and, for display, the downstream reaches on the SAME river
    # (LevelPathI) — the receiving Skykomish is not sediment-starved and must
    # not inherit the flag.
    hydro_to_dn = dict(zip(fl["HydroSeq"], fl["DnHydroSeq"]))
    level_of = dict(zip(fl["HydroSeq"], fl["LevelPathI"]))
    fl["below_dam"] = False
    fl["is_dam_segment"] = False
    for dam in DAMS:
        pt = gpd.GeoSeries([Point(dam["lon"], dam["lat"])], crs="EPSG:4326").to_crs(CRS).iloc[0]
        # snap only to the named river's mainstem level path(s) — the nearest
        # raw flowline to a dam coordinate is often a minor side tributary
        mainstem_lps = fl.loc[fl["GNIS_Name"] == dam["river"], "LevelPathI"].unique()
        cand = fl[fl["LevelPathI"].isin(mainstem_lps)]
        seg = cand.loc[cand.geometry.distance(pt).idxmin()]
        dist = seg.geometry.distance(pt)
        print(f"  {dam['name']}: snapped to {seg['GNIS_Name']!r} (NHDPlusID {seg['NHDPlusID']}, {dist:.0f} m away)")
        if dist > 500:
            print("  WARNING: dam snapped >500 m from a flowline — check coordinates")
        fl.loc[fl["HydroSeq"] == seg["HydroSeq"], "is_dam_segment"] = True
        below = set()
        h = hydro_to_dn.get(seg["HydroSeq"])
        while h in hydro_to_dn and h not in below and level_of.get(h) == seg["LevelPathI"]:
            below.add(h)
            h = hydro_to_dn[h]
        fl.loc[fl["HydroSeq"].isin(below), "below_dam"] = True
    print(f"  {fl['below_dam'].sum()} same-river segments below dams")

    fl["segment_id"] = range(1, len(fl) + 1)
    out = fl[["segment_id", "NHDPlusID", "GNIS_Name", "ReachCode", "FType",
              "StreamOrde", "slope_pct", "TotDASqKm", "length_km",
              "HydroSeq", "DnHydroSeq", "UpHydroSeq", "LevelPathI",
              "n_inflows", "is_junction", "below_dam", "is_dam_segment", "geometry"]].copy()
    out.to_file(GPKG, layer="stream_segments", driver="GPKG")
    pd.DataFrame(out.drop(columns="geometry")).to_parquet(INTERIM / "stream_segments.parquet")
    print(f"Wrote {len(out)} segments -> {GPKG}:stream_segments")

    print("Reading watershed boundaries...")
    for lvl in ["WBDHU10", "WBDHU12"]:
        wb = pyogrio.read_dataframe(GDB, layer=lvl, bbox=BBOX_4326, force_2d=True)
        code_col = "HUC10" if lvl == "WBDHU10" else "HUC12"
        wb = wb[[code_col, "Name", "AreaSqKm", "geometry"]].to_crs(CRS)
        wb.to_file(GPKG, layer=lvl.lower(), driver="GPKG")
        print(f"  {len(wb)} {lvl} polygons -> {GPKG}:{lvl.lower()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
