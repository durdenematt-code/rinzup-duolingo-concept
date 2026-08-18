"""Stage 01b — regenerate raw extracts from locally downloaded bulk datasets.

Replaces the small service-query caches in data/raw/ with clips of the full
authoritative downloads (see docs/01_data_inventory.md):

  - WA DNR GER portal Mines & Minerals geodatabase (WGS_Mines_Minerals.gdb)
      -> wgs_gold_silver.geojson, wgs_metallic.geojson, wgs_mining_districts.geojson
  - USGS MRDS relational dump (rdbms-tab: MRDS.txt + Commodity.txt)
      -> mrds.geojson  (code_list rebuilt primaries-first from Commodity.txt,
         matching the WFS semantics stage 02 relies on)
  - USGS USMIN state extract (usmin-WA shapefiles)
      -> usmin_points.geojson  (columns lowercased to match the old WFS cache)

Everything is clipped to common.BBOX_4326 and written in EPSG:4326 with the
same filenames/schemas the old extracts used, so stage 02 runs unchanged.
The outputs are small and stay committed to the repo; the bulk sources live
outside it (SOURCES below) and only need to exist when this stage is re-run.
"""
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

from common import BBOX_4326, RAW, ensure_dirs

SOURCES = {
    "wgs_gdb": Path("~/Downloads/ger_portal_mines_minerals/WGS_Mines_Minerals.gdb").expanduser(),
    "mrds_tab": Path("~/Downloads/rdbms-tab").expanduser(),
    "usmin": Path("~/Downloads/usmin-WA").expanduser(),
}


def clip_4326(g):
    if g.crs is None:
        g = g.set_crs("EPSG:4326")
    g = g.to_crs("EPSG:4326")
    return g.cx[BBOX_4326[0]:BBOX_4326[2], BBOX_4326[1]:BBOX_4326[3]]


def write(g, name):
    out = RAW / name
    if out.exists():
        out.unlink()  # avoid GeoJSON append/schema-merge surprises
    g.to_file(out, driver="GeoJSON")
    print(f"  {name}: {len(g)} features")


def main() -> int:
    ensure_dirs()
    missing = [k for k, p in SOURCES.items() if not p.exists()]
    if missing:
        print(f"missing local sources: {missing} — see docs/01_data_inventory.md")
        return 1

    # ---- WGS gold/silver + metallic + districts --------------------------
    gdb = SOURCES["wgs_gdb"]
    for layer, name in [("Gold_Silver_Locations", "wgs_gold_silver.geojson"),
                        ("Metallic_Mineral_Locations", "wgs_metallic.geojson"),
                        ("Mining_Distircts_WA", "wgs_mining_districts.geojson")]:
        g = gpd.read_file(gdb, layer=layer, force_2d=True)
        write(clip_4326(g), name)

    # ---- MRDS ------------------------------------------------------------
    tab = SOURCES["mrds_tab"]
    mrds = pd.read_csv(tab / "MRDS.txt", sep="\t", dtype={"dep_id": str},
                       usecols=["dep_id", "name", "dev_stat", "url",
                                "longitude", "latitude"])
    mrds = mrds.dropna(subset=["longitude", "latitude"])
    mrds = mrds[(mrds["longitude"].between(BBOX_4326[0], BBOX_4326[2]))
                & (mrds["latitude"].between(BBOX_4326[1], BBOX_4326[3]))]
    com = pd.read_csv(tab / "Commodity.txt", sep="\t",
                      usecols=["dep_id", "code", "import", "line"],
                      dtype={"dep_id": str})
    com = com[com["dep_id"].isin(set(mrds["dep_id"]))]
    com["rank"] = com["import"].map({"Primary": 0, "Secondary": 1}).fillna(2)
    com = com.sort_values(["dep_id", "rank", "line"])
    code_list = com.groupby("dep_id")["code"].agg(" ".join)
    mrds["code_list"] = mrds["dep_id"].map(code_list).fillna("")
    mrds = mrds.rename(columns={"name": "site_name"})
    g = gpd.GeoDataFrame(
        mrds, geometry=gpd.points_from_xy(mrds["longitude"], mrds["latitude"]),
        crs="EPSG:4326").drop(columns=["longitude", "latitude"])
    write(g, "mrds.geojson")

    # ---- USMIN -----------------------------------------------------------
    us = gpd.read_file(SOURCES["usmin"] / "WA-point.shp")
    us.columns = [c.lower() if c != "geometry" else c for c in us.columns]
    write(clip_4326(us), "usmin_points.geojson")
    return 0


if __name__ == "__main__":
    sys.exit(main())
